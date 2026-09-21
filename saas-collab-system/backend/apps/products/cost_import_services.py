"""Two-phase CSV/XLSX import for append-only SKU cost versions."""
import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.models import DataImportLog
from apps.tenants.models import Tenant

from .cost_services import append_cost_version
from .models import ProductCostVersion, ProductSKU


EXPECTED_COLUMNS = (
    "sku_code", "effective_from", "effective_to", "currency", "purchase_cost",
    "freight_cost", "duty_cost", "packaging_cost", "other_cost", "confirmed_cost", "reason",
)
HEADER_ALIASES = {
    "SKU编码": "sku_code",
    "生效开始": "effective_from",
    "生效结束": "effective_to",
    "币种": "currency",
    "采购成本": "purchase_cost",
    "物流分摊": "freight_cost",
    "税费": "duty_cost",
    "包装费": "packaging_cost",
    "其他费用": "other_cost",
    "确认成本": "confirmed_cost",
    "调整原因": "reason",
}
AMOUNT_COLUMNS = ("purchase_cost", "freight_cost", "duty_cost", "packaging_cost", "other_cost")
TOKEN_SALT = "products.cost.import.v1"


def _xlsx_date_styles(archive, ns):
    if "xl/styles.xml" not in archive.namelist():
        return set()
    root = ElementTree.fromstring(archive.read("xl/styles.xml"))
    custom = {
        int(node.attrib["numFmtId"]): node.attrib.get("formatCode", "")
        for node in root.findall("x:numFmts/x:numFmt", ns)
    }
    built_in_dates = set(range(14, 23)) | set(range(45, 48))
    styles = set()
    for index, node in enumerate(root.findall("x:cellXfs/x:xf", ns)):
        num_fmt_id = int(node.attrib.get("numFmtId", 0))
        format_code = re.sub(r'"[^"]*"|\\.', "", custom.get(num_fmt_id, "")).lower()
        if num_fmt_id in built_in_dates or re.search(r"[ymdhis]", format_code):
            styles.add(index)
    return styles


def _xlsx_cell_value(cell, raw_value, shared, date_styles):
    if cell.attrib.get("t") == "s" and raw_value.isdigit() and int(raw_value) < len(shared):
        return shared[int(raw_value)]
    inline = cell.find("x:is", {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"})
    if inline is not None:
        return "".join(inline.itertext())
    style_index = int(cell.attrib.get("s", 0))
    if raw_value and style_index in date_styles:
        try:
            parsed = datetime(1899, 12, 30) + timedelta(days=float(raw_value))
            return parsed.isoformat(sep=" ")
        except ValueError:
            pass
    return raw_value


def _xlsx_rows(raw):
    """Read the first non-empty XLSX worksheet without an optional dependency."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        shared = []
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall("x:si", ns)]
        date_styles = _xlsx_date_styles(archive, ns)
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        rel_map = {node.attrib["Id"]: node.attrib["Target"] for node in rels.findall("r:Relationship", rel_ns)}
        ns["r"] = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        for sheet in workbook.findall("x:sheets/x:sheet", ns):
            rel_id = sheet.attrib.get("{%s}id" % ns["r"])
            target = rel_map.get(rel_id, "")
            if target.startswith("/"):
                path = target.lstrip("/")
            elif target.startswith("xl/"):
                path = target
            else:
                path = "xl/" + target.lstrip("/")
            if path not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(path))
            sparse_rows = []
            max_column = 0
            for row in root.findall(".//x:sheetData/x:row", ns):
                cells = {}
                for cell in row.findall("x:c", ns):
                    letters = re.match(r"[A-Z]+", cell.attrib.get("r", "A1")).group(0)
                    column = 0
                    for letter in letters:
                        column = column * 26 + ord(letter) - 64
                    value_node = cell.find("x:v", ns)
                    raw_value = "" if value_node is None else (value_node.text or "")
                    value = _xlsx_cell_value(cell, raw_value, shared, date_styles)
                    cells[column - 1] = value
                    max_column = max(max_column, column)
                sparse_rows.append(cells)
            rows = [[item.get(index, "") for index in range(max_column)] for item in sparse_rows]
            if any(any(str(value).strip() for value in row) for row in rows):
                return rows
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValidationError({"file": "Invalid XLSX file."}) from exc
    return []


def _tabular_rows(raw, filename):
    if filename.lower().endswith(".xlsx") or raw[:2] == b"PK":
        return _xlsx_rows(raw)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError({"file": "CSV must use UTF-8 encoding."}) from exc
    try:
        dialect = csv.Sniffer().sniff(text[:4096])
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def _datetime(value, field):
    value = str(value or "").strip()
    if not value and field == "effective_to":
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = None
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            parsed = datetime.fromisoformat(value) if fmt is None else datetime.strptime(value, fmt)
            break
        except (TypeError, ValueError):
            pass
    if parsed is None:
        raise ValueError("Use an ISO-8601 date or datetime.")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _decimal(value, field, *, required=False):
    value = str(value or "").strip()
    if not value and not required:
        return Decimal("0")
    if not value:
        raise ValueError("This value is required.")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Use a decimal number.") from exc
    if result < 0 or result.as_tuple().exponent < -4 or len(result.as_tuple().digits) > 16:
        raise ValueError("Use a non-negative decimal with at most 4 decimal places and 16 digits.")
    return result.quantize(Decimal("0.0001"))


def _overlaps(left_start, left_end, right_start, right_end):
    return (left_end is None or left_end > right_start) and (right_end is None or right_end > left_start)


def parse_and_validate(*, tenant, raw, filename=""):
    digest = hashlib.sha256(raw).hexdigest()
    rows = _tabular_rows(raw, filename)
    errors = []
    parsed = []
    if not rows:
        errors.append({"row": 1, "field": "file", "message": "The import file is empty."})
        return parsed, errors, digest
    headers = []
    for value in rows[0]:
        label = str(value or "").strip().lstrip("*").strip()
        headers.append(HEADER_ALIASES.get(label, label.lower()))
    missing = [field for field in EXPECTED_COLUMNS if field not in headers]
    if missing:
        errors.append({"row": 1, "field": "headers", "message": "Missing columns: %s." % ", ".join(missing)})
        return parsed, errors, digest
    index = {field: headers.index(field) for field in EXPECTED_COLUMNS}
    sku_map = {item.sku_code: item for item in ProductSKU.objects.filter(tenant=tenant)}
    for number, values in enumerate(rows[1:], start=2):
        if not any(str(value or "").strip() for value in values):
            continue
        record = {field: (values[position] if position < len(values) else "") for field, position in index.items()}
        row_errors = []
        sku_code = str(record["sku_code"] or "").strip()
        sku = sku_map.get(sku_code)
        if not sku:
            row_errors.append(("sku_code", "SKU does not exist in the current tenant."))
        cleaned = {"sku": sku, "sku_code": sku_code}
        for field in ("effective_from", "effective_to"):
            try:
                cleaned[field] = _datetime(record[field], field)
            except ValueError as exc:
                row_errors.append((field, str(exc)))
        for field in AMOUNT_COLUMNS:
            try:
                cleaned[field] = _decimal(record[field], field)
            except ValueError as exc:
                row_errors.append((field, str(exc)))
        try:
            cleaned["confirmed_cost"] = _decimal(record["confirmed_cost"], "confirmed_cost", required=True)
        except ValueError as exc:
            row_errors.append(("confirmed_cost", str(exc)))
        cleaned["currency"] = str(record["currency"] or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", cleaned["currency"]):
            row_errors.append(("currency", "Use a three-letter currency code."))
        cleaned["reason"] = str(record["reason"] or "").strip()
        if len(cleaned["reason"]) > 500:
            row_errors.append(("reason", "Cannot exceed 500 characters."))
        if cleaned.get("effective_from") and cleaned.get("effective_to") and cleaned["effective_to"] <= cleaned["effective_from"]:
            row_errors.append(("effective_to", "Must be later than effective_from."))
        if row_errors:
            errors.extend({"row": number, "field": field, "message": message} for field, message in row_errors)
        else:
            cleaned["row"] = number
            parsed.append(cleaned)

    # Reject overlaps within this batch.
    by_sku = {}
    for item in parsed:
        for prior in by_sku.setdefault(item["sku_code"], []):
            if _overlaps(item["effective_from"], item["effective_to"], prior["effective_from"], prior["effective_to"]):
                errors.append({"row": item["row"], "field": "effective_from", "message": f"Overlaps import row {prior['row']}."})
        by_sku[item["sku_code"]].append(item)

    # Match append_cost_version semantics: one preceding open interval may be
    # closed at the first imported boundary; every other database overlap is a conflict.
    for sku_code, imports in by_sku.items():
        existing = list(ProductCostVersion.objects.filter(tenant=tenant, sku=imports[0]["sku"]))
        for position, item in enumerate(sorted(imports, key=lambda value: value["effective_from"])):
            overlaps = [version for version in existing if _overlaps(item["effective_from"], item["effective_to"], version.effective_from, version.effective_to)]
            closable = [version for version in overlaps if position == 0 and version.effective_to is None and version.effective_from < item["effective_from"]]
            if len(overlaps) != len(closable) or len(closable) > 1:
                errors.append({"row": item["row"], "field": "effective_from", "message": "Cost interval overlaps an existing version."})
    return parsed, errors, digest


def preview_cost_import(*, tenant, raw, filename=""):
    rows, errors, digest = parse_and_validate(tenant=tenant, raw=raw, filename=filename)
    invalid_rows = {item["row"] for item in errors if isinstance(item.get("row"), int) and item["row"] > 1}
    total = len({item["row"] for item in rows}.union(invalid_rows))
    payload = {"tenant_id": tenant.pk, "digest": digest, "valid": not errors}
    return {
        "total": total,
        "valid": len({item["row"] for item in rows} - invalid_rows),
        "errors": errors,
        "digest": digest,
        "token": signing.dumps(payload, salt=TOKEN_SALT, compress=True),
    }


@transaction.atomic
def confirm_cost_import(*, tenant, actor, raw, filename, token, idempotency_key):
    key = str(idempotency_key or "").strip()
    if not 8 <= len(key) <= 128 or any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise ValidationError({"Idempotency-Key": "Use 8-128 printable ASCII characters."})
    try:
        token_data = signing.loads(token, salt=TOKEN_SALT, max_age=3600)
    except signing.BadSignature as exc:
        raise ValidationError({"token": "The preview token is invalid or expired."}) from exc
    rows, errors, digest = parse_and_validate(tenant=tenant, raw=raw, filename=filename)
    if token_data.get("tenant_id") != tenant.pk or token_data.get("digest") != digest:
        raise ValidationError({"file": "The file does not match the preview token."})
    # The tenant row serializes competing imports and makes the audit log a
    # durable idempotency ledger without adding a second domain table.
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    key_hash = hashlib.sha256(key.encode("ascii")).hexdigest()
    for log in DataImportLog.objects.filter(tenant=tenant, import_type="product_cost").order_by("-id"):
        detail = log.error_summary or {}
        if detail.get("idempotency_key_hash") != key_hash:
            continue
        if detail.get("digest") != digest:
            raise ValidationError({"Idempotency-Key": "This key was already used with a different file."})
        return detail["result"]

    if errors or not token_data.get("valid"):
        raise ValidationError({"errors": errors or [{"message": "The preview contained errors."}]})

    created = []
    for item in sorted(rows, key=lambda value: (value["sku_id"] if "sku_id" in value else value["sku"].pk, value["effective_from"])):
        version = append_cost_version(
            tenant=tenant, sku=item["sku"], actor=actor,
            status=ProductCostVersion.Status.CONFIRMED, source=ProductCostVersion.Source.IMPORT,
            currency=item["currency"], purchase_cost=item["purchase_cost"], freight_cost=item["freight_cost"],
            duty_cost=item["duty_cost"], packaging_cost=item["packaging_cost"], other_cost=item["other_cost"],
            system_cost=None, confirmed_cost=item["confirmed_cost"], effective_from=item["effective_from"],
            effective_to=item["effective_to"], reason=item["reason"],
        )
        created.append({"id": version.pk, "sku_code": item["sku_code"], "version_no": version.version_no})
    result = {"created": len(created), "versions": created, "digest": digest, "replayed": False}
    DataImportLog.objects.create(
        tenant=tenant, import_type="product_cost", file_name=filename[:255], status=DataImportLog.Status.SUCCESS,
        total_count=len(rows), success_count=len(rows), failed_count=0, created_by=actor,
        error_summary={"idempotency_key_hash": key_hash, "digest": digest, "result": result},
    )
    return result
