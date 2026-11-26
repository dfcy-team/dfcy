"""Read-only aggregation of confirmed receipt costs and physical warehouse outbounds."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.conf import settings
ZERO = Decimal("0")
AMOUNT_FIELDS = ("received_total",)
MAX_BATCHES = 500


def _month_bounds(month):
    start = date(month.year, month.month, 1)
    end = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return start, end


def aggregate_month(tenant_id, month):
    """Return compact per SKU/warehouse inputs; never creates or finalizes records.

    Source gaps (notably opening balances and unmodeled adjustments) deliberately keep
    every affected row incomplete. A zero amount remains a known amount.
    """
    from apps.products.models import ProductSKU
    from apps.supply_chain.cost_models import CostVersion
    from apps.supply_chain.inbound_costs import receipt_allocations
    from apps.supply_chain.models import InternalStockReceiptLine
    from apps.sales_management.warehouse_order_models import WarehouseOutboundLine

    start, end = _month_bounds(month)
    receipt_dates = dict(InternalStockReceiptLine.objects.filter(
        receipt__tenant_id=tenant_id, receipt__created_at__date__gte=start,
        receipt__created_at__date__lt=end).values_list("pk", "receipt__created_at"))
    versions = (CostVersion.objects.filter(tenant_id=tenant_id, batch__isnull=False,
        stage="received").order_by("batch_id", "-sequence", "-pk"))
    latest = {}
    truncated = False
    for version in versions.iterator():
        if version.batch_id not in latest:
            if len(latest) >= MAX_BATCHES:
                truncated = True
                break
            latest[version.batch_id] = version

    rows = defaultdict(lambda: {"receipt_quantity": ZERO, "receipt_amount": ZERO,
        "outbound_quantity": ZERO, "is_complete": True, "contains_estimates": False,
        "missing_reasons": [], "source_keys": []})
    for batch_id, version in latest.items():
        allocations = receipt_allocations(version)
        for allocation in allocations:
            receipt_id = allocation.get("receipt_line_id")
            stamp = receipt_dates.get(receipt_id)
            if stamp is None or not (start <= stamp.date() < end):
                continue
            sku_id, warehouse_id = allocation.get("sku_id"), allocation.get("warehouse_id")
            if not sku_id or not warehouse_id:
                continue
            row = rows[(sku_id, warehouse_id)]
            if version.created_at.date() >= end:
                row["is_complete"] = False
                row["missing_reasons"].append("跨月批次修订须形成当期差额，不回写原月")
            if version.state != "confirmed":
                row["contains_estimates"] = True
            qty = allocation.get("actual_quantity")
            amount = allocation.get("received_total")
            if qty is None or amount is None:
                row["is_complete"] = False
                row["missing_reasons"].append("入库数量或成本金额未知")
            else:
                row["receipt_quantity"] += Decimal(str(qty))
                row["receipt_amount"] += Decimal(str(amount))
            row["source_keys"].append(f"batch:{batch_id}:v{version.sequence}:receipt:{receipt_id}")

    skus = list(ProductSKU.objects.filter(tenant_id=tenant_id))
    sku_index = defaultdict(set)
    for sku in skus:
        for value in (sku.sku_code, sku.legacy_sku_code):
            if value:
                sku_index[value.casefold()].add(sku.pk)
    sku_by_id = {sku.pk: sku for sku in skus}
    unmapped_outbounds = 0
    ambiguous_outbounds = 0
    outbound = WarehouseOutboundLine.objects.filter(tenant_id=tenant_id,
        shipped_at__date__gte=start, shipped_at__date__lt=end).select_related("warehouse")
    for line in outbound.iterator():
        ids = sku_index.get((line.warehouse_sku or line.source_sku or "").casefold(), set())
        if len(ids) != 1:
            if len(ids) > 1:
                ambiguous_outbounds += 1
            else:
                unmapped_outbounds += 1
            continue
        sku = sku_by_id[next(iter(ids))]
        if sku.tenant_id != tenant_id:
            unmapped_outbounds += 1
            continue
        row = rows[(sku.pk, line.warehouse_id)]
        row["outbound_quantity"] += Decimal(line.quantity)
        row["source_keys"].append(f"outbound:{line.pk}")

    result = []
    for (sku_id, warehouse_id), data in rows.items():
        data["missing_reasons"] = list(dict.fromkeys(data["missing_reasons"]))
        data["missing_reason"] = "；".join(data["missing_reasons"])
        data["source_keys"] = sorted(data["source_keys"])
        result.append({"sku_id": sku_id, "warehouse_id": warehouse_id, **data})
    return {"month": start.isoformat(), "items": result,
            "source_complete": not (truncated or unmapped_outbounds or ambiguous_outbounds),
            "truncated": truncated,
            "unmapped_outbounds": unmapped_outbounds,
            "ambiguous_outbounds": ambiguous_outbounds,
            "pending_reason": "批次扫描截断" if truncated else ("存在未映射或歧义出库 SKU" if unmapped_outbounds or ambiguous_outbounds else "")}
