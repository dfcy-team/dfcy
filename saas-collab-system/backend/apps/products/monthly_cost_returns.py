"""Add physically received, explicitly allocated returns to monthly cost inputs."""
from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP


ZERO = Decimal("0")


def add_return_inputs(tenant_id, start, end, rows, aliases):
    """Apply only warehouse receipts with unambiguous, quantity-valid allocations.

    Same-month returns reverse sales quantity. Older sales return at the original
    sale month's finalized unit cost and enter as a priced stock receipt.
    """
    from apps.sales_management.aftersales_models import WarehouseReturnReceipt
    from apps.sales_management.warehouse_order_models import WarehouseOutboundLine
    from .monthly_cost_models import MonthlyCostMovement, MonthlyProductCost
    from .monthly_cost_reconciliation import business_zone

    gaps = set()
    low = datetime.combine(start, time.min, tzinfo=business_zone())
    high = datetime.combine(end, time.min, tzinfo=business_zone())
    receipts = WarehouseReturnReceipt.objects.filter(
        tenant_id=tenant_id, received_at__isnull=False,
        received_at__gte=low, received_at__lt=high,
    ).select_related("warehouse").prefetch_related(
        "lines__allocations__case__order"
    )
    movement_keys = set(MonthlyCostMovement.objects.filter(
        tenant_id=tenant_id, month=start, kind="return"
    ).values_list("source_key", flat=True))
    cost_cache = {}
    for receipt in receipts:
        for line in receipt.lines.all():
            allocations = list(line.allocations.all())
            assigned = sum(a.quantity for a in allocations)
            if assigned > line.received_quantity:
                gaps.add(receipt.warehouse_id)
                continue
            # Unallocated physical units or conflicting SKU assignments cannot be
            # safely attributed to inventory cost.
            if assigned != line.received_quantity or not allocations:
                gaps.add(receipt.warehouse_id)
                continue
            sku_ids = set()
            bad = False
            for allocation in allocations:
                matches = set(aliases.get((allocation.case_sku or "").strip().casefold(), ()))
                if len(matches) != 1:
                    bad = True
                    break
                sku_ids |= matches
            if bad or len(sku_ids) != 1:
                gaps.add(receipt.warehouse_id)
                continue
            sku_id = next(iter(sku_ids))
            row = rows[(sku_id, receipt.warehouse_id)]
            for allocation in allocations:
                key = f"return:{line.pk}:{allocation.pk}"
                if key in movement_keys:
                    continue
                case = allocation.case
                order = case.order
                if order is None:
                    row["is_complete"] = False
                    row["missing_reasons"].append("退货无法关联原销售订单")
                    gaps.add(receipt.warehouse_id)
                    continue
                sku_aliases = [alias for alias, ids in aliases.items() if sku_id in ids]
                from django.db.models import Q
                from django.db.models.functions import Lower
                shipped = list(WarehouseOutboundLine.objects.filter(
                    tenant_id=tenant_id, lookup__order_id=order.pk,
                    warehouse_id=receipt.warehouse_id, shipped_at__lt=high,
                ).annotate(warehouse_sku_lower=Lower("warehouse_sku"), source_sku_lower=Lower("source_sku"))
                    .filter(Q(warehouse_sku_lower__in=sku_aliases) | Q(source_sku_lower__in=sku_aliases))
                    .values_list("shipped_at", flat=True))
                sale_months = {value.astimezone(business_zone()).date().replace(day=1) for value in shipped}
                if len(sale_months) != 1:
                    row["is_complete"] = False
                    row["missing_reasons"].append("无法唯一确定退货对应的原出库月份")
                    gaps.add(receipt.warehouse_id)
                    continue
                sale_month = next(iter(sale_months))
                if sale_month == start:
                    quantity = Decimal(allocation.quantity)
                    if quantity > row["outbound_quantity"]:
                        row["is_complete"] = False
                        row["missing_reasons"].append("同月退货数量超过原月出库数量")
                        gaps.add(receipt.warehouse_id)
                        continue
                    row["outbound_quantity"] -= quantity
                else:
                    if sale_month not in cost_cache:
                        cost_cache[sale_month] = {
                            (sku_id, warehouse_id): unit_cost
                            for sku_id, warehouse_id, unit_cost in MonthlyProductCost.objects.filter(
                            tenant_id=tenant_id, month=sale_month,
                            status=MonthlyProductCost.Status.FINALIZED,
                        ).values_list("sku_id", "warehouse_id", "unit_cost")
                        }
                    unit_cost = cost_cache[sale_month].get((sku_id, receipt.warehouse_id))
                    if unit_cost is None:
                        row["is_complete"] = False
                        row["missing_reasons"].append("跨月退货缺少原出库月已核定成本")
                        gaps.add(receipt.warehouse_id)
                        continue
                    quantity = Decimal(allocation.quantity)
                    row["other_in_quantity"] += quantity
                    row["other_in_amount"] += (quantity * unit_cost).quantize(
                        Decimal("0.0001"), rounding=ROUND_HALF_UP
                    )
                row["source_keys"].append(key)
    return gaps
