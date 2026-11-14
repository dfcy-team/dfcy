"""Reverse actual received quantities at their identifiable outbound cost."""
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo


def return_costs(user, stores, outbound, aliases, start, end):
    from apps.sales_management.aftersales_models import ReturnAllocation
    allocations = list(ReturnAllocation.objects.filter(case__tenant=user.tenant, case__store_id__in=stores,
        line__receipt__tenant=user.tenant).select_related('case__order', 'line__receipt').order_by('line__receipt__received_at', 'pk'))
    def identity(code):
        code=code.strip().casefold(); matches=aliases.get(code,set())
        return ('sku',next(iter(matches))) if len(matches)==1 else ('code',code)
    totals=defaultdict(int)
    for a in allocations:
        totals[(a.case.order_id,a.line.receipt.warehouse_id,identity(a.line.sku))]+=a.quantity
    result=[]
    for a in allocations:
        receipt=a.line.receipt; order=a.case.order; store=stores[a.case.store_id]
        if not order or order.tenant_id!=user.tenant_id or order.store_id!=store.pk or not receipt.received_at:continue
        day=receipt.received_at.astimezone(ZoneInfo(store.timezone)).date().isoformat()
        if not str(start)<=day<=str(end):continue
        code=a.line.sku.strip().casefold(); matched=aliases.get(code,set())
        candidates=[c for c in outbound.get(order.pk,[]) if c['warehouse_id']==receipt.warehouse_id
            and (c['source_sku'].strip().casefold()==code or len(matched)==1 and c['sku_id'] in matched)
            and c['shipped_date']<=day]
        reasons=[]
        if not candidates or any(c['reasons'] for c in candidates):reasons.append('缺少可核对的原出库成本')
        prices={c['unit_cost'] for c in candidates}
        if len(prices)!=1:reasons.append('原出库成本不唯一，需核对具体出库批次')
        if totals[(order.pk,receipt.warehouse_id,identity(a.line.sku))]>sum(c['quantity'] for c in candidates):reasons.append('累计退货数量超过原出库数量')
        if a.quantity>a.line.received_quantity:reasons.append('关联数量超过到仓实收数量')
        amount=None if reasons else Decimal(next(iter(prices)))*a.quantity
        component={**(candidates[0] if candidates else {}),'quantity':a.quantity,'source_sku':a.line.sku,
            'unit_cost':None if reasons else next(iter(prices)),'net_cost':str(amount) if amount is not None else None,
            'gross_cost':'0','return_credit':str(amount) if amount is not None else None,'currency':'CNY','reasons':reasons}
        result.append({'source_id':f'warehouse-return-cost:{a.pk}','kind':'product_cost','cost_event':'return',
            'date':day,'statistics_date':day,'statistics_date_basis':'退货成功入库日期','period_date':day,
            'period_date_basis':'退货成功入库日期','currency':'CNY','amount':str(amount) if amount is not None else None,
            'country':store.country_code,'platform':store.platform.platform_type,'store_id':store.pk,'store_code':store.code,
            'external_order_id':order.external_order_id,'scope':'order','status':'pending' if reasons else 'confirmed',
            'source':'SaaS退货到仓成本冲回','raw_source_flow':True,
            'description':f'退货单 {receipt.return_no}；SKU {a.line.sku}；实收关联数量 {a.quantity}'+('；'+'；'.join(reasons) if reasons else ''),
            'return_event':{'id':a.pk,'verified':not reasons,'confirmed_at':receipt.received_at.isoformat()},
            'source_proof':{'return_receipt_id':receipt.pk,'return_allocation_id':a.pk,
                'outbound_flow_ids':[c['source_flow_id'] for c in candidates]},
            'cost_calculation':{'components':[component],'state':'pending' if reasons else 'calculated',
                'time_basis':'warehouse_received_date','gross_cost':'0','net_cost':str(amount) if amount is not None else None,
                'return_credit':str(amount) if amount is not None else None,'reasons':reasons}})
    return result
