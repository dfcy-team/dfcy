"""Generate financial inputs from tenant-owned SaaS records, without HTML inputs."""
import calendar
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from .summary_models import FinanceSummaryInput

ZERO = Decimal('0')
SIX = Decimal('.000001')
INCOME_FIELDS = set((
    'currency escrow_amount order_original_price original_price seller_discount seller_return_refund '
    'order_selling_price voucher_from_seller seller_coin_cash_back buyer_paid_shipping_fee '
    'shipping_fee_discount_from_3pl shopee_shipping_rebate actual_shipping_fee reverse_shipping_fee '
    'seller_shipping_discount final_return_to_seller_shipping_fee commission_fee service_fee '
    'seller_transaction_fee order_ams_commission_fee seller_order_processing_fee withholding_tax '
    'cross_border_tax escrow_tax fbs_fee ads_escrow_top_up_fee_or_technical_support_fee campaign_fee '
    'sspl_fee sales_tax_on_lvg shipping_fee_sst return_handling_fee overseas_return_service_fee '
    'shipping_seller_protection_fee_amount lff_seller_protection_fee_amount reverse_shipping_fee_sst '
    'return_to_seller_shipping_fee_sst final_product_vat_tax final_shipping_vat_tax '
    'total_adjustment_amount escrow_amount_after_adjustment').split())


def text(value):
    return None if value is None else format(Decimal(str(value)).quantize(SIX), 'f')


def posted_income(rows, envelope_id):
    """Recover exact provider fields when the raw body is stored outside the DB."""
    income, evidence = {}, {}
    for row in rows:
        if row.raw_fee_name not in INCOME_FIELDS:
            continue
        if (row.raw_envelope_id != envelope_id or row.match_status == 'conflict'
                or row.raw_fee_name in income):
            return None
        income[row.raw_fee_name] = text(row.raw_amount)
        evidence[row.raw_fee_name] = row.pk
    return {'income': income, 'envelope_id': envelope_id, 'response_index': None,
            'platform_finance_fields': evidence, 'basis': 'posted_provider_fields'} if income else None


def split_amount(amount, weights):
    """Largest remainder in micro-units; deterministic and exactly conserved."""
    weights = [(str(k), Decimal(str(v))) for k, v in weights if Decimal(str(v)) > 0]
    total = sum((v for _, v in weights), ZERO)
    if not total:
        return {}
    units = int((abs(Decimal(str(amount))) / SIX).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    rows = [(k, int(units * v / total), units * v / total % 1) for k, v in weights]
    remainder = units - sum(v for _, v, _ in rows)
    order = sorted(rows, key=lambda x: (-x[2], x[0]))
    added = {k for k, _, _ in order[:remainder]}
    sign = -1 if Decimal(str(amount)) < 0 else 1
    return {k: Decimal(v + (k in added)) * SIX * sign for k, v, _ in rows}


def shipping_dates(orders, shipments):
    """Prefer actual shipment, then confirmed pickup; never use creation/capture time."""
    by_id = {order.pk: order for order in orders}
    days = defaultdict(set)
    for shipment in shipments:
        order = by_id.get(shipment['sales_order_id'])
        stamp = shipment['shipped_at_utc']
        if order and stamp and (shipment['store_id'], shipment['platform_id']) == (order.store_id, order.platform_id):
            days[order.pk].add(stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    result = {}
    for order in orders:
        key = str(order.store_id)+'|'+order.external_order_id
        candidates = days[order.pk]
        basis = 'order_shipped_at_utc:Asia/Shanghai'
        if not candidates:
            details = getattr(order, 'source_details', None) or {}
            def pickup_day(value):
                if not isinstance(value, str):return None
                try:stamp = parse_datetime(value)
                except ValueError:return None
                return stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() if stamp and timezone.is_aware(stamp) else None
            direct = pickup_day(details.get('platform_pickup_at_utc'))
            if direct:
                candidates = {direct}
                basis = 'order_platform_pickup_at_utc:Asia/Shanghai'
            else:
                logistics = details.get('platform_logistics') or {}
                if logistics.get('order_sn') == order.external_order_id:
                    for package in logistics.get('packages') or []:
                        for event in package.get('events') or []:
                            # Confirmed pickup in saved Lazada OrderTrace; packed/handover is not pickup.
                            if str(event.get('status')) == '100100' and str(event.get('description') or '').startswith('Your package has been picked up by '):
                                value = pickup_day(event.get('occurred_at_utc'))
                                if value:candidates.add(value)
                basis = 'order_trace_pickup:Asia/Shanghai'
        result[key] = {'date': next(iter(candidates)) if len(candidates) == 1 else None,
            'order_id': order.pk, 'basis': basis,
            'reason': '' if len(candidates) == 1 else '订单存在多个发货／揽收日期，待核对' if candidates else '关联订单缺少发货／揽收日期'} if key not in result else {
                'date': None, 'order_id': None, 'basis': '', 'reason': '订单关联不唯一，待核对'}
    return result


def final_lines(lines, changes):
    """Changes affect shipped cost/quantity; platform sales facts stay intact."""
    result = [dict(x) for x in lines]
    for change in changes:
        action = change.get('action')
        if action in ('reduce', 'replace'):
            sku = change.get('old_sku_id') or change.get('sku_id')
            remaining = int(change.get('reduce_quantity') or 0)
            for line in result:
                if str(line.get('sku_id')) == str(sku):
                    reduced = min(remaining, line['quantity'])
                    line['quantity'] -= reduced
                    remaining -= reduced
            if remaining:
                raise ValidationError('减货数量超过原商品数量，未生成汇总。')
        if action in ('add', 'replace'):
            result.append({'sku_id': change.get('new_sku_id') or change.get('sku_id'),
                           'quantity': int(change.get('add_quantity') or 0), 'source_sku': ''})
    return [x for x in result if x['quantity'] > 0]


def cost_on(versions, day, zone):
    """Match the effective cost interval at the end of the local business date."""
    at = datetime.combine(date.fromisoformat(day), time.max, tzinfo=ZoneInfo(zone))
    matching = [v for v in versions if v.status == 'confirmed' and v.confirmed_cost is not None
                and v.effective_from <= at and (v.effective_to is None or at < v.effective_to)]
    return matching[0] if len(matching) == 1 else None


def convert_costs(facts, stores, rates):
    """Freeze one monthly conversion per order; distribute its exact total to SKUs."""
    for f in facts:
        if f['kind'] != 'product_cost':
            continue
        target = stores[f['store_id']].currency
        quote = rates['monthly'].get('|'.join([f['date'][:7], f['country'], f['currency'], target]))
        quote = dict(quote) if quote else None
        same = f['currency'] == target
        known = f['amount'] is not None and (same or quote is not None)
        original = Decimal(f['amount']) if f['amount'] is not None else None
        local = None if not known else original if same else (original * Decimal(str(quote['rate']))).quantize(SIX, rounding=ROUND_HALF_UP) if quote else None
        conversion = {'basis': 'cost_monthly_business', 'period': f['date'][:7],
                      'from': f['currency'], 'to': target, 'quote': quote,
                      'original_amount': text(original), 'local_amount': text(local)}
        f['cost_conversion'] = conversion
        components = f['cost_calculation']['components']
        shares = split_amount(local, [(i, c['net_cost']) for i, c in enumerate(components)]) if known else {}
        for i, c in enumerate(components):
            c['local_currency'] = target
            c['local_amount'] = text(shares.get(str(i), ZERO)) if known and not c['reasons'] else None
        if not known:

            if not same and quote is None:
                f['cost_calculation']['reasons'].append('缺成本归属月份业务汇率')
            f['cost_calculation']['state'] = 'pending'
            f['status'] = 'pending'


def item_price(line):
    source = line.source_details or {}
    verified = source.get('api_price_source') and not source.get('api_price_unverified_zero')
    value = source.get('reported_line_amount') if verified else None
    if value is None and verified and 'sale_unit_price' in source:
        value = Decimal(str(source['sale_unit_price'])) * line.quantity
    return text(value)


def bounded_raw_envelopes(queryset):
    # MySQL buffers a full result even with iterator(); LIMIT must reach SQL.
    upper = queryset.order_by('-pk').values_list('pk', flat=True).first()
    if upper is None:
        return
    last = 0
    while True:
        batch = list(queryset.filter(pk__gt=last, pk__lte=upper).order_by('pk')[:20])
        if not batch:
            return
        for envelope in batch:
            yield envelope
        last = batch[-1].pk
        batch.clear()


def product_quotes(envelopes):
    """Allowlist product fields; never forward arbitrary provider/customer payloads."""
    quotes, metadata = {}, {}
    for envelope in envelopes:
        candidates = []
        for row in envelope.payload.get('records') or []:
            if isinstance(row, dict) and ('skus' in row or 'item_name' in row):candidates.append(row)
        for trace in envelope.payload.get('responses') or []:
            body = (trace.get('payload') or {}).get('data') or (trace.get('payload') or {}).get('response') or {}
            if isinstance(body, dict):candidates.extend(body.get('products') or body.get('item_list') or [])
        for product in candidates:
            product_id = str(product.get('item_id') or product.get('product_id') or '')
            title = product.get('item_name') or (product.get('attributes') or {}).get('name') or product.get('title') or ''
            key = (envelope.store_id, product_id)
            if key not in metadata or envelope.pk > metadata[key]['raw_id']:
                metadata[key] = {'store_id': envelope.store_id, 'platform_product_id': product_id, 'title': title,
                                 'url': '', 'raw_id': envelope.pk}
            for sku in product.get('skus') or product.get('model') or []:
                price = sku.get('special_price') or sku.get('price')
                if price is None:
                    price = next((x.get('current_price') for x in sku.get('price_info') or [] if x.get('current_price') is not None), None)
                if price is None:continue
                for identity in [sku.get('SellerSku'), sku.get('SkuId'), sku.get('model_sku'), sku.get('model_id')]:
                    if identity is None:continue
                    k = (envelope.store_id, str(identity))
                    if k not in quotes or envelope.pk > quotes[k]['raw_id']:
                        quotes[k] = {'price': text(price), 'raw_id': envelope.pk, 'captured_at': envelope.created_at}
    return quotes, metadata


def collect(user, scope, *, allow_legacy_zero=True, native=False):
    from apps.masterdata.models import StoreMaster
    from apps.finance.models import PlatformFinanceTransaction
    from apps.finance.warehouse_fee_models import WarehouseFee, WarehouseBillUpload
    from apps.commerce.models import SalesOrder, SalesOrderItem, ShipmentRecord
    from apps.integrations.models import SyncRawEnvelope, MarketplaceStoreAuthorization
    from apps.products.models import ProductSKU, ProductCostVersion
    from apps.sales_management.registration_models import OrderRegistration
    from apps.listings.models import PlatformProductDetail

    start, end = date.fromisoformat(scope['from']), date.fromisoformat(scope['to'])
    stores = {s.pk: s for s in StoreMaster.objects.filter(tenant=user.tenant, pk__in=scope['stores']).select_related('platform')}
    if not stores or len(stores) != len(set(scope['stores'])) or start > end:
        raise ValidationError('汇总范围无效或店铺不属于当前租户。')
    stamp = timezone.now().isoformat()
    raw, facts = [], []
    seen = defaultdict(list)
    def add(store, kind, amount, day, order='', source_id='', **extra):
        f = {'source_id': source_id, 'kind': kind, 'amount': text(amount), 'date': str(day),
             'currency': store.currency, 'country': store.country_code, 'platform': store.platform.platform_type,
             'store_id': store.pk, 'store_code': store.code, 'external_order_id': order,
             'scope': 'order' if order else 'store', 'status': 'confirmed' if amount is not None else 'pending',
             'source': 'SaaS平台结算', **extra}
        facts.append(f)
        return f

    finance = PlatformFinanceTransaction.objects.filter(tenant=user.tenant, store_id__in=stores,
        business_date__gte=start, business_date__lte=end).order_by('pk')
    financial_count = 0
    if native:
        from django.db import connections
        from django.db.models import Func
        from itertools import groupby
        connection = connections[finance.db]
        def read_sql(queryset):
            sql, params = queryset.query.get_compiler(using=queryset.db).as_sql()
            if connection.vendor == 'mysql':
                table = connection.ops.quote_name(queryset.model._meta.db_table)
                index = 'idx_fin_tx_store_date'
                sql = sql.replace('FROM '+table, 'FROM '+table+' FORCE INDEX ('+connection.ops.quote_name(index)+')', 1)
            return sql, params
        def upper_value(queryset, field):
            sql, params = read_sql(queryset.order_by().values_list(field, flat=True))
            column = connection.ops.quote_name(field)
            with connection.cursor() as cursor:
                cursor.execute('SELECT MAX('+column+') FROM ('+sql+') AS finance_upper', params)
                return cursor.fetchone()[0]
        envelope_ids = set()
        for store_id in sorted(stores):
            ids = finance.filter(store_id=store_id, platform='shopee', raw_envelope_id__isnull=False).order_by().values_list('raw_envelope_id', flat=True).distinct()
            if connection.vendor == 'mysql':
                upper = upper_value(finance.filter(store_id=store_id, platform='shopee'), 'raw_envelope_id')
                if upper is not None:
                    from MySQLdb.cursors import SSCursor
                    query = ids.filter(raw_envelope_id__lte=upper).order_by('raw_envelope_id')
                    last = None
                    with connection.wrap_database_errors:
                        with connection.connection.cursor(SSCursor) as cursor:
                            cursor.execute(*read_sql(query))
                            while batch := cursor.fetchmany(500):
                                for (envelope_id,) in batch:
                                    if last is not None and envelope_id <= last:
                                        raise ValidationError('结算来源版本读取异常，未生成部分账单。')
                                    envelope_ids.add(envelope_id)
                                    last = envelope_id
                    if last != upper:
                        raise ValidationError('结算来源版本读取不完整，请重试；未生成部分账单。')
            else:
                envelope_ids.update(ids)
        group_order = ['store_id', 'external_order_id', 'business_date', 'currency', 'pk']
        if connection.vendor == 'mysql':
            binary = lambda field: Func(field, function='BINARY', template='%(function)s %(expressions)s')
            group_order = ['store_id', binary('external_order_id'), 'business_date', binary('currency'), 'pk']
        ordered = finance.only('id', 'store_id', 'business_date', 'platform', 'external_order_id',
            'raw_fee_name', 'raw_amount', 'signed_amount', 'currency', 'match_status', 'raw_envelope_id', 'fee_category'
            ).order_by(*group_order)
        finance_fields = ('id', 'store_id', 'business_date', 'platform', 'external_order_id', 'raw_fee_name',
                  'raw_amount', 'signed_amount', 'currency', 'match_status', 'raw_envelope_id', 'fee_category')
        from collections import namedtuple
        FinanceRow = namedtuple('FinanceRow', ('pk', *finance_fields[1:]))
        def read_finance():
            for store_id in sorted(stores):
                query = ordered.filter(store_id=store_id).values_list(*finance_fields)
                if connection.vendor != 'mysql':
                    for values in query.iterator(chunk_size=500):
                        yield FinanceRow(*values)
                    continue
                upper = upper_value(query, 'id')
                expected = 0
                if upper is not None:
                    sql, params = read_sql(query.filter(pk__lte=upper).order_by().values_list('pk'))
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT COUNT(*) FROM (' + sql + ') AS finance_count', params)
                        expected = cursor.fetchone()[0]
                read_count = 0
                if upper is not None:
                    from MySQLdb.cursors import SSCursor
                    sql, params = read_sql(query.filter(pk__lte=upper))
                    last_key = None
                    with connection.wrap_database_errors:
                        with connection.connection.cursor(SSCursor) as cursor:
                            cursor.execute(sql, params)
                            while batch := cursor.fetchmany(500):
                                for values in batch:
                                    row = FinanceRow(*values)
                                    next_key = (row.external_order_id, row.business_date, row.currency, row.pk)
                                    if last_key is not None and next_key <= last_key:
                                        raise ValidationError('财务流水排序异常，已停止读取。')
                                    last_key = next_key
                                    read_count += 1
                                    if read_count > expected:
                                        raise ValidationError('结算来源读取异常，未生成部分账单。')
                                    yield row
                if read_count != expected:
                    raise ValidationError('结算来源读取不完整，请重试；未生成部分账单。')
        iterator = read_finance()
        grouped = ((key, list(rows)) for key, rows in groupby(iterator,
            lambda row: (row.store_id, row.external_order_id, str(row.business_date), row.currency)))
        financial_rows = []
    else:
        financial_rows = list(finance)
        financial_count = len(financial_rows)
        groups = defaultdict(list)
        for r in financial_rows:
            store = stores[r.store_id]
            raw.append({'id': r.pk, 'date': str(r.business_date), 'platform': r.platform, 'store_id': r.store_id,
                        'store': store.code, 'country': store.country_code, 'order': r.external_order_id,
                        'name': r.raw_fee_name, 'raw': text(r.raw_amount), 'amount': text(r.signed_amount),
                        'currency': r.currency, 'match': r.match_status})
            groups[(r.store_id, r.external_order_id, str(r.business_date), r.currency)].append(r)
        grouped = groups.items()
        envelope_ids = {r.raw_envelope_id for r in financial_rows if r.platform == 'shopee'}

    # Read exact provider escrow versions referenced by posted financial facts.
    envelopes = SyncRawEnvelope.objects.filter(tenant=user.tenant, pk__in=envelope_ids).order_by()
    escrow = {}
    for envelope in bounded_raw_envelopes(envelopes) if native else envelopes.iterator(chunk_size=20):
        for index, trace in enumerate(envelope.payload.get('responses') or []):
            body = (trace.get('payload') or {}).get('response') or {}
            if not body.get('order_sn') or not body.get('order_income'):
                continue
            income = body['order_income']
            key = (envelope.store_id, str(body['order_sn']), envelope.pk)
            cleaned = {k: str(v) if isinstance(v, (int, float, str)) else v for k, v in income.items()
                       if k in INCOME_FIELDS and not isinstance(v, (list, dict))}
            if key in escrow and escrow[key]['income'] != cleaned:
                raise ValidationError('同一来源订单结算响应冲突，未汇总。')
            escrow[key] = {'income': cleaned, 'envelope_id': envelope.pk, 'response_index': index}
    shopee_income = []
    component_pool, text_pool = {}, {}
    settled = {}
    raw_stores = set()
    try:
        for (store_id, order, day, currency), rows in grouped:
            store = stores[store_id]
            if native:
                financial_count += len(rows)
                if store_id not in raw_stores:
                    raw.append({'platform': rows[0].platform, 'store_id': store_id, 'store': store.code})
                    raw_stores.add(store_id)
            if store.platform.platform_type == 'lazada':
                if order and any(r.match_status != 'conflict' for r in rows):
                    settled[(store_id, order)] = min(settled.get((store_id, order), day), day)
                by_kind = defaultdict(list)
                for row in rows:
                    name = row.raw_fee_name.strip().lower()
                    kind = 'sales' if name == 'item price credit' else 'refund' if name in (
                        'reversal item price', 'shipping fee refund to customer') else 'adjustment' if name in (
                        'wrong shipping fee adjustment', 'lost claim', 'damaged claim',
                        'commission fee - correction for undercharge', 'payment fee - correction for undercharge') else 'order_fee'
                    by_kind[kind].append(row)
                for kind, members in by_kind.items():
                    add(store, kind, sum((r.signed_amount for r in members), ZERO), day, order,
                        'preview:'+'|'.join(['lazada', str(store_id), order, day, currency])+':'+kind,
                        currency=currency, status='pending' if any(r.match_status == 'conflict' for r in members) else 'confirmed',
                        description='SaaS财务流水按原始费用名称分类，收入、支出及返还保留符号。')
                    facts[-1]['rows'] = [{'id': r.pk, 'name': r.raw_fee_name, 'raw': text(r.raw_amount), 'amount': text(r.signed_amount), 'currency': r.currency} for r in members]
                continue
            net_rows = [r for r in rows if r.raw_fee_name == 'escrow_amount']
            if len(net_rows) != 1:
                continue
            net_row = net_rows[0]
            if order and net_row.match_status != 'conflict':
                settled[(store_id, order)] = min(settled.get((store_id, order), day), day)
            source = escrow.get((store_id, order, net_row.raw_envelope_id)) or posted_income(rows, net_row.raw_envelope_id)
            income = source['income'] if source else {}
            if native and source:
                income = {key: text_pool.setdefault(value, value) for key, value in income.items()}
                source = {**source, 'income': income}
            components = []
            if store.code.startswith('SPKJ'):
                fields = [('voucher_from_seller', -1), ('seller_coin_cash_back', -1),
                    ('buyer_paid_shipping_fee', 1), ('shipping_fee_discount_from_3pl', 1), ('shopee_shipping_rebate', 1),
                    ('actual_shipping_fee', -1), ('reverse_shipping_fee', -1), ('seller_shipping_discount', 1), ('final_return_to_seller_shipping_fee', -1)]
                fields += [(k, -1) for k in ('commission_fee', 'service_fee', 'seller_transaction_fee',
                    'order_ams_commission_fee', 'seller_order_processing_fee', 'withholding_tax', 'cross_border_tax',
                    'escrow_tax', 'fbs_fee', 'ads_escrow_top_up_fee_or_technical_support_fee', 'campaign_fee', 'sspl_fee',
                    'sales_tax_on_lvg', 'shipping_fee_sst', 'return_handling_fee', 'overseas_return_service_fee',
                    'shipping_seller_protection_fee_amount', 'lff_seller_protection_fee_amount', 'reverse_shipping_fee_sst',
                    'return_to_seller_shipping_fee_sst', 'final_product_vat_tax', 'final_shipping_vat_tax')]
                merchandise = None if any(income.get(k) is None for k in ['original_price', 'seller_discount']) else Decimal(income['original_price'])-Decimal(income['seller_discount'])
            else:
                fields = [(k, -1) for k in ('voucher_from_seller', 'commission_fee', 'seller_transaction_fee',
                    'order_ams_commission_fee', 'seller_order_processing_fee', 'ads_escrow_top_up_fee_or_technical_support_fee',
                    'actual_shipping_fee', 'reverse_shipping_fee')]+[('buyer_paid_shipping_fee', 1), ('shopee_shipping_rebate', 1)]
                merchandise = Decimal(income['order_selling_price']) if income.get('order_selling_price') is not None else None
            refund = Decimal(income['seller_return_refund']) if income.get('seller_return_refund') is not None else None
            for name, sign in fields:
                value = text(Decimal(income[name])*sign) if income.get(name) is not None else None
                component = {'field': name, 'label': name, 'amount': value}
                if native and value in (None, '0.000000', '-0.000000'):
                    component = component_pool.setdefault((name, value), component)
                components.append(component)
            fees = None if any(c['amount'] is None for c in components) else sum((Decimal(c['amount']) for c in components), ZERO)
            sales = None if merchandise is None or refund is None else merchandise-refund
            reconciled = sales is not None and fees is not None and refund is not None and sales+fees+refund == net_row.raw_amount
            prefix = 'html2:sp6th:settlement:'+order if store.code == 'SP6TH' else 'preview:'+'|'.join(['shopee', str(store_id), order, day, currency])
            for kind, amount in [('sales', sales if reconciled else None), ('refund', refund), ('order_fee', fees if reconciled else None)]:
                add(store, kind, amount, day, order, prefix+':'+kind, source_proof=source and {k: source[k] for k in ['envelope_id', 'response_index', 'platform_finance_fields', 'basis'] if k in source},
                    sp6th_components=components if kind == 'order_fee' else None, description='SaaS保存的官方订单结算响应；构成必须与净结算额对平。')
            if source:shopee_income.append({'store_id': store_id, 'order': order, 'date': day, 'currency': currency, **source})

    finally:
        if native:
            iterator.close()

    financial_fact_count = len(facts) if native else 0
    if native:
        escrow.clear()
        envelope_ids.clear()
        del envelopes
        component_pool.clear()
        text_pool.clear()

    # Cost is charged once, at the first positive settlement; refunds do not imply physical returns.
    first = {}
    for f in facts:
        if f['kind'] == 'sales' and f['amount'] is not None and Decimal(f['amount']) > 0 and f['external_order_id']:
            k = (f['store_id'], f['external_order_id'])
            first[k] = min(first.get(k, f['date']), f['date'])
    prior = PlatformFinanceTransaction.objects.filter(tenant=user.tenant, store_id__in=stores,
        business_date__lt=start, raw_amount__gt=0).filter(Q(raw_fee_name__iexact='Item Price Credit') | Q(raw_fee_name='order_selling_price') | Q(raw_fee_name='escrow_amount'))
    if native:
        # Historical settlement matters only for orders receiving a cost in this scope.
        prior = prior.filter(external_order_id__in={key[1] for key in first}).order_by()
        prior_keys = set(prior.values_list('store_id', 'external_order_id').distinct())
    else:
        prior_keys = set(prior.values_list('store_id', 'external_order_id'))
    registrations = None
    shipment_lookups = None
    related_ids = set()
    if native:
        from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
        from apps.sales_management.aftersales_models import ReturnAllocation
        registrations = list(OrderRegistration.objects.filter(tenant=user.tenant, store_id__in=stores,
            deleted_at__isnull=True, status__in=['registered', 'historical_recorded', 'completed', 'applied']
            ).select_related('order').only('id', 'store_id', 'kind', 'payload', 'version', 'order_id',
                'order__id', 'order__external_order_id').order_by('version', 'pk'))
        for registration in registrations:
            payload = registration.payload
            day = str(payload.get('paid_at') if registration.kind == 'gcash' else payload.get('rate_date'))[:10]
            if registration.kind in ('gcash', 'promotion') and str(start) <= day <= str(end) and registration.order_id:
                related_ids.add(registration.order_id)
        before = date.fromordinal(max(date.min.toordinal(), start.toordinal()-2))
        after = date.fromordinal(min(date.max.toordinal(), end.toordinal()+2))
        related_ids.update(ReturnAllocation.objects.filter(case__tenant=user.tenant, case__store_id__in=stores,
            line__receipt__tenant=user.tenant, line__receipt__received_at__date__range=(before, after)
            ).order_by().values_list('case__order_id', flat=True).distinct())
        financial_orders = {f['external_order_id'] for f in facts if f.get('external_order_id')}
        selected = Q(order__external_order_id__in=financial_orders) | Q(order_id__in=related_ids)
        shipped = Q(status='matched', warehouse_id__isnull=False)
        first_month, last_month = start.year*12+start.month-1, end.year*12+end.month-1
        if last_month-first_month <= 24:
            dates = Q(pk__in=[])
            for month in range(max(12, first_month-1), min(9999*12+11, last_month+1)+1):
                dates |= Q(snapshot__packages__icontains=f'{month//12:04d}-{month%12+1:02d}')
            shipped &= dates
        lookup_query = OrderWarehouseLookup.objects.filter(order__tenant=user.tenant, order__store_id__in=stores
            ).filter(selected | shipped).order_by().only('id', 'order_id', 'status', 'warehouse_id', 'snapshot')
        shipment_lookups = {row.order_id: row for row in lookup_query.iterator(chunk_size=500)}
        related_ids.update(shipment_lookups)
    order_query = SalesOrder.objects.filter(tenant=user.tenant, store_id__in=stores)
    if native:
        from django.db.models import F
        order_query = order_query.filter(Q(pk__in=related_ids) | Q(external_order_id__in=financial_orders)).order_by().only('id', 'store_id', 'platform_id', 'external_order_id',
            'raw_status', 'normalized_status', 'delivered_at_utc').annotate(
                _read_logistics=F('source_details__platform_logistics'),
                _read_pickup=F('source_details__platform_pickup_at_utc'))
    orders = list(order_query)
    if native:
        for order in orders:
            order.source_details = {'platform_logistics': order._read_logistics,
                                    'platform_pickup_at_utc': order._read_pickup}
    orders_by_key = {(r.store_id, r.external_order_id): r for r in orders}
    order_dates = shipping_dates(orders, ShipmentRecord.objects.filter(tenant=user.tenant,
        store_id__in=stores, sales_order__isnull=False).values(
            'sales_order_id', 'store_id', 'platform_id', 'shipped_at_utc'))
    from .summary_cost_classification import collect_classifications, classify
    classifications = collect_classifications(user, stores, orders, facts, native=native)
    if native:
        # Shipping-date and classification evidence has consumed these projections.
        for order in orders:
            order.source_details = None
            del order._read_logistics, order._read_pickup
        del order_query, lookup_query, selected, financial_orders, related_ids
    sku_sales = {'source': 'SaaS SalesOrderItem', 'orders': {}, 'exchanges': {}}
    products = {}; catalogue = []
    provider_shops = defaultdict(set)
    for authorization in MarketplaceStoreAuthorization.objects.filter(
            tenant=user.tenant, store_id__in=stores, platform='shopee', status='active').values('store_id', 'platform_store_id'):
        identity = str(authorization['platform_store_id'] or '')
        if identity.isdigit():provider_shops[authorization['store_id']].add(identity)
    product_query = PlatformProductDetail.objects.filter(tenant=user.tenant, store_id__in=stores).order_by('pk')
    if native:
        product_query = product_query.only('store_id', 'platform_product_id', 'platform_variant_id', 'platform_sku', 'internal_sku_id', 'title').iterator(chunk_size=500)
    for r in product_query:
        catalogue.append({k: getattr(r, k) for k in ['store_id', 'platform_product_id', 'platform_variant_id', 'platform_sku', 'internal_sku_id', 'title']})
        products[(r.store_id, r.platform_product_id)] = {'store_id': r.store_id, 'platform_product_id': r.platform_product_id, 'title': r.title, 'url': ''}
    product_envelopes = SyncRawEnvelope.objects.filter(
        tenant=user.tenant, store_id__in=stores, endpoint__icontains='product').order_by()
    quotes, saved_products = product_quotes(bounded_raw_envelopes(product_envelopes) if native else product_envelopes.iterator(chunk_size=10))
    for key, product in saved_products.items():
        if product['title']:products[key] = product
    if native:
        # Resolve the earliest historical item per product in SQL. MySQL's
        # default collation may collapse distinct provider identifiers.
        from itertools import islice
        from django.db.models import BinaryField, F, Func, Min

        product_key = F('platform_product_id')
        if connection.vendor == 'mysql':
            product_key = Func(product_key, template='CAST(%(expressions)s AS BINARY)', output_field=BinaryField())
        for sid in sorted(stores):
            items = SalesOrderItem.objects.using(finance.db).filter(sales_order__tenant=user.tenant, sales_order__store_id=sid)
            first_ids = iter(items.order_by().values(key=product_key).annotate(first_id=Min('pk'))
                             .values_list('first_id', flat=True).iterator(chunk_size=500))
            while batch := list(islice(first_ids, 500)):
                titles = items.filter(pk__in=batch).values_list('platform_product_id', 'item_name_snapshot')
                for pid, title in titles:
                    products.setdefault((sid, pid), {
                        'store_id': sid, 'platform_product_id': pid, 'title': title, 'url': '',
                    })
    item_query = SalesOrderItem.objects.filter(sales_order__tenant=user.tenant, sales_order__store_id__in=stores).select_related('sales_order').order_by('pk')
    if native:
        item_query = item_query.only('id', 'sales_order_id', 'internal_sku_id', 'platform_product_id',
            'platform_variant_id', 'seller_sku', 'quantity', 'source_details', 'original_unit_price',
            'sale_unit_price', 'line_total_amount', 'currency', 'item_name_snapshot',
            'sales_order__id', 'sales_order__store_id', 'sales_order__external_order_id')
        from itertools import chain
        order_ids = [order.pk for order in orders]
        item_rows = item_query
        def read_item_pages(query):
            # Exclude rows inserted after this bounded group starts reading.
            upper = query.order_by('-pk').values_list('pk', flat=True).first()
            if upper is None:
                return
            last = 0
            while batch := list(query.filter(pk__gt=last, pk__lte=upper).order_by('pk')[:200]):
                for item in batch:
                    if item.pk <= last:
                        raise ValidationError('商品明细分页游标未推进，已停止读取。')
                    last = item.pk
                    yield item

        item_query = chain.from_iterable(
            read_item_pages(item_rows.filter(sales_order_id__in=order_ids[offset:offset+500]))
            for offset in range(0, len(order_ids), 500)
        )
    for item in item_query:
        order = item.sales_order;key = str(order.store_id)+'|'+order.external_order_id
        line = {'item_id': item.pk, 'internal_sku_id': item.internal_sku_id, 'platform_product_id': item.platform_product_id,
                'platform_variant_id': item.platform_variant_id, 'seller_sku': item.seller_sku, 'quantity': item.quantity,
                'historical_line_amount': item_price(item), 'historical_price_source': (item.source_details or {}).get('api_price_source', ''),
                'current_price_fresh': False, 'original_unit_price': text(item.original_unit_price), 'sale_unit_price': text(item.sale_unit_price),
                'line_total_amount': text(item.line_total_amount), 'currency': item.currency}
        quote = quotes.get((order.store_id, item.platform_variant_id)) or quotes.get((order.store_id, item.seller_sku))
        if quote:
            line.update(current_unit_price=quote['price'], current_price_source='SaaS平台商品快照 #'+str(quote['raw_id']),
                        current_captured_at=quote['captured_at'].isoformat(),
                        current_price_fresh=(timezone.now()-quote['captured_at']).total_seconds() <= 86400)
        sku_sales['orders'].setdefault(key, []).append(line)
        products.setdefault((order.store_id, item.platform_product_id), {'store_id': order.store_id, 'platform_product_id': item.platform_product_id, 'title': item.item_name_snapshot, 'url': ''})
    if registrations is None:
        registrations = list(OrderRegistration.objects.filter(tenant=user.tenant, store_id__in=stores,
            deleted_at__isnull=True, status__in=['registered', 'historical_recorded', 'completed', 'applied']).order_by('version', 'pk'))
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    from .summary_shipped_items import shipped_items
    if shipment_lookups is None:
        shipment_lookups = {r.order_id: r for r in OrderWarehouseLookup.objects.filter(order__tenant=user.tenant, order__store_id__in=stores)}
    sku_query = ProductSKU.objects.filter(tenant=user.tenant)
    if native:
        sku_query = sku_query.only('id', 'sku_code', 'legacy_sku_code')
    skus = {sku.pk: sku for sku in sku_query}
    aliases = defaultdict(set)
    for sku in skus.values():
        for code in [sku.sku_code, sku.legacy_sku_code]:
            if code:aliases[code.strip().casefold()].add(sku.pk)
    from .monthly_cost_adapter import monthly_cost_index, select_monthly_cost
    monthly_costs = monthly_cost_index(user.tenant)
    cost_query = ProductCostVersion.objects.filter(tenant=user.tenant).select_related('warehouse')
    if native:
        cost_query = cost_query.only(
            'id', 'sku_id', 'warehouse_id', 'warehouse__country_code', 'status',
            'confirmed_cost', 'currency', 'version_no', 'effective_from', 'effective_to',
        )
    cost_versions = list(cost_query)
    costs_by_sku = defaultdict(lambda: defaultdict(list))
    for version in cost_versions:
        costs_by_sku[version.sku_id][version.warehouse_id].append(version)
    fees = list(WarehouseFee.objects.filter(tenant=user.tenant, status='registered').filter(
        Q(store_id__in=stores) | Q(store__isnull=True, country__in={s.country_code for s in stores.values()})).select_related('store__platform').order_by('pk'))
    cost_flows, outbound_components = [], {}
    cost_orders = set(first) | {(o.store_id, o.external_order_id) for o in orders if o.pk in shipment_lookups}
    for store_id, external in sorted(cost_orders):
        day = first.get((store_id, external))
        store = stores[store_id];order = orders_by_key.get((store_id, external));key = str(store_id)+'|'+external
        lookup = shipment_lookups.get(order.pk) if order else None
        final, reasons = shipped_items(lookup, store.timezone)
        components, cost = [], ZERO
        for line in final:
            sku_id = line.get('sku_id') or line.get('internal_sku_id');code = line.get('source_sku') or ''
            if not sku_id and len(aliases[code.strip().casefold()]) == 1:sku_id = next(iter(aliases[code.strip().casefold()]))
            sku = skus.get(int(sku_id)) if sku_id else None
            candidates = {}
            for wh, versions in costs_by_sku.get(sku.pk if sku else None, {}).items():
                version = cost_on(versions, line['shipped_date'], store.timezone)
                if version and (not version.warehouse or version.warehouse.country_code == store.country_code):
                    candidates[wh] = version
            matched = {lookup.warehouse_id} if lookup and lookup.warehouse_id else set()
            version = candidates.get(next(iter(matched))) if len(matched) == 1 else None
            if monthly_costs is not None:
                cost_day = line["shipped_date"]
                if line.get("shipped_at_utc"):
                    from apps.products.monthly_cost_reconciliation import business_zone
                    cost_day = parse_datetime(line["shipped_at_utc"]).astimezone(business_zone()).date().isoformat()
                version = select_monthly_cost(monthly_costs, sku.pk if sku else None, lookup.warehouse_id if lookup else None, cost_day, version)
            quantity = int(line.get('quantity') or 0);reason = ''
            if not sku:reason = 'SKU尚未唯一关联'
            elif not version:reason = '缺出库日有效的对应仓库已确认成本'
            elif version.currency != 'CNY':reason = '成本币种尚未核对'
            if reason:reasons.append(reason)
            net = version.confirmed_cost * quantity if not reason else ZERO
            cost += net
            components.append({'sku_id': sku.pk if sku else None, 'sku_code': sku.sku_code if sku else '',
                'legacy_sku_code': sku.legacy_sku_code if sku else '', 'source_sku': code, 'quantity': quantity,
                'unit_cost': text(version.confirmed_cost) if version and not reason else None, 'net_cost': text(net),
                'gross_cost': text(net), 'return_credit': '0', 'currency': version.currency if version else 'CNY',
                'cost_version_id': version.pk if version else None, 'cost_version_no': version.version_no if version else None,
                'monthly_cost_id': getattr(version, 'monthly_cost_id', None),
                'monthly_cost_status': getattr(version, 'monthly_cost_status', None),
                'monthly_cost_month': getattr(version, 'monthly_cost_month', None),
                'cost_effective_from': version.effective_from.isoformat() if version else None,
                'cost_effective_to': version.effective_to.isoformat() if version and version.effective_to else None,
                'warehouse_id': lookup.warehouse_id if lookup else None, 'shipped_date': line['shipped_date'], 'warehouse_order_no': line['warehouse_order_no'], 'reasons': [reason] if reason else []})
        for index, component in enumerate(components):
            component['source_flow_id'] = f"warehouse-cost:{order.pk}:{component['warehouse_order_no']}:{index}"
            if not str(start) <= component['shipped_date'] <= str(end):continue
            cost_flows.append({'source_id': component['source_flow_id'],
                'kind': 'product_cost', 'date': component['shipped_date'], 'period_date': component['shipped_date'],
                'period_date_basis': '仓库实际出库日期', 'currency': 'CNY',
                'amount': text(-Decimal(component['net_cost'])) if not component['reasons'] else None,
                'country': store.country_code, 'platform': store.platform.platform_type,
                'store_id': store.pk, 'store_code': store.code, 'external_order_id': external,
                'scope': 'order', 'status': 'pending' if component['reasons'] else 'estimated' if component.get('monthly_cost_status') in ('estimated', 'pending_review') else 'confirmed',
                'source': 'SaaS仓库实际出库商品成本', 'raw_cost_flow': True,
                'description': f"出库单 {component['warehouse_order_no']}；SKU {component['source_sku']}；数量 {component['quantity']}；成本版本 {('月度 ' + str(component['monthly_cost_id'])) if component.get('monthly_cost_id') else component['cost_version_id'] or '待核'}" + ('；' + '；'.join(component['reasons']) if component['reasons'] else ''),
                'source_proof': {'order_id': order.pk, 'warehouse_lookup_id': lookup.pk,
                    'warehouse_id': lookup.warehouse_id, 'warehouse_order_no': component['warehouse_order_no'],
                    'cost_version_id': component['cost_version_id'],
                    'monthly_cost_id': component.get('monthly_cost_id'), 'monthly_cost_status': component.get('monthly_cost_status')},
                'cost_calculation': {'components': [component], 'state': 'pending' if component['reasons'] else 'calculated',
                    'reasons': component['reasons'], 'time_basis': 'warehouse_shipped_date'}})
        if order:outbound_components[order.pk] = components
        if day is None or (store_id, external) in prior_keys:continue
        f = add(store, 'product_cost', -cost if components and any(not c['reasons'] for c in components) else None, day, external, 'database:cost:'+str(store_id)+':'+external,
            currency='CNY', source='SaaS仓库实际出库商品成本', status='pending' if reasons else 'estimated' if any(c.get('monthly_cost_status') in ('estimated','pending_review') for c in components) else 'confirmed',
            cost_calculation={'components': components, 'state': 'pending' if reasons else 'calculated',
                'business_classification': classifications.get((store_id, external)) or classify(None),
                'time_basis': 'warehouse_shipped_date', 'cost_at': None, 'settlement_date': day, 'cost_timezone': store.timezone,
                'read_at': stamp, 'cost_field': 'MonthlyProductCost.unit_cost' if any(c.get('monthly_cost_id') for c in components) else 'ProductCostVersion.confirmed_cost',
                'gross_cost': text(cost), 'net_cost': text(cost), 'return_credit': '0', 'reasons': sorted(set(reasons)),
                'items_basis': '仓库已匹配订单的实际出库商品；换货登记不参与成本', 'ledger_writes': 0})

    # Registered fees only. Unregistered original warehouse bills remain outside calculation.
    for r in fees:
        if r.kind == 'order':
            store = stores.get(r.store_id)
            if not store:continue
            key = (r.store_id, r.external_order_id);order = orders_by_key.get(key)
            if not order or order.platform_id != store.platform_id or r.order_id not in (None, order.pk):continue
            day = settled.get(key)
            if not day:continue
            dates = {}
            if key not in first:
                shipping = order_dates.get(str(r.store_id)+'|'+r.external_order_id) or {
                    'date': None, 'order_id': None, 'basis': '', 'reason': '费用尚未唯一关联订单'}
                dates = {'statistics_date': shipping['date'], 'statistics_date_basis': shipping['basis'],
                    'statistics_date_reason': shipping['reason'], 'statistics_order_id': shipping['order_id']}
            add(store, 'warehouse_order', -r.amount, day, r.external_order_id, 'warehouse:'+str(r.pk),
                source='SaaS仓库处理费登记', currency=r.currency, warehouse_id=r.warehouse_id, source_bill_month=r.bill_month,
                warehouse_settlement_date=day,
                **dates,
                source_proof={'warehouse_fee_id': r.pk, 'version': r.version})
    # A settled order can carry a bill older than this report's source window.
    # Load only its original national pool, retaining that bill's fixed denominator.
    warehouse_periods = {(f['country'], f['source_bill_month']) for f in facts if f['kind'] == 'warehouse_order'}
    for r in fees:
        if r.kind == 'other' and (str(start)[:7] <= r.bill_month <= str(end)[:7]
                or (r.country, r.bill_month) in warehouse_periods):
            facts.append({'source_id': 'warehouse:'+str(r.pk), 'kind': 'warehouse_other', 'amount': text(-r.amount),
                'currency': r.currency, 'country': r.country, 'date': r.bill_month, 'scope': 'country',
                'status': 'reference' if r.source.get('type') == 'warehouse_settlement_adjustment' else 'confirmed',
                'store_id': None, 'external_order_id': '', 'source': 'SaaS国家仓库其他费登记', 'source_bill_month': r.bill_month})
    for r in registrations:
        if r.kind not in ('gcash', 'promotion'):continue
        store = stores[r.store_id];p = r.payload
        day = str(p.get('paid_at') if r.kind == 'gcash' else p.get('rate_date'))[:10]
        amount = p.get('amount') if r.kind == 'gcash' else p.get('cost')
        order = next((o for o in orders if o.pk == r.order_id), None)
        if not str(start) <= day <= str(end) or amount is None or not p.get('currency'):continue
        if order and (r.store_id, order.external_order_id) not in first:continue
        add(store, r.kind, -Decimal(str(amount)), day, order.external_order_id if order else '',
            'registration:'+str(r.pk), currency=p['currency'], source='SaaS费用登记', source_proof={'registration_id': r.pk, 'version': r.version})

    from .summary_return_costs import return_costs
    returns = return_costs(user, stores, outbound_components, aliases, start, end)
    facts.extend(returns)
    rates = {'monthly': {}, 'historical': {}}
    for r in FinanceSummaryInput.objects.filter(tenant=user.tenant).order_by('pk'):
        if r.kind == 'exchange_rate' and r.payload.get('basis') == 'historical':
            rates['historical'][r.source_key] = {**r.payload['quote'],
                'input_id': r.pk, 'source_hash': r.source_hash, 'source_description': r.source_description}
        elif r.kind == 'adjustment' and r.store_id in stores and str(start)[:7] <= r.period[:7] <= str(end)[:7]:
            p = r.payload
            if p.get('order') and (r.store_id, p['order']) not in first:continue
            add(stores[r.store_id], 'adjustment', Decimal(str(p['amount'])), (p.get('occurred_at') or p.get('date') or r.period)[:10], p.get('order') or '',
                'database:adjustment:'+str(r.pk), source='SaaS原始调整报表', source_proof={'input_id': r.pk, 'source_hash': r.source_hash},
                description=p.get('scenario') or p.get('fee_type') or '')

    _advertising(user, stores, start, end, facts, add, seen)
    recharge, cycles = _cashflows(user, stores, facts, add, start, end)
    from apps.masterdata.monthly_exchange_rates import monthly_average_quotes
    months = {str(start)[:7], str(end)[:7]} | {f['date'][:7] for f in facts}
    months.update(f['source_bill_month'] for f in facts if f.get('source_bill_month'))
    pairs = set()
    for store in stores.values():
        currencies = {'CNY', 'USD'} | {f['currency'] for f in facts if f['country'] == store.country_code}
        pairs.update((store.country_code, currency, store.currency) for currency in currencies)
    rates['monthly'] = monthly_average_quotes(user.tenant, months, pairs)
    for store in stores.values():
        if store.code != 'SP6TH':
            continue
        periods = sorted({f['date'][:7] for f in facts if f.get('store_id') == store.pk})
        for period in periods:
            if not any(f.get('store_id') == store.pk and f['kind'] == 'adjustment' and f['date'].startswith(period) for f in facts):
                add(store, 'adjustment', None, period, source_id='database:coverage:'+str(store.pk)+':'+period+':adjustment',
                    source='SaaS来源覆盖检查', description='未获取独立调整来源，保留待核')
    basis = {}
    for r in WarehouseBillUpload.objects.filter(tenant=user.tenant).order_by('created_at'):
        p = r.summary or {}
        if p.get('country') and p.get('bill_month') and p.get('order_detail_sum') is not None:
            key = '|'.join([p['country'], p['bill_month'], p.get('currency') or 'CNY'])
            basis[key] = {'total': str(p['order_detail_sum']), 'file': r.file_name, 'sha256': r.file_hash}
    from .summary_raw_flows import source_flows
    raw_flows = [{'native_fact_index': index} for index in range(financial_fact_count)]
    raw_flows.extend(source_flows(stores, financial_rows, fees, registrations,
        FinanceSummaryInput.objects.filter(tenant=user.tenant, kind='adjustment', store_id__in=stores),
        facts, start, end))
    raw_flows.extend(cost_flows)
    raw_flows.extend(dict(row) for row in returns)
    convert_costs(facts, stores, rates)
    shares = warehouse_shares(facts, basis, rates)
    members = [] if native else _sku_members(facts, rates)
    # Product routes use only stored platform shop/product IDs.
    for (sid, pid), product in products.items():
        store = stores[sid];host = {'PH': 'com.ph', 'TH': 'co.th', 'MY': 'com.my'}.get(store.country_code)
        if store.platform.platform_type == 'lazada' and host and str(pid).isdigit():product['url'] = 'https://www.lazada.'+host+'/products/i'+str(pid)+'.html'
        elif store.platform.platform_type == 'shopee' and str(pid).isdigit():
            identity = str(store.external_store_id or '')
            if not identity.isdigit() and len(provider_shops[sid]) == 1:identity = next(iter(provider_shops[sid]))
            host = {'PH': 'ph', 'TH': 'co.th', 'MY': 'com.my'}.get(store.country_code)
            if host and identity.isdigit():product['url'] = 'https://shopee.'+host+'/product/'+identity+'/'+str(pid)
    return {'schema': 'saas-finance-database.v1', 'read_at': stamp, 'scope': scope, 'raw': raw, 'facts': facts,
            'shares': shares, 'rates': rates, 'order_dates': order_dates, 'cost_flows': cost_flows, 'raw_flows': raw_flows, 'sku_members': members, 'sku_sales': sku_sales,
            'products': {'rows': catalogue, 'products': list(products.values())}, 'shopee_income': shopee_income,
            'recharge': recharge, 'cycles': cycles, 'source_counts': {'platform_finance': financial_count, 'facts': len(facts),
            'order_items': sum(map(len, sku_sales['orders'].values())), 'cost_versions': len(cost_versions), 'warehouse_registered': len(fees)}}


def _advertising(user, stores, start, end, facts, add, seen):
    from apps.integrations.models import ShopeeAdvertisingRecord
    from apps.integrations.lazada_api_models import LazadaAdvertisingDailySpend
    for r in LazadaAdvertisingDailySpend.objects.filter(tenant=user.tenant, store_id__in=stores, report_date__range=(start, end)):
        add(stores[r.store_id], 'advertising', -r.spend, r.report_date, source_id='lazada-smax:'+str(r.pk),
            source='SaaS Sponsored Max日报', currency=r.currency, saas_lazada=True)
    for r in ShopeeAdvertisingRecord.objects.filter(tenant=user.tenant, store_id__in=stores, kind='shop_daily', report_date__range=(start, end)).order_by('pk'):
        if r.data.get('expense') is None:continue
        key = (r.store_id, str(r.report_date))
        if key in seen:raise ValidationError('同店同日广告日报重复，未汇总。')
        seen[key] = r.pk
        add(stores[r.store_id], 'advertising', -Decimal(str(r.data['expense'])), r.report_date,
            source_id='shopee-advertising:'+str(r.pk), source='SaaS站内广告实际消耗', source_proof={'advertising_record_id': r.pk})


def _cashflows(user, stores, facts, add, start, end):
    from apps.integrations.models import SyncRawEnvelope
    from apps.integrations.lazada_api_models import LazadaApiSnapshot
    recharge = {'shops': [], 'transactions': [], 'actualSpend': None}
    cycles = {'shops': {}}
    for store in stores.values():
        shop = {'id': store.pk, 'code': store.code, 'country': store.country_code, 'currency': store.currency}
        if store.platform.platform_type == 'lazada':cycles['shops'][store.code] = {**shop, 'months': {}, 'rows': []}
        else:recharge['shops'].append(shop)
    # Latest immutable, complete snapshot per endpoint, then dedup by provider ID.
    envelopes = SyncRawEnvelope.objects.filter(tenant=user.tenant, store_id__in=stores,
        schema_version='finance-source-backfill.v1').order_by()
    latest = {}
    for r in envelopes:
        key = (r.store_id, r.endpoint, r.payload.get('month') or '2026-08..09')
        if key not in latest or r.pk > latest[key].pk:latest[key] = r
    for r in latest.values():
        store = stores[r.store_id];p = r.payload
        if 'wallet_transaction' in r.endpoint:
            if not p.get('complete'):raise ValidationError('余额交易快照不完整，未使用。')
            seen = set()
            for row in p['rows']:
                if row['transaction_id'] in seen:raise ValidationError('余额交易ID重复。')
                seen.add(row['transaction_id'])
                if row['transaction_type'] != 'SVS_PAYMENT_DEDUCT':continue
                day = row['local_time'][:10];amount = Decimal(row['amount'])
                add(store, 'shop_adjustment', amount, day, source_id='html2:sp6th:wallet:'+row['transaction_id'],
                    adjustment_event=True, scenario='SVS_PAYMENT_DEDUCT', source='SaaS余额交易', source_proof={'envelope_id': r.pk, 'transaction_id': row['transaction_id']})
                recharge['transactions'].append({'id': 'wallet:'+row['transaction_id'], 'shop': store.code, 'date': day,
                    'time': row['local_time'], 'debit': format(-amount, '.2f'), 'sourceType': 'wallet'})
            recharge['walletSnapshotAt'] = p['fetched_at']
        elif 'billing_transaction' in r.endpoint:
            if not p.get('reconciled'):raise ValidationError('拨款账单未对平。')
            for row in p['transactions']:
                if row['level'] != 'SHOP' or row['cost_header'] != 'Marketing Fee':continue
                day = row['local_time'][:10];amount = Decimal(str(row['amount']))
                add(store, 'shop_adjustment', amount, day, source_id='database:billing:'+row['source_key'],
                    adjustment_event=True, scenario='Paid Ads Service', source='SaaS拨款账单', source_proof={'envelope_id': r.pk, 'source_key': row['source_key']})
                recharge['transactions'].append({'id': 'billing:'+row['source_key'], 'shop': store.code, 'date': day,
                    'time': row['local_time'], 'debit': format(-amount, '.2f'), 'sourceType': 'billing', 'payoutId': row['payout_id']})
            recharge['billingSnapshotAt'] = p['fetched_at']
    for shop in recharge['shops']:
        if not shop['code'].startswith('SPKJ'):continue
        days = [{'date': f['date'], 'amount': text(-Decimal(f['amount']))} for f in facts if f['store_id'] == shop['id'] and f['kind'] == 'advertising' and f['amount'] is not None]
        months = []
        for period in sorted({d['date'][:7] for d in days}):
            chosen = [d for d in days if d['date'].startswith(period)]
            count = calendar.monthrange(int(period[:4]), int(period[5:]))[1]
            months.append({'month': period, 'days': len(chosen), 'expense': text(sum((Decimal(d['amount']) for d in chosen), ZERO)), 'complete': len({d['date'] for d in chosen}) == count})
        recharge['actualSpend'] = {'shop': shop['code'], 'monthly': months, 'days': days}
    unique = {}
    snaps = LazadaApiSnapshot.objects.filter(tenant=user.tenant, authorization__store_id__in=stores,
        operation='account_transactions', status='succeeded').select_related('authorization').order_by()
    for r in snaps:
        if hashlib.sha256(json.dumps(r.response, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != r.response_hash:
            raise ValidationError('Lazada账户快照校验失败。')
        for row in (r.response.get('data') or {}).get('transactions') or []:
            key = (r.authorization.store_id, str(row['transaction_number']))
            if key not in unique or r.pk > unique[key][0]:unique[key] = (r.pk, row)
    for (store_id, identity), (snapshot_id, row) in unique.items():
        store = stores[store_id];shop = cycles['shops'].get(store.code)
        if shop is None:continue
        try:when = datetime.fromisoformat(row['transaction_time'])
        except ValueError:when = datetime.strptime(row['transaction_time'], '%d %b %Y %H:%M:%S')
        if not start <= when.date() <= end:continue
        shop['rows'].append({'id': identity, 'time': when.isoformat(), 'date': str(when.date()),
            'amount': text(Decimal(str(row['amount']).replace(',', ''))), 'currency': row['currency'],
            'type': row['type'], 'sub_type': row['sub_type'], 'snapshotId': snapshot_id})
    return recharge, cycles


def warehouse_shares(facts, basis, rates):
    result = {'store': [], 'order': [], 'unallocated': []}
    for source in [f for f in facts if f['kind'] == 'warehouse_other' and f['scope'] == 'country']:
        if source.get('status') != 'confirmed':
            result['unallocated'].append({**source, 'reason': '原账单结算差额，按原要求保留国家原归属，不向店铺分配'})
            continue
        month = source['source_bill_month'];control = basis.get('|'.join([source['country'], month, source['currency']]))
        fees = [f for f in facts if f['kind'] == 'warehouse_order' and f['country'] == source['country']
                and f['source_bill_month'] == month and f['currency'] == source['currency'] and Decimal(f['amount']) < 0]
        weights = defaultdict(Decimal)
        for f in fees:weights[(f['store_id'], f['external_order_id'])] -= Decimal(f['amount'])
        known = sum(weights.values(), ZERO);denominator = Decimal(control['total']) if control else ZERO
        if not denominator or not known or known > denominator:
            result['unallocated'].append({**source, 'reason': '缺完整国家账单分母或对应已登记处理费，保留国家原归属'})
            continue
        store_weights = defaultdict(Decimal)
        for (sid, order), value in weights.items():store_weights[str(sid)] += value
        targets = list(store_weights.items())
        if known < denominator:targets.append(('unassigned', denominator-known))
        original = split_amount(source['amount'], targets)
        currency = {'PH': 'PHP', 'TH': 'THB', 'MY': 'MYR'}.get(source['country'])
        quote = rates['monthly'].get('|'.join([month, source['country'], source['currency'], currency or '']))
        rate = quote['rate'] if quote else None
        local = split_amount(Decimal(source['amount'])*Decimal(rate), targets) if rate else {}
        fee_map = {(f['store_id'], f['external_order_id']): f for f in fees}
        for sid, portion in original.items():
            if sid == 'unassigned':
                result['unallocated'].append({**source, 'amount': text(portion), 'reason': '完整账单内其他订单对应份额，保留国家原归属'})
                continue
            selected = [(order, value) for (store_id, order), value in weights.items() if str(store_id) == sid]
            amounts = split_amount(portion, selected)
            converted = split_amount(local[sid], selected) if sid in local else {}
            for order, amount in amounts.items():
                fee = fee_map[(int(sid), order)]
                result['order'].append({**source, 'amount': text(amount),
                    'store_id': fee['store_id'], 'store_code': fee['store_code'], 'platform': fee['platform'],
                    'external_order_id': order, 'date': fee['date'], 'scope': 'order', 'allocated': True,
                    **{key: fee[key] for key in ['warehouse_settlement_date', 'statistics_date', 'statistics_date_basis', 'statistics_date_reason', 'statistics_order_id'] if key in fee},
                    'warehouse_allocation': {'method': 'warehouse_fee_share', 'source_id': source['source_id'],
                        'source_amount': source['amount'], 'country_total': text(denominator), 'store_weight': text(store_weights[sid]),
                        'order_weight': text(weights[(int(sid), order)]), 'month': month, 'control': control,
                        'local_currency': currency, 'rate': rate, 'local_amount': text(converted.get(order))},
                    'description': '按完整国家账单固定分母分配到店铺，再分到原订单；SKU层按最终数量分摊'})
    return result


def _sku_members(facts, rates):
    rows = []
    for f in facts:
        if f.get('platform') != 'lazada' or f['kind'] != 'product_cost':continue
        for i, c in enumerate(f['cost_calculation']['components']):
            value = c['local_amount']
            rows.append({'country': f['country'], 'platform': f['platform'], 'store': str(f['store_id']),
                'shop': f['store_code'], 'month': f['date'][:7], 'currency': c['local_currency'], 'sku_id': c['sku_id'],
                'code': c['sku_code'], 'legacy': c['legacy_sku_code'], 'platform_sku': c['source_sku'],
                'identity': 'internal:'+str(c['sku_id']) if c['sku_id'] else 'cost:'+f['source_id']+':'+str(i),
                'amounts': {'product_cost': value}, 'orders': [f['platform']+'|'+str(f['store_id'])+'|'+f['external_order_id']],
                'pending': bool(c['reasons']) or value is None, 'source': 'saas', 'proof': [], 'cost_qty': c['quantity'],
                'component': c, 'fact': f, 'cost_conversion': f['cost_conversion']})
    return rows
