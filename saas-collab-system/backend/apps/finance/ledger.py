"""Read-only financial presentation. Original facts are never rewritten or re-imported."""
from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_FLOOR, localcontext
from django.db.models import Q

from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.commerce.models import SalesOrder
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.ui_p6_scopes import filter_finance_queryset
from apps.sales_management.registration_services import scoped as registrations
from apps.sales_management.scopes import filter_sales_queryset
from .models import PlatformFinanceTransaction
from .warehouse_fee_services import scoped as warehouse_fees

KINDS = {'receipt': '订单回款', 'refund': '订单退款', 'advertising': '广告花费', 'product_cost': '商品成本',
         'gcash': 'GCash退款', 'promotion': '刷单费用', 'warehouse_order': '仓库处理费', 'warehouse_other': '仓库其他处理费'}
QUANT = Decimal('0.000001')
MAX_ROWS = 200000


def bounded(qs):
    if qs.count() > MAX_ROWS:
        raise ValidationError('当前期间数据过多，请缩小日期范围；没有返回截断合计。')
    return qs


def in_period(value, query):
    return value and (not query.get('period_start') or str(value) >= str(query['period_start'])) and (
        not query.get('period_end') or str(value) <= str(query['period_end']))


def period_queryset(qs, query, field):
    for suffix, key in [('gte', 'period_start'), ('lte', 'period_end')]:
        if query.get(key):
            qs = qs.filter(**{f'{field}__{suffix}': query[key]})
    return qs


def record(source_id, kind, amount, currency, occurred, *, store=None, country='', order='',
           status='confirmed', source='', description='', warehouse_id=None, parts=None):
    return {'source_id': source_id, 'kind': kind, 'amount': Decimal(amount), 'currency': currency,
            'date': str(occurred), 'scope': 'order' if order else 'store' if store else 'country',
            'country': store.country_code if store else country, 'store_id': store.pk if store else None,
            'store_code': store.code if store else '', 'platform': store.platform.platform_type if store else '',
            'external_order_id': order, 'status': status, 'source': source, 'description': description,
            'warehouse_id': warehouse_id, 'parts': parts or []}


def platform_records(user, query):
    qs = filter_finance_queryset(user, PlatformFinanceTransaction.objects.filter(
        tenant=user.tenant, store__tenant=user.tenant), 'finance.view')
    qs = period_queryset(qs, query, 'business_date').select_related('store__platform').order_by('pk')
    receipts, records, ignored = {}, [], 0
    for row in bounded(qs).iterator(chunk_size=2000):
        name = row.raw_fee_name.strip().lower()
        common = dict(store=row.store, order=row.external_order_id, source='平台结算')
        status = 'pending' if row.match_status == 'conflict' else 'confirmed'
        if row.platform == 'shopee':
            if name not in {'escrow_amount', 'seller_return_refund'}:
                # Shopee detail emits both settlement totals and their components.
                # Original price, commission, shipping etc. must not be added again.
                ignored += 1
                continue
            if name == 'seller_return_refund' and not row.signed_amount:
                continue
            records.append(record(f'platform:{row.pk}', 'receipt' if name == 'escrow_amount' else 'refund',
                row.signed_amount, row.currency, row.business_date,
                status=status if name == 'escrow_amount' else 'reference',
                description='Shopee净结算回款（不再次扣除平台费用）' if name == 'escrow_amount' else
                'Shopee退款指标参考项：净结算回款已独立展示，本指标不再次计入收支差额。',
                parts=[{'name': row.raw_fee_name, 'amount': row.signed_amount, 'id': row.pk}], **common))
        elif name in {'ads_expense', 'advertising_expense', 'advertising fee', '广告花费'}:
            records.append(record(f'platform:{row.pk}', 'advertising', row.signed_amount, row.currency,
                row.business_date, store=row.store, source='广告账单', status=status, description=row.raw_fee_name))
        elif row.platform in {'lazada', 'tiktok'} and row.external_order_id:
            refund = row.fee_category == 'refund' or name in {'reversal item price', 'shipping fee refund to customer'}
            if refund:
                records.append(record(f'platform:{row.pk}', 'refund', row.signed_amount, row.currency,
                    row.business_date, status=status, description=row.raw_fee_name, **common))
                continue
            key = (row.store_id, row.external_order_id, row.currency, str(row.business_date), status)
            if key not in receipts:
                receipts[key] = record(f'net:{row.pk}', 'receipt', 0, row.currency, row.business_date,
                    status=status, description='订单回款净额：订单结算流水扣除平台费用；退款单独展示。', **common)
            entry = receipts[key]
            entry['amount'] += row.signed_amount
            part = next((x for x in entry['parts'] if x['name'] == row.raw_fee_name), None)
            if part is None:
                part = {'name': row.raw_fee_name, 'amount': Decimal(0), 'count': 0}
                entry['parts'].append(part)
            part['amount'] += row.signed_amount
            part['count'] += 1
        else:
            ignored += 1
    return records + list(receipts.values()), ignored


def collect_records(user, query):
    warehouse_only = query.get('kind') in {'warehouse_order', 'warehouse_other'} or query.get('source') == '仓库账单'
    facts, ignored = ([], 0) if warehouse_only else platform_records(user, query)
    notices = ['收支差额不是净利润或现金余额；缺少数据不代表费用为零。',
               'Shopee按净结算回款展示；退款指标仅供参考，不再次扣减。Lazada按结算流水归集净回款、单列退款。',
               '广告报表消耗、充值和账户余额不是实际广告扣费，不混入财务流水。当前未接入销售订单履约成本快照。']
    unavailable = []
    for kind in ([] if warehouse_only else ['gcash', 'promotion']):
        try:
            qs = registrations(user, kind).filter(store__tenant=user.tenant).select_related('store__platform', 'order').exclude(
                status__in=['void', 'cancelled', 'withdrawn', 'rejected'])
        except PermissionDenied:
            unavailable.append(KINDS[kind])
            continue
        qs = filter_finance_queryset(user, qs, 'finance.view',
            platform_field='store__platform__platform_type', currency_field='payload__currency')
        for row in bounded(qs).iterator(chunk_size=1000):
            data = row.payload
            occurred = data.get('paid_at') if kind == 'gcash' else data.get('rate_date')
            if not in_period(occurred, query):
                continue
            amount = data.get('amount') if kind == 'gcash' else data.get('cost')
            if amount is None or not data.get('currency'):
                notices.append(f'登记 #{row.pk} 缺少金额或币种，未计入合计。')
                continue
            # Explicit allowlist: never return recipient, phone, account, screenshots or arbitrary payload.
            facts.append(record(f'{kind}:{row.pk}', kind, -Decimal(str(amount)), data['currency'], occurred,
                store=row.store, order=row.order.external_order_id if row.order_id else '',
                status='confirmed' if row.status == 'registered' else 'pending',
                source='GCash登记' if kind == 'gcash' else '订单推广登记',
                description=('GCash退款' if data.get('type') == 'refund' else 'GCash其他用途') if kind == 'gcash'
                    else '刷单总费用＝整单金额＋服务费×登记汇率（不重复累加服务费）'))
    try:
        qs = warehouse_fees(user).filter(Q(warehouse__tenant=user.tenant) | Q(warehouse__isnull=True)).exclude(status='void').select_related('store__platform', 'warehouse')
    except PermissionDenied:
        qs = None
        unavailable.append('仓库处理费')
    if qs is not None:
        qs = filter_finance_queryset(user, qs, 'finance.view', platform_field='store__platform__platform_type')
        for row in bounded(qs).iterator(chunk_size=1000):
            year, month = map(int, row.bill_month.split('-'))
            occurred = row.occurred_on or date(year, month, monthrange(year, month)[1])
            if not in_period(occurred, query):
                continue
            facts.append(record(f'warehouse:{row.pk}', 'warehouse_' + row.kind, -row.amount, row.currency,
                occurred, store=row.store, country=row.country, order=row.external_order_id,
                status='confirmed' if row.status == 'registered' else 'pending', source='仓库账单',
                warehouse_id=row.warehouse_id, description=f'{row.bill_number} · {row.fee_item} · {row.reference}' +
                    ('（未注明发生日，按账单月末归集）' if not row.occurred_on else '')))
    if unavailable:
        notices.append('当前无权查看以下登记来源，未纳入汇总：' + '、'.join(unavailable))
    if ignored:
        notices.append(f'{ignored} 条平台构成指标或未归类流水未独立累加，可在“平台原始流水”核对。')
    return facts, notices


def sales_weights(user, query):
    code = 'sales_management.orders.view'
    if not check_user_permission(user, code):
        return [], False
    scopes = get_permission_data_scopes(user, code, resource_code='sales_management.sales')
    complete = user.is_superuser or any(s['scope_type'] == 'all' for s in scopes)
    qs = filter_sales_queryset(user, code, SalesOrder.objects.filter(tenant=user.tenant))
    qs = filter_finance_queryset(user, qs, 'finance.view', platform_field='platform__platform_type')
    qs = period_queryset(qs, query, 'business_date').filter(order_total_amount__gt=0,
        normalized_status__in=['confirmed', 'fulfilled', 'completed']).select_related('store__platform')
    return [{'id': row.pk, 'country': row.store.country_code, 'store_id': row.store_id,
             'store_code': row.store.code, 'platform': row.store.platform.platform_type,
             'external_order_id': row.external_order_id, 'currency': row.currency,
             'weight': row.order_total_amount} for row in bounded(qs).iterator(chunk_size=1000)], complete


def split_amount(amount, weighted):
    """Largest remainder at original six-decimal precision; deterministic tie-break."""
    weighted = sorted((key, weight) for key, weight in weighted if weight > 0)
    if not weighted:
        return {}
    with localcontext() as context:
        context.prec = 50
        units = int(abs(amount) / QUANT)
        total = sum(weight for _, weight in weighted)
        exact = {key: Decimal(units) * weight / total for key, weight in weighted}
        rounded = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in exact.items()}
        remainder = units - sum(rounded.values())
        for key in sorted(exact, key=lambda k: (-(exact[k] - rounded[k]), k))[:remainder]:
            rounded[key] += 1
        return {key: value * QUANT * (-1 if amount < 0 else 1) for key, value in rounded.items()}


def allocate(facts, orders, view, *, complete=True):
    if view in {'detail', 'country'}:
        return facts, []
    entries, missing = [], []
    for source in facts:
        if source['scope'] == 'order' or view == 'store' and source['scope'] == 'store':
            entries.append(source)
            continue
        targets = [o for o in orders if o['country'] == source['country'] and o['currency'] == source['currency']
            and (not source['store_id'] or o['store_id'] == source['store_id'])]
        if not complete or not targets:
            missing.append({**source, 'reason': '销售订单授权范围不完整，未分摊' if not complete else '同国家、同期间、同币种无有效销售额，未分摊'})
            continue
        stores = defaultdict(list)
        for order in targets:
            stores[order['store_id']].append(order)
        weights = {key: sum(o['weight'] for o in values) for key, values in stores.items()}
        shares = split_amount(source['amount'], list(weights.items()))
        for store_id, store_amount in shares.items():
            store = stores[store_id][0]
            allocation = {'source_scope': source['scope'], 'source_amount': source['amount'],
                          'store_sales': weights[store_id], 'basis_currency': store['currency'],
                          'country_sales': sum(weights.values()) if source['scope'] == 'country' else None,
                          'basis': '同国家、所选期间有效订单整单金额；筛选店铺/订单不改变分母；非回款金额',
                          'precision': '0.000001，最大余数法补差'}
            common = {**source, 'store_id': store_id, 'store_code': store['store_code'],
                      'platform': store['platform'], 'allocation': allocation}
            if view == 'store':
                entries.append({**common, 'amount': store_amount})
            else:
                order_shares = split_amount(store_amount, [(o['id'], o['weight']) for o in stores[store_id]])
                for order in stores[store_id]:
                    entries.append({**common, 'external_order_id': order['external_order_id'],
                        'amount': order_shares[order['id']], 'allocation': {**allocation,
                            'order_sales': order['weight'], 'store_allocated_amount': store_amount}})
        if len(entries) > MAX_ROWS:
            raise ValidationError('分摊结果过多，请缩小日期范围；没有返回截断合计。')
    return entries, missing


def matches(entry, query):
    return all(not query.get(key) or str(entry.get(key, '')) == str(query[key])
        for key in ['country', 'platform', 'store_id', 'currency', 'kind', 'status', 'source', 'warehouse_id']) and (
        not query.get('external_order_id') or entry.get('external_order_id') in {
            value.strip() for value in query['external_order_id'].replace('，', ',').split(',')})


def summarize(entries, view):
    groups = {}
    for entry in entries:
        key = (entry['country'], entry['currency'], entry['store_id'] if view != 'country' else None,
               entry['external_order_id'] if view == 'order' else '')
        if key not in groups:
            groups[key] = {'country': key[0], 'currency': key[1], 'store_id': key[2],
                'store_code': entry['store_code'] if key[2] else '', 'external_order_id': key[3],
                'cells': {}, 'balance': Decimal(0), 'pending_count': 0, 'sources': set()}
        row = groups[key]
        cell = row['cells'].setdefault(entry['kind'], {'amount': None, 'reference_amount': None,
            'pending_count': 0, 'allocated': False, 'source_count': 0})
        row['sources'].add(entry['source_id'])
        cell['source_count'] += 1
        if entry['status'] == 'confirmed':
            cell['amount'] = (cell['amount'] or Decimal(0)) + entry['amount']
            cell['allocated'] |= bool(entry.get('allocation'))
            row['balance'] += entry['amount']
        elif entry['status'] == 'reference':
            cell['reference_amount'] = (cell['reference_amount'] or Decimal(0)) + entry['amount']
        else:
            cell['pending_count'] += 1
            row['pending_count'] += 1
    for row in groups.values():
        row['source_count'] = len(row.pop('sources'))
    return sorted(groups.values(), key=lambda r: (r['country'], r['store_code'], r['external_order_id'], r['currency']))


def report(user, query):
    facts, notices = collect_records(user, query)
    orders, complete = ([], True) if query['view'] in {'detail', 'country'} else sales_weights(user, query)
    entries, missing = allocate(facts, orders, query['view'], complete=complete)
    entries = [e for e in entries if matches(e, query)]
    # Pending public expenses remain discoverable even under a lower-level filter.
    missing_query = {k: v for k, v in query.items() if k not in {'platform', 'store_id', 'external_order_id'}}
    missing = [e for e in missing if matches(e, missing_query)]
    totals = {}
    for entry in entries:
        value = totals.setdefault(entry['currency'], {'currency': entry['currency'], 'income': Decimal(0),
            'expense': Decimal(0), 'balance': Decimal(0), 'pending_count': 0})
        if entry['status'] == 'confirmed':
            amount = entry['amount']
            value['income' if amount > 0 else 'expense'] += amount
            value['balance'] += amount
        elif entry['status'] == 'pending':
            value['pending_count'] += 1
    hidden_reference_refund_count = 0
    if query['view'] == 'detail' and not query.get('breakdown'):
        visible = [e for e in entries if not (e['kind'] == 'refund' and e['status'] == 'reference')]
        hidden_reference_refund_count = len(entries) - len(visible)
        entries = visible
    items = sorted(entries, key=lambda e: (e['date'], e['source_id']), reverse=True) if query['view'] == 'detail' or query.get('breakdown') else summarize(entries, query['view'])
    page, size = query['page'], query['page_size']
    if missing:
        notices.append(f'{len({e["source_id"] for e in missing})} 笔公共费用缺少有效分摊基数或完整授权，仍保留原归属，未计入当前下级汇总。')
    export_codes = ['finance.export']
    if any(e['kind'] == 'gcash' for e in entries):
        export_codes.append('finance.gcash.export')
    if any(e['kind'] == 'promotion' for e in entries):
        export_codes.append('sales_management.promotion.export')
    if any(e['kind'].startswith('warehouse_') for e in entries):
        export_codes.append('finance.warehouse_fees.export')
    can_export = all(check_user_permission(user, code) and (
        user.is_superuser or any(s['scope_type'] == 'all' for s in get_permission_data_scopes(user, code)))
        for code in export_codes)
    return {'items': items[(page - 1) * size:page * size], 'can_export': can_export,
        'pagination': {'page': page, 'page_size': size, 'total': len(items)},
        'totals': list(totals.values()), 'kinds': KINDS, 'notices': list(dict.fromkeys(notices)),
        'source_count': len({e['source_id'] for e in entries}), 'hidden_reference_refund_count': hidden_reference_refund_count,
        'unallocated_count': len({e['source_id'] for e in missing}),
        'unallocated': [{k: e[k] for k in ['source_id', 'country', 'currency', 'amount', 'description', 'reason']} for e in missing[:100]],
        'stores': sorted({(e['store_id'], e['store_code']) for e in facts if e['store_id']}),
        'coverage': {kind: sum(e['kind'] == kind for e in facts) for kind in KINDS}}
