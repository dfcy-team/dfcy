"""Publish confirmed receipt costs into warehouse product cost versions."""
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from apps.products.cost_services import append_cost_version
from apps.products.models import ProductCostVersion, ProductSKU

PRECISION = Decimal("0.0001")

def _rounded_unit_costs(purchase, freight, duty, quantity):
    exact = [amount / quantity for amount in (purchase, freight, duty)]
    total = (sum((purchase, freight, duty)) / quantity).quantize(PRECISION, rounding=ROUND_HALF_UP)
    components = [value.quantize(PRECISION, rounding=ROUND_DOWN) for value in exact]
    remainder = int((total - sum(components)) / PRECISION)
    order = sorted(range(len(exact)), key=lambda index: exact[index] - components[index], reverse=True)
    for index in order[:remainder]:
        components[index] += PRECISION
    return total, *components


def publish_received_costs(version, actor):
    from django.conf import settings
    # Monthly mode uses one month average; a batch must not overwrite it.
    if getattr(settings, "MONTHLY_PRODUCT_COST_ENABLED", False) is True:
        return
    if version.state != "confirmed" or version.stage != "received":
        return
    from .inbound_costs import receipt_allocations
    from apps.masterdata.models import WarehouseMaster
    groups = defaultdict(list)
    for allocation in receipt_allocations(version):
        if allocation['actual_quantity'] and all(allocation.get(name) is not None for name in (
                'received_total', 'received_goods_amount', 'received_collection_fee', 'received_freight_fee', 'clearance_fee')):
            groups[(allocation['sku_id'], allocation['warehouse_id'])].append(allocation)

    start = version.created_at
    source = version.batch if version.batch_id else version.shipment
    reason = f"供应链入库成本 {source.number} / v{version.sequence} / 成本记录 {version.pk}"
    for (sku_id, warehouse_id), entries in sorted(groups.items()):
        sku = ProductSKU.objects.select_for_update().get(tenant=version.tenant, pk=sku_id)
        warehouse = WarehouseMaster.objects.get(tenant=version.tenant, pk=warehouse_id)
        existing = ProductCostVersion.objects.filter(
            tenant=version.tenant, sku=sku, warehouse_id=warehouse_id,
            status=ProductCostVersion.Status.CONFIRMED,
        )
        if existing.filter(reason=reason).exists():
            continue
        future = existing.filter(effective_from__gt=start).order_by("effective_from").first()
        quantity = sum(entry['actual_quantity'] for entry in entries)

        total, purchase, freight, duty = _rounded_unit_costs(
            sum(Decimal(entry['received_goods_amount']) for entry in entries),
            sum(Decimal(entry['received_collection_fee']) + Decimal(entry['received_freight_fee']) for entry in entries),
            sum(Decimal(entry['clearance_fee']) for entry in entries),
            quantity,
        )
        append_cost_version(
            tenant=version.tenant, sku=sku, warehouse=warehouse, actor=actor,
            status=ProductCostVersion.Status.CONFIRMED, source=ProductCostVersion.Source.SYSTEM,
            currency="CNY", purchase_cost=purchase, freight_cost=freight, duty_cost=duty,
            packaging_cost=Decimal(0), other_cost=Decimal(0),
            system_cost=total, confirmed_cost=total, effective_from=start,
            effective_to=future.effective_from if future else None, reason=reason,
        )
