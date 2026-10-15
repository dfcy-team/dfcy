"""Bounded Excel preview/commit. The retained input and SHA identify original rows."""
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError
from defusedxml.common import DefusedXmlException
from openpyxl.utils.exceptions import InvalidFileException

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .dates import business_date
from openpyxl import load_workbook
from rest_framework.exceptions import NotFound

from apps.masterdata.models import CountrySiteMaster
from apps.products.models import ProductSKU
from .archives import allowed_suppliers
from .documents import IMPORT_HEADERS, IMPORT_SHEET
from .models import PurchaseImport, SupplierProductPrice, domain_write
from .permissions import MANAGE
from .services import _internal, _tenant_lock, _key, _matching_replay, _version, _event, _prior_event, create_purchase_order

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 1000


def _read_workbook(content):
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValidationError("Excel 文件须在 5MB 以内。")
    try:
        with ZipFile(BytesIO(content)) as archive:
            info = archive.infolist()
            if len(info) > 200 or sum(x.file_size for x in info) > 32 * 1024 * 1024 or any(x.flag_bits & 1 or "vbaproject" in x.filename.lower() for x in info):
                raise ValidationError("文件体积、加密或宏内容不符合导入要求。")
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
        if IMPORT_SHEET not in workbook.sheetnames:
            workbook.close()
            raise ValidationError("请使用模板中的“采购单导入”工作表。")
        sheet = workbook[IMPORT_SHEET]
        if (sheet.max_row or 0) > MAX_ROWS + 1 or (sheet.max_column or 0) > len(IMPORT_HEADERS):
            workbook.close()
            raise ValidationError("最多导入 1000 行，列数须与模板一致。")
        return workbook, sheet
    except (BadZipFile, OSError, KeyError, ValueError, ParseError, DefusedXmlException, InvalidFileException) as exc:
        raise ValidationError("无法读取文件，请上传未加密的 .xlsx 模板。") from exc


def preview_excel(actor, content):
    workbook, sheet = _read_workbook(content)
    try:
        header = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
        if header != IMPORT_HEADERS:
            raise ValidationError("表头必须与下载模板一致。")
        suppliers = {x.code: x for x in allowed_suppliers(actor, MANAGE).filter(status="active")}
        countries = {x.code: x for x in CountrySiteMaster.objects.filter(tenant=actor.tenant, status="active")}
        errors, groups, source_rows, error_count = [], {}, 0, 0

        def error(row, field, message):
            nonlocal error_count
            error_count += 1
            if len(errors) < 20:
                errors.append({"row": row, "field": field, "message": message})

        for cells in sheet.iter_rows(min_row=2, max_col=len(IMPORT_HEADERS)):
            if all(cell.value is None for cell in cells):
                continue
            source_rows += 1
            row_number = cells[0].row
            if any(cell.data_type == "f" or cell.data_type == "e" for cell in cells):
                error(row_number, "单元格", "不能使用公式或 Excel 错误值。")
                continue
            values = [cell.value for cell in cells]
            try:
                group_key, supplier_code, country_code, sku_code = [str(x).strip() if x is not None else "" for x in values[:4]]
                if not group_key or len(group_key) > 80:
                    raise ValueError("导入分组号必填且最多 80 字符。")
                supplier, country = suppliers.get(supplier_code), countries.get(country_code)
                if not supplier or not country:
                    raise ValueError("供应商或国家编码不存在、已停用或无权访问。")
                sku = ProductSKU.objects.filter(tenant=actor.tenant, sku_code=sku_code, is_active=True).first()
                if not sku:
                    raise ValueError("商品 SKU 不存在或已停用。")
                qty = Decimal(str(values[4]))
                if isinstance(values[4], bool) or not qty.is_finite() or qty <= 0 or qty != qty.to_integral_value() or qty > 2147483647:
                    raise ValueError("采购数量须为正整数。")
                price = values[5]
                if price is None or price == "":
                    recent = SupplierProductPrice.objects.filter(tenant=actor.tenant, supplier=supplier, sku=sku, effective_date__lte=business_date()).first()
                    price = recent.unit_price if recent else sku.purchase_price
                if price is not None:
                    price = Decimal(str(price))
                    if not price.is_finite() or price < 0 or price >= Decimal("10000000000") or price != price.quantize(Decimal("0.0001")):
                        raise ValueError("单价须为非负数，最多 10 位整数、4 位小数。")
                reference, notes = str(values[6] or ""), str(values[8] or "")
                order_date = values[7] or business_date()
                if isinstance(order_date, datetime):
                    order_date = order_date.date()
                if isinstance(order_date, str):
                    order_date = date.fromisoformat(order_date)
                if not isinstance(order_date, date) or order_date > business_date():
                    raise ValueError("下单日期须为 YYYY-MM-DD，且不能晚于今天。")
                if len(reference) > 120 or len(notes) > 10000:
                    raise ValueError("备注单号最多 120 字符，备注最多 10000 字符。")
                header_data = {"supplier_id": supplier.pk, "country_id": country.pk, "reference_number": reference,
                               "order_date": str(order_date), "notes": notes}
                group = groups.get(group_key)
                if group and group["payload_header"] != header_data:
                    raise ValueError("同一分组的供应商、国家、备注单号、日期及备注必须一致。")
                if group is None:
                    group = groups[group_key] = {"group_key": group_key, "supplier_name": supplier.name, "country_name": country.name,
                        "reference_number": reference, "payload_header": header_data, "lines": []}
                if any(x["sku_id"] == sku.pk and x["unit_price"] != (str(price) if price is not None else None) for x in group["lines"]):
                    raise ValueError("同一分组的同一 SKU 不能填写不同单价。")
                group["lines"].append({"sku_id": sku.pk, "quantity": int(qty), "unit_price": str(price) if price is not None else None, "import_row_number": row_number})
            except (ValueError, TypeError, ArithmeticError) as exc:
                error(row_number, "数据行", str(exc) if isinstance(exc, ValueError) else "数量、单价或日期格式不正确。")
        if not source_rows:
            error(0, "文件", "文件没有采购明细。")
        if len(groups) > 100:
            error(0, "分组", "最多导入 100 张采购单。")
        missing = 0
        total_quantity, total_amount = 0, Decimal(0)
        for group in groups.values():
            lines = group["lines"]
            group["lines_count"] = len(lines)
            group["total_quantity"] = sum(x["quantity"] for x in lines)
            complete = all(x["unit_price"] is not None for x in lines)
            amount = sum((x["quantity"] * Decimal(x["unit_price"]) for x in lines if x["unit_price"] is not None), Decimal(0))
            group["total_amount"] = str(amount) if complete else None
            missing += sum(x["unit_price"] is None for x in lines)
            total_quantity += group["total_quantity"]
            total_amount += amount
        return {"valid": error_count == 0, "rows_count": source_rows, "groups_count": len(groups),
                "error_count": error_count, "errors": errors, "groups": list(groups.values()),
                "missing_prices_count": missing, "total_quantity": total_quantity,
                "total_amount": str(total_amount) if missing == 0 else None}
    except (ParseError, DefusedXmlException, KeyError, IndexError) as exc:
        raise ValidationError("Excel 结构无效，请使用下载的模板重新保存。") from exc
    finally:
        workbook.close()


@transaction.atomic
def create_import(actor, filename, content, *, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    key = _key(idempotency_key)
    digest = sha256(content).hexdigest()
    previous = PurchaseImport.objects.filter(tenant=actor.tenant, creation_key=key).first()
    if previous:
        if previous.created_by_id != actor.pk:
            raise NotFound("导入任务不可访问。")
        return _matching_replay(previous, digest)
    if not filename.lower().endswith(".xlsx"):
        raise ValidationError("请上传 .xlsx 文件。")
    preview = preview_excel(actor, content)
    with domain_write():
        return PurchaseImport.objects.create(tenant=actor.tenant, created_by=actor, filename=filename[:255],
            file_sha256=digest, file_content=content, creation_key=key, request_hash=digest, preview=preview)


@transaction.atomic
def commit_import(actor, job_id, *, expected_version, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    job = PurchaseImport.objects.filter(tenant=actor.tenant, created_by=actor, pk=job_id).first()
    if job is None:
        raise NotFound("导入任务不可访问。")
    payload = {"expected_version": expected_version}
    if _prior_event(actor, job, "import_committed", idempotency_key, payload):
        return job
    _version(job, expected_version)
    if job.committed_at:
        return job
    if not job.preview["valid"]:
        raise ValidationError("请修正预览错误后重新上传。")
    # Check current authorization/master availability again; prices remain the preview snapshot.
    with domain_write():
        ids = []
        for index, group in enumerate(job.preview["groups"]):
            data = {**group["payload_header"], "source_kind": "import", "import_batch_ref": f"IMPORT-{job.pk}-{job.file_sha256[:12]}", "lines": group["lines"]}
            order = create_purchase_order(actor, data, idempotency_key=f"import-{job.pk}-{index}")
            ids.append(order.pk)
        job.order_ids, job.committed_at, job.version = ids, timezone.now(), job.version + 1
        job.save()
        _event(actor, job, "import_committed", idempotency_key, payload, audit={"order_ids": ids})
    return job


def import_data(job):
    # Only the owner can see a preview or original file. Credentials never enter it.
    preview = {**job.preview, "groups": [{k: v for k, v in group.items() if k not in {"payload_header", "lines"}} for group in job.preview["groups"]]}
    return {"id": job.pk, "version": job.version, "filename": job.filename, "file_sha256": job.file_sha256,
            "committed_at": job.committed_at, "order_ids": job.order_ids, "preview": preview}
