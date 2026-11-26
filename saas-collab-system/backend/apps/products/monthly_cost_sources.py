"""Normalized month inputs from immutable physical receipts and warehouse outbounds."""
from collections import defaultdict
from datetime import date,datetime,time
from decimal import Decimal
from django.db.models import Q
from .monthly_cost_adjustments import next_month,business_month
from .monthly_cost_reconciliation import business_zone

ZERO=Decimal(0)


def _month_bounds(month):
    start=month.replace(day=1)
    return start,next_month(start)


def aggregate_month(tenant_id,month):
    from apps.products.models import ProductSKU
    from apps.supply_chain.cost_models import CostVersion
    from apps.supply_chain.inbound_costs import receipt_allocations
    from apps.supply_chain.models import InternalStockReceiptLine
    from apps.sales_management.warehouse_order_models import WarehouseOutboundLine
    from .monthly_cost_models import MonthlyCostMovement,MonthlyCostAdjustment,MonthlyProductCost
    start,end=_month_bounds(month)
    low=datetime.combine(start,time.min,tzinfo=business_zone());high=datetime.combine(end,time.min,tzinfo=business_zone())
    rows=defaultdict(lambda:dict(receipt_quantity=ZERO,receipt_amount=ZERO,outbound_quantity=ZERO,
        other_in_quantity=ZERO,other_in_amount=ZERO,other_out_quantity=ZERO,adjustment_amount=ZERO,
        historical_sold_adjustment=ZERO,is_complete=True,contains_estimates=False,missing_reasons=[],source_keys=[]))
    receipts=list(InternalStockReceiptLine.objects.filter(tenant_id=tenant_id,
        receipt__inbound__confirmed_at__gte=low,receipt__inbound__confirmed_at__lt=high).select_related("receipt__inbound"))
    receipt_map={r.pk:r for r in receipts}
    batch_ids={r.receipt.inbound.batch_id for r in receipts}
    latest_by_receipt={}
    # Most recent observation within the original month; late fees are separate
    # adjustment records and never replace this receipt's original-month basis.
    versions=CostVersion.objects.filter(tenant_id=tenant_id,batch_id__in=batch_ids,stage="received",created_at__lt=high).order_by("batch_id","sequence","pk")
    for version in versions.iterator(chunk_size=200):
        for allocation in receipt_allocations(version):
            rid=allocation.get("receipt_line_id")
            if rid in receipt_map:latest_by_receipt[rid]=(allocation,version)
    missing_receipts=set(receipt_map)-set(latest_by_receipt)
    if missing_receipts:
        closed=set(MonthlyProductCost.objects.filter(tenant_id=tenant_id,month=start,status="finalized").values_list("sku_id","warehouse_id"))
        first_versions=CostVersion.objects.filter(tenant_id=tenant_id,batch_id__in=batch_ids,stage="received",created_at__gte=high).order_by("created_at","pk")
        for version in first_versions.iterator(chunk_size=200):
            for allocation in receipt_allocations(version):
                rid=allocation.get("receipt_line_id")
                if rid in missing_receipts:
                    receipt=receipt_map[rid]
                    if (receipt.sku_id,receipt.receipt.warehouse_id) not in closed:
                        latest_by_receipt[rid]=(allocation,version)
                        missing_receipts.remove(rid)
            if not missing_receipts:break
    for receipt in receipts:
        row=rows[(receipt.sku_id,receipt.receipt.warehouse_id)]
        row["receipt_quantity"]+=Decimal(receipt.received_quantity)
        row["source_keys"].append(f"receipt:{receipt.pk}")
        pair=latest_by_receipt.get(receipt.pk)
        if not pair:
            row["is_complete"]=False;row["missing_reasons"].append("入库尚无所属月份成本版本")
            continue
        allocation,version=pair
        amount=allocation.get("received_total")
        if amount is None or Decimal(str(allocation.get("actual_quantity") or 0))!=receipt.received_quantity:
            row["is_complete"]=False;row["missing_reasons"].append("入库成本金额未知或数量不一致")
        else:row["receipt_amount"]+=Decimal(str(amount))
        payment=(version.summary or {}).get("payment_audit",{})
        row["contains_estimates"]|=not bool(payment.get("snapshot",{}).get("ready",version.state=="confirmed"))
        row["source_keys"].append(f"cost:{version.pk}")
    aliases=defaultdict(set)
    for sku_id,code,legacy in ProductSKU.objects.filter(tenant_id=tenant_id).values_list("pk","sku_code","legacy_sku_code"):
        for value in (code,legacy):
            if value:aliases[value.strip().casefold()].add(sku_id)
    unmapped=ambiguous=0;warehouse_gaps=set()
    outbound=WarehouseOutboundLine.objects.filter(tenant_id=tenant_id,shipped_at__gte=low,shipped_at__lt=high)
    for line in outbound.iterator(chunk_size=1000):
        matches=set()
        for code in (line.warehouse_sku,line.source_sku):
            if code:matches|=aliases.get(code.strip().casefold(),set())
        if len(matches)!=1:
            warehouse_gaps.add(line.warehouse_id)
            if matches:ambiguous+=1
            else:unmapped+=1
            continue
        row=rows[(next(iter(matches)),line.warehouse_id)]
        row["outbound_quantity"]+=Decimal(line.quantity)
        row["source_keys"].append(f"outbound:{line.pk}")
    for move in MonthlyCostMovement.objects.filter(tenant_id=tenant_id,month=start).iterator(chunk_size=500):
        row=rows[(move.sku_id,move.warehouse_id)]
        if move.kind in ("return","transfer_in","count_in"):
            row["other_in_quantity"]+=move.quantity
            if move.amount is None:
                row["is_complete"]=False;row["missing_reasons"].append("非销售入库金额未知")
            else:row["other_in_amount"]+=move.amount
        else:row["other_out_quantity"]+=move.quantity
        row["source_keys"].append(f"movement:{move.pk}")
    for adjustment in MonthlyCostAdjustment.objects.filter(tenant_id=tenant_id,effective_month=start).iterator(chunk_size=500):
        row=rows[(adjustment.sku_id,adjustment.warehouse_id)]
        row["source_keys"].append(f"late-adjustment:{adjustment.pk}:{adjustment.status}")
        if adjustment.status=="allocated":
            row["adjustment_amount"]+=adjustment.inventory_amount
            row["historical_sold_adjustment"]+=adjustment.sold_amount
        else:row["missing_reasons"].append("跨月成本差额待分配")
    # Keep inactive-stock and all-sold rows in the monthly roll-forward, not only
    # products that happened to have a new order or receipt this month.
    previous=(start.replace(day=1)-__import__('datetime').timedelta(days=1)).replace(day=1)
    for sku_id,warehouse_id in MonthlyProductCost.objects.filter(tenant_id=tenant_id,month__in=(start,previous)).values_list("sku_id","warehouse_id"):
        rows[(sku_id,warehouse_id)]
    from .monthly_cost_returns import add_return_inputs
    return_gaps=add_return_inputs(tenant_id,start,end,rows,aliases)
    warehouse_gaps|=set(return_gaps)
    result=[]
    for (sku_id,warehouse_id),row in rows.items():
        row["source_complete"]=warehouse_id not in warehouse_gaps
        row["missing_reasons"]=list(dict.fromkeys(row["missing_reasons"]))
        row["missing_reason"]="；".join(row["missing_reasons"])
        row["source_keys"]=sorted(row["source_keys"])
        result.append(dict(sku_id=sku_id,warehouse_id=warehouse_id,**row))
    return dict(month=start.isoformat(),items=result,source_complete=not warehouse_gaps,truncated=False,
        unmapped_outbounds=unmapped,ambiguous_outbounds=ambiguous,pending_reason="存在未映射或歧义仓库流水" if warehouse_gaps else "")
