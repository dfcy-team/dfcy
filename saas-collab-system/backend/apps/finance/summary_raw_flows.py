"""Unallocated source evidence; never writes business records."""
from decimal import Decimal


def source_flows(stores, transactions, fees, registrations, inputs, facts, start, end):
    rows = []
    def append(store, kind, amount, day, key, **extra):
        if not str(start)[:7] <= str(day)[:7] <= str(end)[:7]:return
        if len(str(day)) == 10 and not str(start) <= str(day) <= str(end):return
        rows.append({'source_id': key, 'kind': kind, 'amount': str(amount) if amount is not None else None,
            'date': str(day), 'period_date': str(day) if len(str(day)) == 10 else None,
            'period_date_basis': '原始记录业务日期' if len(str(day)) == 10 else '仅有来源月份，未推断具体日期',
            'store_id': store.pk if store else None, 'store_code': store.code if store else '',
            'country': store.country_code if store else '', 'platform': store.platform.platform_type if store else '',
            'currency': store.currency if store else 'CNY', 'scope': 'order' if extra.get('external_order_id') else 'store',
            'external_order_id': '', 'status': 'confirmed' if amount is not None else 'pending',
            'raw_source_flow': True, **extra})
    for r in transactions:
        name = r.raw_fee_name.strip().lower()
        if name in {'item price credit', 'order_selling_price', 'order_original_price'}:kind='sales'
        elif name=='escrow_amount':kind='settlement'
        elif r.fee_category=='refund' or name in {'reversal item price','shipping fee refund to customer','seller_return_refund'}:kind='refund'
        elif r.fee_category=='adjustment' or name in {'wrong shipping fee adjustment','lost claim','damaged claim',
                'commission fee - correction for undercharge','payment fee - correction for undercharge'}:
            kind='adjustment' if r.external_order_id else 'shop_adjustment'
        else:kind='order_fee'
        append(stores[r.store_id], kind, r.signed_amount, r.business_date, f'finance-transaction:{r.pk}',
            currency=r.currency, external_order_id=r.external_order_id, source='SaaS平台原始财务记录',
            status='pending' if r.match_status == 'conflict' else 'reference' if kind=='settlement' or name=='order_original_price' else 'confirmed', description=r.raw_fee_name,
            source_proof={'platform_finance_transaction_id': r.pk})
    for r in fees:
        append(stores.get(r.store_id), 'warehouse_order' if r.kind == 'order' else 'warehouse_other',
            -r.amount, r.occurred_on or r.bill_month, f'warehouse:{r.pk}', currency=r.currency,
            country=r.country, warehouse_id=r.warehouse_id, source_bill_month=r.bill_month,
            external_order_id=r.external_order_id, source='SaaS仓库处理费登记', description=r.fee_item,
            status='reference' if r.source.get('type')=='warehouse_settlement_adjustment' else 'confirmed',
            source_proof={'warehouse_fee_id': r.pk, 'version': r.version})
    for r in registrations:
        if r.kind not in {'gcash', 'promotion'}:continue
        p=r.payload; day=str(p.get('paid_at') if r.kind=='gcash' else p.get('rate_date'))[:10]
        value=p.get('amount') if r.kind=='gcash' else p.get('cost')
        if value is None or not p.get('currency'):continue
        append(stores[r.store_id], r.kind, -Decimal(str(value)), day, f'registration:{r.pk}',
            currency=p['currency'], external_order_id=r.order.external_order_id if r.order_id else '',
            source='SaaS费用登记', source_proof={'registration_id':r.pk,'version':r.version})
    for r in inputs:
        p=r.payload
        append(stores[r.store_id], 'adjustment' if p.get('order') else 'shop_adjustment',
            p.get('amount'), (p.get('occurred_at') or p.get('date') or r.period)[:10], f'database:adjustment:{r.pk}',
            external_order_id=p.get('order') or '', currency=p.get('currency') or stores[r.store_id].currency,
            source='SaaS原始调整报表', description=p.get('scenario') or p.get('fee_type') or '',
            source_proof={'input_id':r.pk,'source_hash':r.source_hash})
    for f in facts:
        if f['kind']=='advertising':
            rows.append({**f,'period_date':f['date'] if len(f['date'])==10 else None,
                'period_date_basis':'广告实际来源日期','raw_source_flow':True})
    return rows
