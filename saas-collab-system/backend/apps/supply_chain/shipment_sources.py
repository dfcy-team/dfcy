"""Purchase provenance for multi-order shipments; header order remains a legacy anchor."""
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from .models import PurchaseLine, ShipmentLine, SupplierShipment


def compatible_orders(primary, source):
    if (primary.tenant_id, primary.supplier_id, primary.country_id) != (source.tenant_id, source.supplier_id, source.country_id):
        raise ValidationError('同一发货单的采购来源必须属于同租户、同供应商和同目的国家。')
    if source.status != 'confirmed':
        raise ValidationError('来源采购单必须已确认。')


def resolve_source(actor, primary, sku, purchase_line_id=None):
    from .services import _order
    if purchase_line_id:
        source = PurchaseLine.objects.filter(tenant_id=actor.tenant_id, pk=purchase_line_id,
            sku=sku, is_active=True).select_related('order').first()
        if source is None:
            raise ValidationError('来源采购行不存在、已停用或商品不一致。')
        allowed = _order(actor, source.order_id)
        compatible_orders(primary, allowed)
        return source
    candidates = primary.lines.filter(is_active=True, sku=sku)
    if candidates.count() > 1:
        raise ValidationError('同一 SKU 有多条采购行，请选择具体来源行。')
    return candidates.first()


def source_order_ids(shipment):
    if hasattr(shipment, '_source_orders'):
        return {order.pk for order in shipment._source_orders}
    rows = list(shipment.lines.filter(is_active=True).values_list('purchase_line__order_id', flat=True))
    return {value or shipment.order_id for value in rows} or {shipment.order_id}


def accessible_shipments(orders, queryset=None):
    query = SupplierShipment.objects.all() if queryset is None else queryset
    denied = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True,
        purchase_line__isnull=False).exclude(purchase_line__order__in=orders)
    return query.filter(order__in=orders).alias(_denied_source=Exists(denied)).filter(_denied_source=False)


def for_source_order(query, order_id):
    linked = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True,
        purchase_line__order_id=order_id)
    additional = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True, purchase_line__isnull=True)
    active = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True)
    return query.alias(_source_order_match=Exists(linked), _additional_source=Exists(additional),
        _has_source=Exists(active)).filter(Q(_source_order_match=True) |
        (Q(order_id=order_id) & (Q(_additional_source=True) | Q(_has_source=False))))


def prepare_source_orders(shipments):
    if not shipments:
        return
    for tenant_id in {obj.tenant_id for obj in shipments}:
        owners = {obj.pk: obj for obj in shipments if obj.tenant_id == tenant_id}
        groups = {pk: {} for pk in owners}
        for line in ShipmentLine.objects.filter(tenant_id=tenant_id, shipment_id__in=owners,
                is_active=True).select_related('purchase_line__order'):
            order = line.purchase_line.order if line.purchase_line_id else owners[line.shipment_id].order
            groups[line.shipment_id][order.pk] = order
        for pk, obj in owners.items():
            obj._source_orders = sorted(groups[pk].values(), key=lambda order: order.pk) or [obj.order]
