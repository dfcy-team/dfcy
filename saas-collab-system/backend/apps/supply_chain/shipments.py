"""Versioned supplier/procurement shipment commands; private files stay atomic."""
import hashlib
import csv
from io import BytesIO, StringIO
from pathlib import PurePath
from uuid import uuid4
from zipfile import ZipFile, BadZipFile

from django.db import transaction
from django.db.models import Max, Sum
from rest_framework.exceptions import NotFound, PermissionDenied
from django.core.exceptions import ValidationError
from PIL import Image
from apps.accounts.models import CustomUser
from apps.files.models import AttachmentFile
from apps.products.models import ProductSKU
from .dates import business_date
from .models import BoxFileContent, BoxInfoAttachment, PurchaseOrder, ShipmentLine, SupplierShipment, domain_write
from .permissions import VIEW, MANAGE, accessible_orders
from .services import _date, _event, _internal, _key, _master, _matching_replay, _order, _positive_int, _price, _prior_event, _tenant_lock, _version, request_hash, shipment_delivery_details
from .supplier_products import shipment_line_product_details

MAX_BYTES = 10 * 1024 * 1024


def shipment_for(actor, pk, permission=MANAGE):
    orders = accessible_orders(actor, PurchaseOrder.objects.all(), permission)
    obj = SupplierShipment.objects.filter(tenant_id=actor.tenant_id, order__in=orders, pk=pk).select_related("order__supplier").first()
    if not obj:
        raise NotFound("发货单不存在或不在可操作范围内。")
    return obj


def editable(obj):
    return obj.status == "draft" and not obj.collection_arrived and not obj.dispatch_memberships.filter(active_guard=True).exists()


def assert_draft(obj):
    if not editable(obj):
        raise ValidationError("仅未集货的草稿可修改商品数量和箱号附件；请刷新后查看最新状态。")


def snapshot(obj, *, internal=False):
    member = obj.dispatch_memberships.filter(active_guard=True).select_related("batch").first()
    result = {
        "id": obj.pk, "number": obj.number, "order_id": obj.order_id,
        "order_number": obj.order.number, "supplier_name": obj.order.supplier.name,
        "country_code": obj.order.country_code_snapshot, "shipment_date": str(obj.shipment_date),
        "notes": obj.notes, "status": obj.status, "entry_mode": obj.entry_mode,
        "delivery_mode": obj.delivery_mode, "loading_address": obj.loading_address_snapshot,
        "collection_arrival_applicable": obj.delivery_mode != SupplierShipment.DeliveryMode.FACTORY_LOADING,
        "collection_arrived": obj.collection_arrived, "collection_arrived_at": obj.collection_arrived_at,
        "version": obj.version, "editable": editable(obj),
        "logistics_stage": member.batch.stage if member else "unmarked",
        "logistics_dates": {field: getattr(member.batch, field) if member else None
                           for field in ("departed_at", "arrived_port_at", "arrived_warehouse_at")},
        "lines": [], "attachments": [],
    }
    source_lines = list(obj.lines.filter(is_active=True).select_related('sku__spu__category_node', 'shipment__order'))
    details_by_line = shipment_line_product_details(source_lines)
    for line in source_lines:
        details = details_by_line.get(line.pk, {})
        row = {"id": line.pk, "sku_id": line.sku_id, "sku": line.sku_code_snapshot,
               "legacy_sku_code": line.sku.legacy_sku_code or '',
               "product_details": {"image_url": details.get('image_url', '')},
               "image_preview_url": (f"/api/internal/supply-chain/v2/supplier-shipments/{obj.pk}/skus/{line.sku_id}/image/" if internal else
                                     f"/api/external/supplier/supply-chain/v2/shipments/{obj.pk}/skus/{line.sku_id}/image/") if details.get('image_url') else '',
               "product_name": line.product_name_snapshot, "purchase_line_id": line.purchase_line_id,
               "quantity": line.quantity, "exception_type": line.exception_type, "excess_quantity": line.excess_quantity}
        if internal:
            row.update(unit_price=str(line.unit_price) if line.unit_price is not None else None,
                       purchase_price_snapshot=str(line.purchase_price_snapshot) if line.purchase_price_snapshot is not None else None)
        result["lines"].append(row)
    for attachment in obj.box_attachments.filter(is_active=True).select_related("file"):
        result["attachments"].append({"id": attachment.pk, "file_name": attachment.file.file_name,
                                      "file_size": attachment.file.file_size, "sha256": attachment.sha256})
    result["total_quantity"] = sum(row["quantity"] for row in result["lines"])
    if internal:
        result["price_editable"] = obj.status != "cancelled"
        result["price_adjustment_requires_reason"] = member is not None
    return result


def save_lines(actor, obj, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValidationError("发货单需包含 1 至 500 行商品。")
    external = actor.user_type == CustomUser.UserType.EXTERNAL
    old = {line.pk: line for line in obj.lines.filter(is_active=True)}
    used = set()
    values = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("商品行格式不正确。")
        if external and any(k in row for k in ("unit_price", "purchase_price_snapshot", "supplier_reference_price", "product_reference_price")):
            raise PermissionDenied("供应商不能修改采购价格。")
        sku = _master(ProductSKU, actor, row.get("sku_id"), is_active=True)
        candidates = obj.order.lines.filter(is_active=True, sku=sku)
        if row.get("purchase_line_id"):
            candidates = candidates.filter(pk=row["purchase_line_id"])
            if not candidates.exists():
                raise ValidationError("来源采购行须属于本采购单，且商品一致。")
        elif candidates.count() > 1:
            raise ValidationError("同一 SKU 有多条采购行，请选择具体来源行。")
        source = candidates.first()
        previous = old.get(row.get("id")) if row.get("id") else None
        if row.get("id") and (not previous or previous.pk in used):
            raise ValidationError("发货行标识不正确或重复。")
        if previous:
            used.add(previous.pk)
        same = previous and previous.sku_id == sku.pk and previous.purchase_line_id == (source.pk if source else None)
        price = previous.unit_price if same else (source.unit_price if source else None)
        if not external and "unit_price" in row:
            price = _price(row["unit_price"])
        values.append((sku, source, _positive_int(row.get("quantity")), price))
    offset = obj.lines.aggregate(n=Max("line_number"))["n"] or 0
    for previous in old.values():
        previous.is_active = False
        previous.save()
    for index, (sku, source, quantity, price) in enumerate(values, offset + 1):
        ShipmentLine.objects.create(tenant=actor.tenant, created_by=actor, shipment=obj, line_number=index,
            sku=sku, purchase_line=source, sku_code_snapshot=sku.sku_code, product_name_snapshot=sku.product_name,
            quantity=quantity, purchase_price_snapshot=source.unit_price if source else None, unit_price=price,
            exception_type="none" if source else "additional")
    recompute_excess(obj)


def recompute_excess(obj):
    cumulative = {}
    for line in obj.lines.filter(is_active=True).select_related("purchase_line"):
        source = line.purchase_line
        if source:
            if source.pk not in cumulative:
                cumulative[source.pk] = ShipmentLine.objects.filter(is_active=True, purchase_line=source,
                    shipment__status="submitted").exclude(shipment=obj).aggregate(n=Sum("quantity"))["n"] or 0
            previous = cumulative[source.pk]
            line.excess_quantity = max(0, previous + line.quantity - source.quantity) - max(0, previous - source.quantity)
            cumulative[source.pk] += line.quantity
            line.exception_type = "excess" if line.excess_quantity else "none"
        else:
            line.exception_type, line.excess_quantity = "additional", 0
        line.save()


def dated(payload):
    value = _date(payload.get("shipment_date", business_date()))
    if value > business_date():
        raise ValidationError("发货日期不能晚于今天。")
    return value


@transaction.atomic
def create_draft(actor, payload, key):
    from .numbering import number_for
    _tenant_lock(actor)
    order = _order(actor, payload.get("order_id"))
    if order.status != "confirmed":
        raise ValidationError("只能从已下单的采购单创建发货单。")
    digest = request_hash(payload)
    previous = SupplierShipment.objects.filter(tenant=actor.tenant, creation_key=_key(key)).first()
    if previous:
        shipment_for(actor, previous.pk)
        return _matching_replay(previous, digest)
    delivery_mode, loading_address = shipment_delivery_details(payload, order.supplier)
    with domain_write():
        obj = SupplierShipment.objects.create(tenant=actor.tenant, created_by=actor, order=order,
            number=payload.get("number") or number_for(actor, "supplier_shipment", f"SH-{business_date():%Y%m%d}-{uuid4().hex[:12].upper()}", order.country_code_snapshot), status="draft",
            shipment_date=dated(payload), notes=payload.get("notes", ""),
            delivery_mode=delivery_mode, loading_address_snapshot=loading_address,
            entry_mode="supplier" if actor.user_type == "external" else "procurement", creation_key=key, request_hash=digest)
        save_lines(actor, obj, payload.get("lines"))
        _event(actor, obj, "draft_created", key, payload, audit={"shipment_snapshot": snapshot(obj, internal=True)})
    return obj


@transaction.atomic
def update_draft(actor, pk, payload, key):
    _tenant_lock(actor)
    obj = shipment_for(actor, pk)
    if _prior_event(actor, obj, "draft_updated", key, payload):
        return obj
    _version(obj, _positive_int(payload.get("expected_version")))
    assert_draft(obj)
    delivery_mode, loading_address = shipment_delivery_details(payload, obj.order.supplier, obj)
    with domain_write():
        obj.delivery_mode, obj.loading_address_snapshot = delivery_mode, loading_address
        obj.shipment_date = dated({"shipment_date": payload.get("shipment_date", obj.shipment_date)})
        obj.notes = payload.get("notes", obj.notes)
        if "lines" in payload:
            save_lines(actor, obj, payload["lines"])
        obj.version += 1
        obj.save()
        _event(actor, obj, "draft_updated", key, payload, audit={"shipment_snapshot": snapshot(obj, internal=True)})
    return obj


@transaction.atomic
def action(actor, pk, payload, key, action_name):
    _tenant_lock(actor)
    obj = shipment_for(actor, pk)
    if _prior_event(actor, obj, action_name, key, payload):
        return obj
    _version(obj, _positive_int(payload.get("expected_version")))
    assert_draft(obj)
    with domain_write():
        if action_name == "submitted":
            if obj.delivery_mode == SupplierShipment.DeliveryMode.FACTORY_LOADING and not obj.loading_address_snapshot.strip():
                raise ValidationError("货柜上门装载须填写本次装柜地址后再提交。")
            if not obj.box_attachments.filter(is_active=True, content__isnull=False).exists():
                raise ValidationError("请先上传包含本次发货所有箱号信息的附件。")
            recompute_excess(obj)
            obj.status = "submitted"
        else:
            obj.status = "cancelled"
        obj.version += 1
        obj.save()
        _event(actor, obj, action_name, key, payload, audit={"shipment_snapshot": snapshot(obj, internal=True)})
    return obj


@transaction.atomic
def prices(actor, pk, payload, key):
    _internal(actor)
    _tenant_lock(actor)
    obj = shipment_for(actor, pk)
    if _prior_event(actor, obj, "prices_adjusted", key, payload):
        return obj
    _version(obj, _positive_int(payload.get("expected_version")))
    if obj.status == "cancelled":
        raise ValidationError("作废发货单不能调价。")
    if obj.dispatch_memberships.filter(active_guard=True).exists() and not str(payload.get('reason', '')).strip():
        raise ValidationError("已集货或入库后的调价须填写原因，保存后请重新计算批次成本。")
    rows = payload.get("lines")
    if not isinstance(rows, list) or not rows:
        raise ValidationError("请选择需调价的商品行。")
    active = {line.pk: line for line in obj.lines.filter(is_active=True)}
    ids = [row.get("id") for row in rows]
    if len(set(ids)) != len(ids) or any(pk not in active for pk in ids):
        raise ValidationError("商品行不属于本发货单或重复。")
    with domain_write():
        before = [{'id': active[row['id']].pk, 'unit_price': str(active[row['id']].unit_price)
                   if active[row['id']].unit_price is not None else None} for row in rows]
        for row in rows:
            line = active[row["id"]]
            line.unit_price = _price(row.get("unit_price"))
            line.save()
        obj.version += 1
        obj.save()
        _event(actor, obj, "prices_adjusted", key, payload, audit={"previous_prices": before,
               "shipment_snapshot": snapshot(obj, internal=True)})
    return obj


def validate_file(upload):
    if not upload or not 0 < upload.size <= MAX_BYTES:
        raise ValidationError("附件须为非空文件且不超过 10MB。")
    name = PurePath(upload.name.replace("\\", "/")).name
    if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
        raise ValidationError("附件名称不合法。")
    ext = PurePath(name).suffix.lower()
    body = upload.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValidationError("附件超过 10MB。")
    try:
        if ext == ".pdf":
            if not body.startswith(b"%PDF-") or b"%%EOF" not in body[-2048:]:
                raise ValueError()
            mime = "application/pdf"
        elif ext == ".xlsx":
            with ZipFile(BytesIO(body)) as archive:
                items = archive.infolist()
                if len(items) > 1000 or sum(i.file_size for i in items) > 50 * 1024 * 1024:
                    raise ValueError()
                names = set(archive.namelist())
                if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names) or any("vbaproject" in n.lower() for n in names):
                    raise ValueError()
                if any(b"<!DOCTYPE" in archive.read(n) or b"<!ENTITY" in archive.read(n) for n in names if n.endswith(".xml")):
                    raise ValueError()
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif ext in (".png", ".jpg", ".jpeg"):
            with Image.open(BytesIO(body)) as image:
                if image.width * image.height > 25000000:
                    raise ValueError()
                if image.format != ("PNG" if ext == ".png" else "JPEG"):
                    raise ValueError()
                image.verify()
            mime = "image/png" if ext == ".png" else "image/jpeg"
        elif ext == ".csv":
            contents = body.decode("utf-8-sig")
            if "\x00" in contents or not next(csv.reader(StringIO(contents)), None):
                raise ValueError()
            mime = "text/csv"
        else:
            raise ValueError()
    except (ValueError, UnicodeError, BadZipFile, OSError, RuntimeError, KeyError, Image.DecompressionBombError):
        raise ValidationError("附件格式不正确；请上传 PDF、XLSX、UTF-8 CSV、PNG 或 JPG。")
    return name, mime, body, hashlib.sha256(body).hexdigest()


@transaction.atomic
def upload_box(actor, pk, upload, expected_version, key):
    _tenant_lock(actor)
    obj = shipment_for(actor, pk)
    name, mime, body, digest = validate_file(upload)
    payload = {"expected_version": expected_version, "file_name": name, "sha256": digest}
    if _prior_event(actor, obj, "box_uploaded", key, payload):
        return obj
    _version(obj, expected_version)
    assert_draft(obj)
    if obj.box_attachments.filter(is_active=True).count() >= 20:
        raise ValidationError("每张发货单最多保留 20 个当前箱号附件。")
    with domain_write():
        file = AttachmentFile.objects.create(tenant=actor.tenant, uploaded_by=actor, file_name=name,
            file_path=f"sc2-private:{uuid4().hex}", file_type=mime, file_size=len(body),
            business_type="sc2_supplier_shipment", business_id=str(obj.pk), is_private=True)
        attachment = BoxInfoAttachment.objects.create(tenant=actor.tenant, created_by=actor, shipment=obj, file=file, sha256=digest)
        BoxFileContent.objects.create(tenant=actor.tenant, created_by=actor, attachment=attachment, body=body)
        obj.version += 1
        obj.save()
        _event(actor, obj, "box_uploaded", key, payload, audit={"attachment_id": attachment.pk})
    return obj


@transaction.atomic
def remove_box(actor, pk, attachment_id, payload, key):
    _tenant_lock(actor)
    obj = shipment_for(actor, pk)
    payload = {**payload, "attachment_id": attachment_id}
    if _prior_event(actor, obj, "box_removed", key, payload):
        return obj
    _version(obj, _positive_int(payload.get("expected_version")))
    assert_draft(obj)
    attachment = obj.box_attachments.filter(pk=attachment_id, is_active=True).first()
    if not attachment:
        raise NotFound("箱号附件不存在。")
    with domain_write():
        attachment.is_active = False
        attachment.save()
        obj.version += 1
        obj.save()
        _event(actor, obj, "box_removed", key, payload)
    return obj
