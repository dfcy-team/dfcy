import hashlib
import io
import json
import stat
import zipfile
from datetime import date, datetime
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Q
from openpyxl import load_workbook
from defusedxml.common import DefusedXmlException
from rest_framework.exceptions import APIException, ValidationError

from apps.commerce.models import SalesOrder
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSKU

from .registration_models import RegistrationImportBatch
from .registration_services import create_registration, digest, masked, require, store_for, upload_evidence


SCHEMA = json.loads(Path(__file__).with_name("registration_import_schema.json").read_text(encoding="utf-8"))
TEXT_FIELDS = {"store_code", "order_number", "group", "old_sku", "new_sku", "phone", "payment_account", "transaction_reference"}
DECIMALS = {"order_amount", "fee_amount", "exchange_rate", "amount"}


def registration_template(kind):
    path = Path(__file__).with_name("templates") / f"{kind}.xlsx"
    if kind == "gcash":
        return path.open("rb")
    workbook = load_workbook(path)
    workbook["登记"].delete_cols(len(SCHEMA[kind]))
    for row in workbook["说明"].iter_rows():
        if row[0].value == "使用步骤":
            row[1].value = "填写登记页，仅上传xlsx，校验预览后确认导入。无需截图或附件。只生成草稿，不自动审批、不付款。"
        elif row[0].value == "附件":
            row[1].value = "本类型无需截图或附件。"
    content = io.BytesIO()
    workbook.save(content)
    workbook.close()
    content.seek(0)
    return content


def safe_zip(content, *, spreadsheet=False):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        entries = archive.infolist()
        if len(entries) > (5000 if spreadsheet else 100) or sum(entry.file_size for entry in entries) > 25 * 1024 * 1024:
            raise ValueError()
        names = set()
        for entry in entries:
            name = entry.filename
            if name in names or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError()
            names.add(name)
            if not spreadsheet and (entry.is_dir() or "/" in name or "\\" in name or name in {".", ".."} or ":" in name or entry.file_size > 5 * 1024 * 1024):
                raise ValueError()
            if spreadsheet and ("vbaProject" in name or name.startswith("xl/externalLinks/")):
                raise ValueError()
        return archive
    except (zipfile.BadZipFile, ValueError):
        raise ValidationError("压缩包包含重复／不安全路径、加密内容或超出大小限制。") from None


def read_inputs(kind, excel, attachment_zip):
    if not excel or not excel.name.lower().endswith(".xlsx") or excel.size > 5 * 1024 * 1024:
        raise ValidationError("请上传不超过5MB的xlsx模板。")
    content = excel.read()
    checked = safe_zip(content, spreadsheet=True)
    checked.close()
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
        if "登记" not in workbook.sheetnames:
            raise ValueError()
        sheet = workbook["登记"]
        fields = SCHEMA[kind]
        if kind != "gcash" and sheet.max_column == len(fields) - 1:
            fields = fields[:-1]
        if sheet.max_row > 501 or sheet.max_column != len(fields):
            raise ValueError()
        cells = list(sheet.iter_rows())
        if [cell.value for cell in cells[0]] != [label for _, label in fields]:
            raise ValueError()
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, DefusedXmlException):
        raise ValidationError("模板表头不匹配或超过500行，请重新下载模板。") from None
    finally:
        if "workbook" in locals():
            workbook.close()
    attachments = {}
    archive_content = b""
    if attachment_zip:
        if attachment_zip.size > 25 * 1024 * 1024:
            raise ValidationError("附件ZIP不能超过25MB。")
        archive_content = attachment_zip.read()
        with safe_zip(archive_content) as archive:
            for entry in archive.infolist():
                attachments[entry.filename] = archive.read(entry)
    groups = {}
    for row_no, row in enumerate(cells[1:], 2):
        if not any(cell.value is not None for cell in row):
            continue
        values, errors = {}, []
        for (field, label), cell in zip(fields, row):
            value = cell.value
            if cell.data_type == "f":
                errors.append(f"{label}不允许公式")
                value = None
            if field in TEXT_FIELDS and value is not None and not isinstance(value, str):
                errors.append(f"{label}必须为文本，避免前导零丢失")
            if field in DECIMALS and value is not None:
                value = str(value)
            if field == "rate_date" and hasattr(value, "date"):
                value = value.date().isoformat()
            if field == "paid_at" and isinstance(value, (date, datetime)):
                value = (value.date() if isinstance(value, datetime) else value).isoformat()
            values[field] = value if value is not None else ""
        identity = tuple(str(values.get(field, "")) for field in ("store_code", "order_number", "group"))
        if not identity[0] or not identity[2] or (kind != "gcash" and not identity[1]):
            errors.append("店铺／登记分组号／必填订单号缺失")
        bucket = groups.setdefault(identity, {"rows": [], "data": [], "errors": []})
        bucket["rows"].append(row_no)
        bucket["data"].append(values)
        bucket["errors"].extend(errors)
    if not groups:
        raise ValidationError("模板没有登记数据。")
    file_hash = hashlib.sha256(content + b"\0" + archive_content).hexdigest()
    return groups, attachments, file_hash


def group_payload(user, kind, identity, group):
    if group["errors"]:
        raise ValidationError("；".join(group["errors"]))
    store = StoreMaster.objects.filter(tenant=user.tenant, code=identity[0]).first()
    if not store:
        raise ValidationError("店铺编码不存在或不属于当前租户。")
    store_for(user, kind, "import", store.pk)
    order = None
    if identity[1]:
        order = SalesOrder.objects.filter(tenant=user.tenant, store=store, external_order_id=identity[1]).first()
        if not order:
            raise ValidationError("订单号不存在或不属于当前店铺。")
    first = group["data"][0]
    filenames = set()
    for data in group["data"]:
        filenames.update(name.strip() for name in str(data.get("attachments", "")).split(";") if name.strip())
    if len(filenames) > 10:
        raise ValidationError("每张登记最多10张截图。")
    if kind == "exchange":
        if any(data["reason"] != first["reason"] or data["note"] != first["note"] for data in group["data"]):
            raise ValidationError("同一申请的原因和备注必须一致。")
        changes = []
        for data in group["data"]:
            action = {"增加": "add", "减少": "reduce", "替换": "replace"}.get(data["action"])
            if not action:
                raise ValidationError("变化类型必须为替换、增加或减少。")
            change = {"action": action}
            for sku_field, qty_field, id_field in (("old_sku", "reduce_quantity", "old_sku_id"), ("new_sku", "add_quantity", "new_sku_id")):
                if data[sku_field] or data[qty_field] != "":
                    matches = list(ProductSKU.objects.filter(tenant=user.tenant, is_active=True).filter(
                        Q(sku_code=data[sku_field]) | Q(legacy_sku_code=data[sku_field]))[:2])
                    if not matches:
                        raise ValidationError("原／新SKU不存在或失效。")
                    if len(matches) > 1:
                        raise ValidationError("SKU编码匹配多个有效商品，请核对内部新／旧SKU编码。")
                    sku = matches[0]
                    qty = data[qty_field]
                    if type(qty) is not int:
                        raise ValidationError("增加／减少数量必须为整数。")
                    change.update({id_field: sku.pk, qty_field: qty})
            changes.append(change)
        payload = {"changes": changes, "reason": first["reason"], "note": first["note"]}
    else:
        if len(group["data"]) != 1:
            raise ValidationError("推广／GCash每张登记只能一行，请使用不同分组号。")
        payload = {k: v for k, v in first.items() if k not in {"store_code", "order_number", "group", "attachments", "store_currency"}}
        if kind == "promotion" and first["store_currency"] != store.currency:
            raise ValidationError("表格店铺币种与当前店铺站点币种不一致。")
        if kind == "gcash":
            payload["type"] = {"退款": "refund", "其他": "other"}.get(first["type"], "")
            if not filenames:
                raise ValidationError("GCash批量登记必须匹配截图文件。")
    return store, order, payload, filenames


def process_group(user, kind, identity, group, attachments, file_hash, preview, *, historical=False):
    with transaction.atomic():
        store, order, payload, filenames = group_payload(user, kind, identity, group)
        if filenames - set(attachments):
            raise ValidationError("指定附件在ZIP中缺失。")
        if historical and filenames:
            raise ValidationError("历史换货补录暂不支持附件，请保留原始来源文件备查。")
        row, created = create_registration(user, kind, store.pk, order.pk if order else None, payload,
                                           "import:" + digest([kind, identity]), batch_key=file_hash, permission_action="import", historical=historical)
        if created and historical:
            row.snapshot["import_source"] = {"file_hash": file_hash, "group": identity[2], "rows": group["rows"],
                                             "original_changes": group["data"]}
            row.save(update_fields=["snapshot"])
        if created:
            for name in sorted(filenames):
                upload_evidence(user, kind, row.pk, SimpleUploadedFile(name, attachments[name]), permission_action="import")
        result = {"rows": group["rows"], "group": identity[2], "store_id": store.pk, "store_code": store.code,
                  "order_number": identity[1], "attachment_count": len(filenames), "valid": True,
                  "status": "existing" if not created else "preview" if preview else "created",
                  "id": None if preview else row.pk, "payload": masked(row.payload), "snapshot": row.snapshot}
        if preview:
            transaction.set_rollback(True)
        return result


def run_import(user, kind, excel, attachment_zip, *, confirm=False, expected_hash="", valid_only=False, historical=False):
    require(user, kind, "import")
    if type(historical) is not bool or (historical and kind != "exchange"):
        raise ValidationError("历史补录仅适用于换货登记。")
    groups, attachments, file_hash = read_inputs(kind, excel, attachment_zip)
    if historical:
        file_hash = digest(["historical_exchange", file_hash])
    if confirm and expected_hash != file_hash:
        raise ValidationError("上传内容与预览不一致，请重新校验预览。")
    results = []
    for identity, group in groups.items():
        try:
            results.append(process_group(user, kind, identity, group, attachments, file_hash, preview=True, historical=historical))
        except (APIException, IntegrityError) as exc:
            results.append({"rows": group["rows"], "group": identity[2], "valid": False, "status": "error", "error": str(exc.detail) if isinstance(exc, APIException) else "登记与已有申请冲突。"})
    if not confirm:
        return {"file_hash": file_hash, "results": results, "confirmed": False}
    if any(not row["valid"] for row in results) and not valid_only:
        raise ValidationError("存在错误申请，未导入。请修正重传，或明确选择仅导入有效申请。")
    # Recheck every valid group in its own transaction at confirmation time.
    for index, (identity, group) in enumerate(groups.items()):
        if not results[index]["valid"]:
            continue
        try:
            results[index] = process_group(user, kind, identity, group, attachments, file_hash, preview=False, historical=historical)
        except (APIException, IntegrityError) as exc:
            results[index] = {"rows": group["rows"], "group": identity[2], "valid": False, "status": "error", "error": str(exc.detail) if isinstance(exc, APIException) else "并发冲突，未导入此申请。"}
    batch, created = RegistrationImportBatch.objects.get_or_create(tenant=user.tenant, kind=kind, file_hash=file_hash, imported_by=user,
        defaults={"file_name": Path(excel.name).name[:255],
                  "attachment_name": Path(attachment_zip.name).name[:255] if attachment_zip else "",
                  "results": [{k: v for k, v in result.items() if k not in {"payload", "snapshot"}} for result in results]})
    if not created and batch.imported_by_id == user.pk:
        # Preserve the original creation result while allowing failed groups to recover.
        previous = {tuple(result["rows"]): result for result in batch.results}
        batch.results = [previous[tuple(result["rows"])] if result["status"] == "existing" and previous.get(tuple(result["rows"]), {}).get("valid") and previous[tuple(result["rows"])].get("id") == result.get("id")
                         else {k: v for k, v in result.items() if k not in {"payload", "snapshot"}} for result in results]
        batch.save(update_fields=["results"])
    return {"file_hash": file_hash, "batch_id": batch.pk, "results": results, "confirmed": True}
