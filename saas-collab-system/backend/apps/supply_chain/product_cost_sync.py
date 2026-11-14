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
    if version.state != "confirmed" or version.stage != "received":
        return
    groups = defaultdict(list)
    for entry in version.entries.filter(
        receipt_line__isnull=False, received_quantity__gt=0, received_total__isnull=False,
    ).select_related("shipment_line", "receipt_line__receipt"):
        groups[(entry.shipment_line.sku_id, entry.receipt_line.receipt.warehouse_id)].append(entry)

    start = version.created_at
    source = version.batch if version.batch_id else version.shipment
    reason = f"供应链入库成本 {source.number} / v{version.sequence} / 成本记录 {version.pk}"
    for (sku_id, warehouse_id), entries in sorted(groups.items()):
        sku = ProductSKU.objects.select_for_update().get(tenant=version.tenant, pk=sku_id)
        warehouse = entries[0].receipt_line.receipt.warehouse
        existing = ProductCostVersion.objects.filter(
            tenant=version.tenant, sku=sku, warehouse_id=warehouse_id,
            status=ProductCostVersion.Status.CONFIRMED,
        )
        if existing.filter(reason=reason).exists():
            continue
        future = existing.filter(effective_from__gt=start).order_by("effective_from").first()
        quantity = sum(entry.received_quantity for entry in entries)

        total, purchase, freight, duty = _rounded_unit_costs(
            sum(entry.received_goods_amount for entry in entries),
            sum(entry.received_collection_fee + entry.received_freight_fee for entry in entries),
            sum(entry.clearance_fee for entry in entries),
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
