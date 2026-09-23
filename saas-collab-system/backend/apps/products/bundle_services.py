import hashlib
import csv
import io
import re
import secrets
import zipfile
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from .models import (
    ProductBundleChangeAudit,
    ProductBundleComponent,
    ProductBundleMigrationBatch,
    ProductBundleVersion,
    ProductBundleVersionComponent,
    ProductSKU,
    ProductSPU,
)


def component_payload(rows):
    return [
        {"component_sku_id": row.component_sku_id, "component_sku_code": row.component_sku.sku_code,
         "component_product_name": row.component_sku.product_name or row.component_sku.spu.product_name, "quantity": row.quantity,
         "cost_allocation_ratio": str(row.cost_allocation_ratio)}
        for row in rows
    ]


def create_bundle_version(*, bundle_sku, actor, effective_at=None, reason="", action="components_updated", before=None):
    components = list(bundle_sku.bundle_components.select_related("component_sku", "component_sku__spu"))
    next_version = (bundle_sku.bundle_versions.aggregate(value=Max("version"))["value"] or 0) + 1
    version = ProductBundleVersion.objects.create(
        tenant=bundle_sku.tenant,
        bundle_sku=bundle_sku,
        version=next_version,
        effective_at=effective_at or timezone.now(),
        reason=reason,
        created_by=actor,
    )
    ProductBundleVersionComponent.objects.bulk_create([
        ProductBundleVersionComponent(
            version=version,
            component_sku=row.component_sku,
            component_sku_code=row.component_sku.sku_code,
            component_name=row.component_sku.product_name or row.component_sku.spu.product_name,
            quantity=row.quantity,
            cost_allocation_ratio=row.cost_allocation_ratio,
        ) for row in components
    ])
    after = component_payload(components)
    ProductBundleChangeAudit.objects.create(
        tenant=bundle_sku.tenant, bundle_sku=bundle_sku, version=version, action=action,
        reason=reason, before_payload=before or [], after_payload=after, actor=actor,
    )
    return version


def validate_component_rows(tenant, rows, bundle_sku=None):
    if not rows:
        raise ValueError("components must not be empty")
    ids = [int(row["component_sku_id"] if "component_sku_id" in row else row["component_sku"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate component SKU")
    skus = {sku.id: sku for sku in ProductSKU.objects.select_related("spu").filter(tenant=tenant, id__in=ids, is_active=True)}
    if len(skus) != len(ids):
        raise ValueError("component SKU not found or inactive")
    for sku_id in ids:
        if skus[sku_id].spu.product_type == ProductSPU.ProductType.BUNDLE or (bundle_sku and sku_id == bundle_sku.id):
            raise ValueError("nested or self-referencing bundles are not supported")
    normalized = []
    for row, sku_id in zip(rows, ids):
        quantity = int(row["quantity"])
        if quantity < 1:
            raise ValueError("component quantity must be positive")
        try:
            ratio = Decimal(str(row.get("cost_allocation_ratio", 1)))
        except (InvalidOperation, TypeError):
            raise ValueError("cost allocation ratio must be a positive number")
        if not ratio.is_finite() or ratio <= 0 or ratio > Decimal("999999.9999") or ratio.as_tuple().exponent < -4:
            raise ValueError("cost allocation ratio must be a positive number with at most four decimals")
        normalized.append((skus[sku_id], quantity))
    return normalized


def _text(value):
    return str(value or "").strip()


def _header_key(value):
    return re.sub(r"[\s_*（）()]", "", _text(value)).casefold()


def _xlsx_rows(raw):
    """Read the first populated XLSX worksheet using only the stdlib."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        shared = []
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall("x:si", ns)]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall("r:Relationship", rel_ns)}
        for sheet in workbook.findall("x:sheets/x:sheet", {**ns, "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}):
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rel_id, "")
            path = target.lstrip("/") if target.startswith("/xl/") else (
                target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            )
            if path not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(path))
            output = []
            for row in root.findall(".//x:sheetData/x:row", ns):
                cells = {}
                for cell in row.findall("x:c", ns):
                    ref = cell.attrib.get("r", "A1")
                    column = re.match(r"[A-Z]+", ref).group(0)
                    value = cell.find("x:v", ns)
                    text = "" if value is None else value.text or ""
                    if cell.attrib.get("t") == "s" and text.isdigit() and int(text) < len(shared):
                        text = shared[int(text)]
                    inline = cell.find("x:is", ns)
                    if inline is not None:
                        text = "".join(inline.itertext())
                    cells[column] = text
                output.append(cells)
            if output:
                columns = sorted({key for row in output for key in row}, key=lambda value: (len(value), value))
                return [[row.get(column, "") for column in columns] for row in output]
    return []


def parse_legacy_bundle_file(raw, filename=""):
    """Normalize canonical CSV or BigSeller horizontal CSV/XLSX to relation rows."""
    if filename.lower().endswith(".xlsx") or raw[:2] == b"PK":
        table = _xlsx_rows(raw)
    else:
        text = raw.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096])
        except csv.Error:
            dialect = csv.excel
        table = list(csv.reader(io.StringIO(text), dialect))
    if len(table) < 2:
        raise ValueError("文件中没有可迁移数据")

    headers = [_header_key(value) for value in table[0]]
    aliases = {
        "legacy_bundle_spu": {"旧组合spu编码", "组合spu", "spu"},
        "legacy_bundle_sku": {"旧组合sku编码", "旧组合sku编号", "组合sku", "组合sku编号", "sku", "sku编号", "sku编号必填"},
        "legacy_component_sku": {"子sku旧编码", "子sku", "单品sku"},
        "quantity": {"数量", "单品数量"},
        "bundle_name": {"组合商品名称", "名称"},
        "image_url": {"imageurl", "图片链接", "图片"},
    }

    def index_for(field):
        return next((i for i, value in enumerate(headers) if value in aliases[field]), None)

    bundle_sku_index = index_for("legacy_bundle_sku")
    if bundle_sku_index is None:
        raise ValueError("未识别到组合 SKU 列")
    spu_index = index_for("legacy_bundle_spu")
    name_index = index_for("bundle_name")
    image_index = index_for("image_url")
    component_index = index_for("legacy_component_sku")
    quantity_index = index_for("quantity")
    component_columns = []
    for index, header in enumerate(headers):
        match = re.fullmatch(r"单品sku(\d+)", header)
        if not match:
            continue
        number = match.group(1)
        qty = next((i for i, value in enumerate(headers) if value == f"sku{number}数量"), None)
        component_columns.append((index, qty))
    if component_index is not None:
        component_columns = [(component_index, quantity_index)]
    if not component_columns:
        raise ValueError("未识别到子 SKU 关系列")

    rows = []
    for line, values in enumerate(table[1:], start=2):
        if not any(_text(value) for value in values):
            continue
        value = lambda index: _text(values[index]) if index is not None and index < len(values) else ""
        bundle_sku = value(bundle_sku_index)
        for component_col, quantity_col in component_columns:
            component_sku = value(component_col)
            quantity = value(quantity_col)
            if not component_sku and not quantity:
                continue
            rows.append({
                "line": line,
                "legacy_bundle_spu": value(spu_index),
                "legacy_bundle_sku": bundle_sku,
                "legacy_component_sku": component_sku,
                "quantity": quantity,
                "bundle_name": value(name_index),
                "image_url": value(image_index),
            })
    if not rows:
        raise ValueError("文件中没有可迁移的组合关系")
    return rows


def preview_legacy_migration(*, tenant, actor, rows):
    grouped = defaultdict(list)
    group_metadata = defaultdict(dict)
    errors = []
    rejected_rows = []
    for index, row in enumerate(rows, start=1):
        try:
            key = (_text(row.get("legacy_bundle_spu")), _text(row["legacy_bundle_sku"]))
            component = str(row["legacy_component_sku"]).strip()
            quantity = int(row["quantity"])
            if not key[1] or not component or quantity < 1:
                raise ValueError
            grouped[key].append((component, quantity, row.get("line", index)))
            if _text(row.get("image_url")):
                group_metadata[key]["image_url"] = _text(row.get("image_url"))
            if _text(row.get("bundle_name")):
                group_metadata[key]["bundle_name"] = _text(row.get("bundle_name"))
        except (KeyError, TypeError, ValueError):
            errors.append({"row": index, "code": "invalid_row"})
    requested_codes = {legacy_sku for _legacy_spu, legacy_sku in grouped}
    requested_codes.update(component for components in grouped.values() for component, _quantity, _line in components)
    matches_by_code = defaultdict(list)
    candidates = ProductSKU.objects.select_related("spu").filter(
        Q(legacy_sku_code__in=requested_codes) | Q(sku_code__in=requested_codes),
        tenant=tenant,
        is_active=True,
    )
    for candidate in candidates:
        for code in {candidate.legacy_sku_code, candidate.sku_code} & requested_codes:
            matches_by_code[code].append(candidate)

    normalized = []
    for (legacy_spu, legacy_sku), components in grouped.items():
        bundle_matches = matches_by_code[legacy_sku]
        if legacy_spu:
            bundle_matches = [item for item in bundle_matches if legacy_spu in {item.spu.legacy_spu_code, item.spu.spu_code}]
        if len(bundle_matches) != 1:
            bundle_error = {
                "line": min(line for _component, _quantity, line in components),
                "legacy_bundle_sku": legacy_sku,
                "code": "bundle_not_unique",
                "match_reason": "not_found" if not bundle_matches else "multiple_matches",
                "match_count": len(bundle_matches),
            }
            errors.append(bundle_error)
            rejected_rows.extend({
                "line": line,
                "legacy_bundle_spu": legacy_spu,
                "legacy_bundle_sku": legacy_sku,
                "legacy_component_sku": component,
                "quantity": quantity,
                **{key: bundle_error[key] for key in ("code", "match_reason", "match_count")},
            } for component, quantity, line in components)
            continue
        resolved = []
        preview_rows = []
        seen = set()
        component_errors = {}
        for legacy_component, quantity, line in components:
            matches = matches_by_code[legacy_component]
            if len(matches) != 1:
                component_error = {
                    "line": line,
                    "legacy_bundle_sku": legacy_sku,
                    "legacy_component_sku": legacy_component,
                    "code": "component_not_unique",
                    "match_reason": "not_found" if not matches else "multiple_matches",
                    "match_count": len(matches),
                }
                errors.append(component_error)
                component_errors[(line, legacy_component)] = component_error
                continue
            if matches[0].id == bundle_matches[0].id or matches[0].id in seen:
                component_error = {"line": line, "legacy_bundle_sku": legacy_sku, "legacy_component_sku": legacy_component, "code": "self_or_duplicate"}
                errors.append(component_error)
                component_errors[(line, legacy_component)] = component_error
                continue
            seen.add(matches[0].id)
            resolved.append({"component_sku_id": matches[0].id, "quantity": quantity})
            preview_rows.append({
                "line": line,
                "legacy_bundle_spu": legacy_spu or bundle_matches[0].spu.legacy_spu_code or bundle_matches[0].spu.spu_code,
                "legacy_bundle_sku": legacy_sku,
                "legacy_component_sku": legacy_component,
                "quantity": quantity,
                "status": "matched",
            })
        if len(resolved) == len(components):
            normalized.append({
                "bundle_sku_id": bundle_matches[0].id,
                "components": resolved,
                "preview_rows": preview_rows,
                **group_metadata.get((legacy_spu, legacy_sku), {}),
            })
        else:
            for component, quantity, line in components:
                component_error = component_errors.get((line, component), {"code": "bundle_contains_blocked_component"})
                rejected_rows.append({
                    "line": line,
                    "legacy_bundle_spu": legacy_spu or bundle_matches[0].spu.legacy_spu_code or bundle_matches[0].spu.spu_code,
                    "legacy_bundle_sku": legacy_sku,
                    "legacy_component_sku": component,
                    "quantity": quantity,
                    **{key: component_error[key] for key in ("code", "match_reason", "match_count") if key in component_error},
                })
    error_breakdown = Counter(
        f"{error['code']}:{error.get('match_reason', 'other')}"
        for error in errors
    )
    raw_token = secrets.token_urlsafe(32)
    batch = ProductBundleMigrationBatch.objects.create(
        tenant=tenant, token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), created_by=actor,
        normalized_rows=normalized,
        preview_summary={
            "input_rows": len(rows), "bundles_ready": len(normalized), "error_count": len(errors),
            "error_breakdown": dict(error_breakdown),
            "rows": [row for item in normalized for row in item["preview_rows"]][:200],
            "errors": errors,
            "rejected_rows": rejected_rows,
        },
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return raw_token, batch


@transaction.atomic
def confirm_legacy_migration(*, tenant, actor, token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    batch = ProductBundleMigrationBatch.objects.select_for_update().filter(tenant=tenant, token_hash=token_hash).first()
    if not batch or batch.status != batch.Status.PREVIEWED or batch.expires_at <= timezone.now():
        raise ValueError("preview token is invalid, expired, or already consumed")
    if not batch.normalized_rows:
        raise ValueError("preview contains no migratable bundles")
    migrated_count = 0
    runtime_rejected = []
    bundle_ids = {item["bundle_sku_id"] for item in batch.normalized_rows}
    for item in batch.normalized_rows:
        bundle = ProductSKU.objects.select_for_update().select_related("spu").get(tenant=tenant, pk=item["bundle_sku_id"])
        # A legacy bundle may reference another SKU that is also being converted
        # in this batch. Migrating both would create an unsupported nested bundle.
        # Skip only the dependent bundle and retain the independent migrations.
        if any(component["component_sku_id"] in bundle_ids for component in item["components"]):
            runtime_rejected.extend({
                **row,
                "code": "nested_bundle_component",
            } for row in item.get("preview_rows", []))
            continue
        before = component_payload(bundle.bundle_components.select_related("component_sku"))
        try:
            normalized = validate_component_rows(tenant, item["components"], bundle)
        except ValueError as exc:
            if str(exc) != "nested or self-referencing bundles are not supported":
                raise
            runtime_rejected.extend({
                **row,
                "code": "nested_bundle_component",
            } for row in item.get("preview_rows", []))
            continue
        bundle.spu.product_type = ProductSPU.ProductType.BUNDLE
        bundle.spu.save(update_fields=["product_type", "updated_at"])
        if item.get("image_url"):
            bundle.image_url = item["image_url"][:500]
            bundle.save(update_fields=["image_url", "updated_at"])
        bundle.bundle_components.all().delete()
        for component, quantity in normalized:
            ProductBundleComponent.objects.create(tenant=tenant, bundle_sku=bundle, component_sku=component, quantity=quantity)
        create_bundle_version(bundle_sku=bundle, actor=actor, reason="legacy bundle migration", action="legacy_migrated", before=before)
        migrated_count += 1
    rejected_rows = [*batch.preview_summary.get("rejected_rows", []), *runtime_rejected]
    batch.preview_summary = {
        **batch.preview_summary,
        "migrated": migrated_count,
        "skipped_errors": batch.preview_summary.get("error_count", 0) + len(runtime_rejected),
        "runtime_rejected_bundles": len({row.get("legacy_bundle_sku") for row in runtime_rejected}),
        "rejected_rows": rejected_rows,
    }
    batch.status = batch.Status.CONFIRMED
    batch.confirmed_at = timezone.now()
    batch.save(update_fields=["preview_summary", "status", "confirmed_at"])
    return batch
