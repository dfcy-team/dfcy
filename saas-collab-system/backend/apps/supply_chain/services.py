"""Transactional commands used by procurement HTTP and Excel import adapters.

Confirmed orders create an atomic notification outbox entry; external delivery
remains disabled. Local stock receipts are confirmed by the logistics service.
"""
import hashlib
import json
from uuid import uuid4
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .dates import business_date
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import CustomUser
from apps.masterdata.models import CountrySiteMaster, SupplierMaster, WarehouseMaster
from apps.products.models import ProductSKU
from apps.purchasing.supply_permissions import authorize_internal_supplier, require_internal_supply_permission
from apps.tenants.models import Tenant
from .models import (
    BusinessEvent, DispatchBatch, DispatchMembership, FreightCompany, InboundLine,
    InboundOrder, NotificationOutbox, OperatingAllocation, PurchaseLine,
    PurchaseOrder, ShipmentLine, SupplierShipment, SupplierProductPrice, SupplierPriceHistory, domain_write,
)
from .permissions import MANAGE, accessible_orders, internal_orders


def request_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()


def _key(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValidationError("A nonempty idempotency key of at most 128 characters is required.")
    return value


def _internal(actor):
    if not actor.is_active:
        raise PermissionDenied("An active procurement account is required.")
    require_internal_supply_permission(actor, MANAGE)


def _tenant_lock(actor):
    # A single tenant lock gives consistent lock order even for overlapping batches.
    Tenant.objects.select_for_update().get(pk=actor.tenant_id)


def _master(model, actor, pk, **filters):
    try:
        return model.objects.get(pk=pk, tenant_id=actor.tenant_id, **filters)
    except (model.DoesNotExist, ValueError, TypeError):
        raise ValidationError("A referenced master record is unavailable in this tenant.")


def _order(actor, pk, permission=MANAGE):
    order = accessible_orders(actor, PurchaseOrder.objects.all(), permission).filter(pk=pk).first()
    if order is None:
        raise NotFound("Purchase order is unavailable.")
    return order


def _matching_replay(record, digest):
    if record.request_hash != digest:
        raise ValidationError("The idempotency key was already used for different content.")
    return record


def _event(actor, record, action, key, payload, *, audit=None):
    return BusinessEvent.objects.create(
        tenant=actor.tenant, created_by=actor, aggregate_type=record._meta.model_name,
        aggregate_id=record.pk, aggregate_version=record.version,
        action=action, request_key=_key(key), request_hash=request_hash(payload),
        payload=json.loads(json.dumps({**payload, **(audit or {})}, default=str, ensure_ascii=False)),
    )


def _prior_event(actor, record, action, key, payload):
    event = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, aggregate_type=record._meta.model_name, aggregate_id=record.pk, action=action, request_key=_key(key)).first()
    if event:
        _matching_replay(event, request_hash(payload))
    return event


def _version(record, expected):
    if expected != record.version:
        raise ValidationError("The document has changed. Reload it before editing.")


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError("Quantity must be a positive integer.")
    return value


def _price(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValidationError("Invalid unit price.") from exc
    if not result.is_finite() or result < 0:
        raise ValidationError("Unit price must be finite and nonnegative.")
    return result


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else value
    except (ValueError, TypeError) as exc:
        raise ValidationError("请填写有效日期。") from exc


def publish_price(actor, supplier, sku, value, effective_date, *, order=None, notes=""):
    """Called under tenant lock/domain_write. Backdated prices only enter history."""
    price = SupplierProductPrice.objects.filter(tenant=actor.tenant, supplier=supplier, sku=sku).first()
    source = "purchase_order" if order else "manual"
    effective_date = _date(effective_date)
    applied = price is None or effective_date >= price.effective_date
    if price is None:
        price = SupplierProductPrice(tenant=actor.tenant, created_by=actor, supplier=supplier, sku=sku)
    else:
        price.version += 1
    if applied:
        price.unit_price, price.effective_date, price.source_kind = _price(value), effective_date, source
        price.source_order, price.source_order_version = order, order.version if order else None
        price.notes = notes
    price.save()
    SupplierPriceHistory.objects.create(
        tenant=actor.tenant, created_by=actor, version=price.version, price=price, unit_price=_price(value),
        effective_date=effective_date, source_kind=source, source_order=order,
        source_order_version=order.version if order else None, applied_to_current=applied, notes=notes,
    )
    return price


def _save_purchase_lines(actor, order, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValidationError("采购单需要 1–1000 条商品明细。")
    # Multiple rows for a SKU with conflicting prices cannot define its current price.
    prices_by_sku = {}
    next_number = (order.lines.order_by("-line_number").values_list("line_number", flat=True).first() or 0) + 1
    for index, row in enumerate(rows, next_number):
        sku = _master(ProductSKU, actor, row["sku_id"], is_active=True)
        latest = SupplierProductPrice.objects.filter(tenant=actor.tenant, supplier=order.supplier, sku=sku, effective_date__lte=business_date()).first()
        value = _price(row["unit_price"] if "unit_price" in row else (latest.unit_price if latest else sku.purchase_price))
        if sku.pk in prices_by_sku and prices_by_sku[sku.pk] != value:
            raise ValidationError("同一采购单的同一 SKU 不能填写不同采购价格。")
        prices_by_sku[sku.pk] = value
        qty = _positive_int(row["quantity"])
        allocations = row.get("operating_sources") or []
        if order.source_kind == PurchaseOrder.Source.OPERATING:
            if not allocations or sum(_positive_int(a["quantity"]) for a in allocations) != qty:
                raise ValidationError("Operating allocations must account for the purchase line quantity.")
        elif allocations:
            raise ValidationError("Manual/imported orders cannot invent operating sources.")
        import_row = row.get("import_row_number")
        if order.source_kind == PurchaseOrder.Source.IMPORT:
            _positive_int(import_row)
        line = PurchaseLine.objects.create(
            tenant=actor.tenant, created_by=actor, order=order, line_number=index,
            sku=sku, sku_code_snapshot=sku.sku_code, product_name_snapshot=sku.product_name,
            quantity=qty, product_reference_price=sku.purchase_price,
            supplier_reference_price=latest.unit_price if latest else None,
            unit_price=value, import_row_number=import_row,
        )
        for allocation in allocations:
            OperatingAllocation.objects.create(
                tenant=actor.tenant, created_by=actor, purchase_line=line,
                source_system=allocation["system"], source_order_id=allocation["order_id"],
                source_line_id=allocation["line_id"], allocated_quantity=allocation["quantity"],
                operating_line_id=allocation.get("operating_line_id"),
            )
    for sku_id, value in prices_by_sku.items():
        if value is not None:
            publish_price(actor, order.supplier, _master(ProductSKU, actor, sku_id), value, order.order_date, order=order)


def purchase_snapshot(order, lines=None):
    from .payment_terms import order_terms
    lines = list(order.lines.filter(is_active=True)) if lines is None else lines
    return {
        "id": order.pk, "number": order.number, "reference_number": order.reference_number,
        "supplier_id": order.supplier_id, "supplier_name": order.supplier.name,
        "country_id": order.country_id, "country_code": order.country_code_snapshot,
        "country_name": order.country.name, "source_kind": order.source_kind,
        "order_date": str(order.order_date), "notes": order.notes, "version": order.version,
        "status": order.status, "total_quantity": sum(x.quantity for x in lines),
        "supplier_terms": order_terms(order),
        "prices_complete": bool(lines) and all(x.unit_price is not None for x in lines),
        "total_amount": str(sum((x.quantity * x.unit_price for x in lines), Decimal(0))) if lines and all(x.unit_price is not None for x in lines) else None,
        "lines": [{"id": x.pk, "sku_id": x.sku_id, "sku": x.sku_code_snapshot,
                   "name": x.product_name_snapshot, "quantity": x.quantity,
                   "unit_price": str(x.unit_price) if x.unit_price is not None else None,
                   "product_reference_price": str(x.product_reference_price) if x.product_reference_price is not None else None,
                   "supplier_reference_price": str(x.supplier_reference_price) if x.supplier_reference_price is not None else None,
                   "import_row_number": x.import_row_number} for x in lines],
    }


@transaction.atomic
def update_purchase_order(actor, order_id, payload, *, expected_version, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    order = _order(actor, order_id)
    action_payload = {"expected_version": expected_version, "changes": payload}
    if _prior_event(actor, order, "draft_updated", idempotency_key, action_payload):
        return order
    _version(order, expected_version)
    if order.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("只能编辑草稿。")
    if order.source_kind == PurchaseOrder.Source.OPERATING:
        existing = list(order.lines.filter(is_active=True).prefetch_related('operating_sources'))
        if (payload['country_id'] != order.country_id or payload['supplier_id'] != order.supplier_id
                or len(payload['lines']) != len(existing)
                or sorted((r['sku_id'], r['quantity']) for r in payload['lines']) != sorted((r.sku_id, r.quantity) for r in existing)):
            raise ValidationError('运营拆单的国家、供应商和需求数量不能改写；请取消草稿后重新拆分。')
        by_sku = {r.sku_id: r for r in existing}
        if len(by_sku) != len(existing):
            raise ValidationError('该运营来源包含重复 SKU，请通过来源拆单重新处理。')
        payload = {**payload, 'lines': [{**r, 'operating_sources': [
            {'system': a.source_system, 'order_id': a.source_order_id, 'line_id': a.source_line_id,
             'quantity': a.allocated_quantity, 'operating_line_id': a.operating_line_id}
            for a in by_sku[r['sku_id']].operating_sources.all()]} for r in payload['lines']]}
    if payload.get("source_kind", order.source_kind) != order.source_kind:
        raise ValidationError("采购单创建来源不能修改。")
    if order.source_kind == PurchaseOrder.Source.IMPORT:
        original_rows = set(order.lines.filter(is_active=True).values_list("import_row_number", flat=True))
        if any(x.get("import_row_number") not in original_rows for x in payload.get("lines", [])):
            raise ValidationError("导入明细须保留原始行号；新增商品请直接新建采购单。")
    supplier = _master(SupplierMaster, actor, payload["supplier_id"], status="active")
    authorize_internal_supplier(actor, MANAGE, supplier.pk)
    country = _master(CountrySiteMaster, actor, payload["country_id"], status="active")
    before = purchase_snapshot(order)
    with domain_write():
        order.supplier, order.country = supplier, country
        order.country_code_snapshot = country.country_code.upper()
        order.reference_number, order.notes = payload.get("reference_number", ""), payload.get("notes", "")
        order.order_date = _date(payload.get("order_date", order.order_date))
        order.version += 1
        order.save()
        # Keep every previous row to preserve import/source and price history.
        for line in order.lines.filter(is_active=True):
            line.is_active = False
            line.save()
        _save_purchase_lines(actor, order, payload["lines"])
        _event(actor, order, "draft_updated", idempotency_key, action_payload, audit={"before": before, "after": purchase_snapshot(order)})
    return order


@transaction.atomic
def update_purchase_metadata(actor, order_id, payload, *, expected_version, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    order = _order(actor, order_id)
    action_payload = {"expected_version": expected_version, "changes": payload}
    if _prior_event(actor, order, "metadata_updated", idempotency_key, action_payload):
        return order
    _version(order, expected_version)
    with domain_write():
        before = {"reference_number": order.reference_number, "notes": order.notes}
        order.reference_number, order.notes = payload["reference_number"], payload.get("notes", "")
        order.version += 1
        order.save()
        _event(actor, order, "metadata_updated", idempotency_key, action_payload, audit={"before": before})
    return order


@transaction.atomic
def cancel_purchase_draft(actor, order_id, *, expected_version, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    order = _order(actor, order_id)
    payload = {"expected_version": expected_version}
    if _prior_event(actor, order, "draft_cancelled", idempotency_key, payload):
        return order
    _version(order, expected_version)
    if order.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("只能作废草稿；已下单采购单需要后续留痕更正流程。")
    with domain_write():
        order.status, order.version = PurchaseOrder.Status.CANCELLED, order.version + 1
        order.save()
        if order.source_kind == PurchaseOrder.Source.OPERATING:
            from apps.sales_management.operating_models import OperatingOrder
            source_orders = OperatingOrder.objects.filter(lines__purchase_allocations__purchase_line__order=order).distinct()
            for source in source_orders:
                source.version += 1
                source.save()
                _event(actor, source, 'purchase_allocation_released', idempotency_key, {'purchase_order_id': order.pk})
        _event(actor, order, "draft_cancelled", idempotency_key, payload)
    return order


@transaction.atomic
def create_purchase_order(actor, payload, *, idempotency_key):
    from .numbering import number_for
    _internal(actor)
    _tenant_lock(actor)
    key, digest = _key(idempotency_key), request_hash(payload)
    previous = PurchaseOrder.objects.filter(tenant_id=actor.tenant_id, creation_key=key).first()
    if previous:
        _order(actor, previous.pk)
        return _matching_replay(previous, digest)
    supplier = _master(SupplierMaster, actor, payload["supplier_id"], status="active")
    authorize_internal_supplier(actor, MANAGE, supplier.pk)
    country = _master(CountrySiteMaster, actor, payload["country_id"], status="active")
    source = payload.get("source_kind", PurchaseOrder.Source.MANUAL)
    rows = payload.get("lines") or []
    if not rows:
        raise ValidationError("A purchase order requires at least one line.")
    if source == PurchaseOrder.Source.IMPORT and not payload.get("import_batch_ref"):
        raise ValidationError("Imported orders require an import batch reference.")
    with domain_write():
        order = PurchaseOrder.objects.create(
            tenant=actor.tenant, created_by=actor, number=payload.get("number") or number_for(actor, "purchase_order", f"PO-{business_date():%Y%m%d}-{uuid4().hex[:12].upper()}", country.country_code.upper()),
            reference_number=payload.get("reference_number", ""), supplier=supplier,
            country=country, country_code_snapshot=country.country_code.upper(),
            source_kind=source, import_batch_ref=payload.get("import_batch_ref", ""),
            order_date=_date(payload.get("order_date", business_date())), notes=payload.get("notes", ""),
            creation_key=key, request_hash=digest,
        )
        _save_purchase_lines(actor, order, rows)
        _event(actor, order, "created", key, {"source_kind": source})
    return order


@transaction.atomic
def confirm_purchase_order(actor, order_id, *, expected_version, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    order = _order(actor, order_id)
    payload = {"expected_version": expected_version}
    if _prior_event(actor, order, "confirmed", idempotency_key, payload):
        return order
    _version(order, expected_version)
    if order.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("Only a draft purchase order can be confirmed.")
    lines = list(order.lines.filter(is_active=True))
    if not lines or any(line.unit_price is None for line in lines):
        raise ValidationError("Complete every purchase price before placing the order.")
    with domain_write():
        from .payment_terms import supplier_terms
        order.supplier_terms_snapshot = supplier_terms(order.supplier)
        order.status, order.confirmed_at, order.version = PurchaseOrder.Status.CONFIRMED, timezone.now(), order.version + 1
        order.save()
        from .supplier_products import enrich_snapshot
        snapshot = enrich_snapshot(purchase_snapshot(order, lines), actor.tenant_id, source='confirmation')
        event = _event(actor, order, "confirmed", idempotency_key, payload, audit={"purchase_snapshot": snapshot})
        # Freeze routing if present; network/file work stays outside this transaction.
        outbox = NotificationOutbox.objects.create(tenant=actor.tenant, created_by=actor, event=event, order=order, order_version=order.version)
        from .notifications import capture_binding
        capture_binding(outbox)
        if outbox.binding_id:
            outbox.save()
    return order


@transaction.atomic
def create_supplier_shipment(actor, payload, *, idempotency_key):
    from .numbering import number_for
    _tenant_lock(actor)
    order = _order(actor, payload["order_id"])
    if order.status != PurchaseOrder.Status.CONFIRMED:
        raise ValidationError("Shipment requires a confirmed purchase order.")
    key, digest = _key(idempotency_key), request_hash(payload)
    previous = SupplierShipment.objects.filter(tenant_id=actor.tenant_id, creation_key=key).first()
    if previous:
        _order(actor, previous.order_id)
        return _matching_replay(previous, digest)
    external = actor.user_type == CustomUser.UserType.EXTERNAL
    rows = payload.get("lines") or []
    if not rows:
        raise ValidationError("A shipment requires at least one line.")
    delivery_mode, loading_address = shipment_delivery_details(payload, order.supplier)
    with domain_write():
        shipment = SupplierShipment.objects.create(
            tenant=actor.tenant, created_by=actor, number=payload.get("number") or number_for(actor, "supplier_shipment",
                f"SH-{business_date():%Y%m%d}-{uuid4().hex[:12].upper()}", order.country_code_snapshot), order=order,
            status=SupplierShipment.Status.SUBMITTED,
            shipment_date=payload.get("shipment_date", business_date()),
            delivery_mode=delivery_mode, loading_address_snapshot=loading_address,
            entry_mode="supplier" if external else "procurement", notes=payload.get("notes", ""),
            creation_key=key, request_hash=digest,
        )
        for index, row in enumerate(rows, 1):
            if external and any(field in row for field in ("unit_price", "purchase_price_snapshot", "supplier_reference_price", "product_reference_price")):
                raise PermissionDenied("Supplier accounts cannot set purchase prices.")
            sku = _master(ProductSKU, actor, row["sku_id"], is_active=True)
            candidates = order.lines.filter(sku=sku, is_active=True)
            if row.get("purchase_line_id"):
                candidates = candidates.filter(pk=row["purchase_line_id"])
                if not candidates.exists():
                    raise ValidationError("Shipment source must match the purchase order and SKU.")
            elif candidates.count() > 1:
                raise ValidationError("Select a specific purchase source line for this SKU.")
            source = candidates.first()
            qty = _positive_int(row["quantity"])
            prior_qty = (ShipmentLine.objects.filter(is_active=True, purchase_line=source, shipment__status=SupplierShipment.Status.SUBMITTED).aggregate(total=Sum("quantity"))["total"] or 0) if source else 0
            excess = max(0, prior_qty + qty - source.quantity) - max(0, prior_qty - source.quantity) if source else 0
            snapshot = source.unit_price if source else None
            ShipmentLine.objects.create(
                tenant=actor.tenant, created_by=actor, shipment=shipment, line_number=index,
                sku=sku, purchase_line=source, sku_code_snapshot=sku.sku_code,
                product_name_snapshot=sku.product_name, quantity=qty, purchase_price_snapshot=snapshot,
                unit_price=snapshot if external else _price(row.get("unit_price", snapshot)),
                exception_type="additional" if source is None else ("excess" if excess else "none"), excess_quantity=excess,
            )
        _event(actor, shipment, "created", key, {"entry_mode": shipment.entry_mode})
    return shipment


def shipment_delivery_details(payload, supplier, current=None):
    """Capture the loading address on the shipment, without changing the supplier."""
    mode = payload.get('delivery_mode', current.delivery_mode if current else SupplierShipment.DeliveryMode.COLLECTION_CENTER)
    if mode not in SupplierShipment.DeliveryMode.values:
        raise ValidationError('请选择送集货中心或货柜上门装载。')
    address = ''
    if mode == SupplierShipment.DeliveryMode.FACTORY_LOADING:
        if 'loading_address' in payload:
            address = payload['loading_address']
        elif current and current.delivery_mode == mode:
            address = current.loading_address_snapshot
        else:
            address = supplier.loading_address or supplier.factory_address or ''
        if not isinstance(address, str) or len(address) > 4000:
            raise ValidationError('装柜地址须为不超过4000字的文本。')
        if not address.strip() and (not current or current.delivery_mode != mode):
            address = supplier.loading_address or supplier.factory_address or ''
        address = address.strip()
    return mode, address


def _internal_shipments(actor):
    orders = internal_orders(actor, PurchaseOrder.objects.all(), MANAGE)
    return SupplierShipment.objects.filter(tenant_id=actor.tenant_id, order__in=orders)


@transaction.atomic
def mark_collection_arrival(actor, shipment_id, *, expected_version, occurred_at, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    if timezone.is_naive(occurred_at):
        raise ValidationError("Use a timezone-aware collection arrival timestamp.")
    shipment = _internal_shipments(actor).filter(pk=shipment_id).first()
    if not shipment:
        raise NotFound("Shipment is unavailable.")
    payload = {"expected_version": expected_version, "occurred_at": occurred_at.isoformat()}
    if _prior_event(actor, shipment, "collection_arrival", idempotency_key, payload):
        return shipment
    _version(shipment, expected_version)
    if shipment.delivery_mode == SupplierShipment.DeliveryMode.FACTORY_LOADING:
        raise ValidationError('货柜上门装载不经过集货中心，无需标记集货到仓。')
    with domain_write():
        shipment.collection_arrived, shipment.collection_arrived_at, shipment.collection_arrived_by = True, occurred_at, actor
        shipment.version += 1
        shipment.save()
        _event(actor, shipment, "collection_arrival", idempotency_key, payload)
    return shipment


@transaction.atomic
def create_dispatch_batch(actor, payload, *, idempotency_key):
    from .numbering import number_for
    _internal(actor)
    _tenant_lock(actor)
    key, digest = _key(idempotency_key), request_hash(payload)
    ids = payload.get("shipment_ids") or []
    if not ids or len(set(ids)) != len(ids):
        raise ValidationError("Select distinct supplier shipments.")
    shipments = list(_internal_shipments(actor).filter(pk__in=ids).select_related("order"))
    if len(shipments) != len(ids):
        raise NotFound("One or more shipments are unavailable.")
    if any(s.status != SupplierShipment.Status.SUBMITTED for s in shipments):
        raise ValidationError("Only submitted supplier shipments can be dispatched.")
    previous = DispatchBatch.objects.filter(tenant_id=actor.tenant_id, creation_key=key).first()
    if previous:
        _batch(actor, previous.pk)
        return _matching_replay(previous, digest)
    country_codes = {s.order.country_code_snapshot for s in shipments}
    if len(country_codes) != 1:
        raise ValidationError("A dispatch batch cannot mix destination countries.")
    if DispatchMembership.objects.filter(shipment_id__in=ids, active_guard=True).exists():
        raise ValidationError("A shipment already belongs to an active dispatch batch.")
    carrier = _master(FreightCompany, actor, payload["freight_company_id"], is_active=True)
    from .freight_channels import batch_freight_values
    freight_values = batch_freight_values(actor, carrier, shipments[0].order.country_code_snapshot,
        payload.get('freight_channel_id'), payload.get('freight_quote_id'))
    from .warehouse_archives import warehouse_refs
    planned = None
    if payload.get('planned_warehouse_id'):
        planned = warehouse_refs(actor, MANAGE).filter(pk=payload['planned_warehouse_id'], status='active',
            country_code__iexact=shipments[0].order.country_code_snapshot).first()
        if not planned:
            raise ValidationError('计划目的仓必须为该国家已启用且有权选择的仓库。')
    container_count = payload.get('container_count', 1)
    if isinstance(container_count, bool) or not isinstance(container_count, int) or not 1 <= container_count <= 1000:
        raise ValidationError('货柜数量必须为 1 至 1000 的整数。')
    with domain_write():
        batch = DispatchBatch.objects.create(
            tenant=actor.tenant, created_by=actor, number=payload.get("number") or number_for(actor, "dispatch_batch", f"DB-{business_date():%Y%m%d}-{uuid4().hex[:12].upper()}", shipments[0].order.country_code_snapshot),
            country=shipments[0].order.country, country_code_snapshot=country_codes.pop(),
            **freight_values, freight_number=payload["freight_number"], planned_warehouse=planned,
            expected_warehouse_date=payload.get('expected_warehouse_date'),
            container_number=payload.get('container_number', ''), container_count=container_count,
            notes=payload.get("notes", ""), creation_key=key, request_hash=digest,
        )
        for shipment in shipments:
            DispatchMembership.objects.create(tenant=actor.tenant, created_by=actor, batch=batch, shipment=shipment)
        _event(actor, batch, "created", key, {"shipment_ids": ids})
    return batch


def _batch(actor, batch_id):
    batch = DispatchBatch.objects.filter(tenant_id=actor.tenant_id, pk=batch_id).first()
    if not batch:
        raise NotFound("Dispatch batch is unavailable.")
    allowed = _internal_shipments(actor)
    if batch.memberships.exclude(shipment__in=allowed).exists():
        raise NotFound("Dispatch batch is outside the authorized data scope.")
    return batch


@transaction.atomic
def mark_logistics_stage(actor, batch_id, *, stage, occurred_at, expected_version, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    batch = _batch(actor, batch_id)
    payload = {"stage": stage, "occurred_at": occurred_at.isoformat(), "expected_version": expected_version}
    if _prior_event(actor, batch, "logistics_marked", idempotency_key, payload):
        return batch
    _version(batch, expected_version)
    if batch.status != DispatchBatch.Status.ACTIVE:
        raise ValidationError("Cancelled batches cannot record logistics stages.")
    stages = list(DispatchBatch.Stage.values)
    if stage not in stages[1:] or stages.index(stage) != stages.index(batch.stage) + 1:
        raise ValidationError("Mark departed, arrived-port and arrived-warehouse in order.")
    if timezone.is_naive(occurred_at):
        raise ValidationError("Use a timezone-aware logistics timestamp.")
    previous_field = {"arrived_port": "departed_at", "arrived_warehouse": "arrived_port_at"}.get(stage)
    if previous_field and occurred_at < getattr(batch, previous_field):
        raise ValidationError("Logistics dates must follow their business order.")
    with domain_write():
        batch.stage = stage
        setattr(batch, {"departed": "departed_at", "arrived_port": "arrived_port_at", "arrived_warehouse": "arrived_warehouse_at"}[stage], occurred_at)
        batch.version += 1
        batch.save()
        _event(actor, batch, "logistics_marked", idempotency_key, payload)
    return batch


@transaction.atomic
def generate_inbound_draft(actor, batch_id, *, warehouse_id=None, expected_version, idempotency_key, reason=''):
    from .numbering import number_for
    _internal(actor)
    _tenant_lock(actor)
    batch = _batch(actor, batch_id)
    payload = {"warehouse_id": warehouse_id, "expected_version": expected_version}
    if reason:
        payload['reason'] = reason
    if _prior_event(actor, batch, "inbound_generated", idempotency_key, payload):
        return batch.inbound_order
    _version(batch, expected_version)
    if batch.status != DispatchBatch.Status.ACTIVE or batch.stage != DispatchBatch.Stage.ARRIVED_WAREHOUSE:
        raise ValidationError("Inbound draft requires a batch marked arrived-warehouse.")
    from .warehouse_archives import warehouse_refs
    selected_warehouse = warehouse_id or batch.planned_warehouse_id
    warehouse = warehouse_refs(actor, MANAGE).filter(pk=selected_warehouse, status='active',
        country_code__iexact=batch.country_code_snapshot).first()
    if not warehouse:
        raise ValidationError('请选择目的国家已启用且有权选择的仓库。')
    if batch.planned_warehouse_id and warehouse.pk != batch.planned_warehouse_id and not reason.strip():
        raise ValidationError('实际入库仓与计划目的仓不同，请填写改仓原因。')
    if InboundOrder.objects.filter(batch=batch).exists():
        raise ValidationError("An inbound order already exists for this batch.")
    with domain_write():
        inbound = InboundOrder.objects.create(tenant=actor.tenant, created_by=actor,
            number=number_for(actor, "inbound_order", f"IN-{batch.pk}", batch.country_code_snapshot), batch=batch, warehouse=warehouse)
        lines = ShipmentLine.objects.filter(is_active=True, shipment__dispatch_memberships__batch=batch, shipment__dispatch_memberships__active_guard=True)
        for line in lines:
            InboundLine.objects.create(tenant=actor.tenant, created_by=actor, inbound=inbound, shipment_line=line, expected_quantity=line.quantity)
        batch.version += 1
        batch.save()
        _event(actor, batch, "inbound_generated", idempotency_key, payload)
    return inbound
