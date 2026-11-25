"""Bounded, read-only source pages. No dataset, calculator or provider dependency."""
from datetime import date, timedelta
from calendar import monthrange
from decimal import Decimal, InvalidOperation
import hashlib
import json
from contextlib import contextmanager

from django.core import signing
from django.db import connection, DatabaseError, OperationalError
from django.db.models import Case, When, Value, F, Q, CharField, DateField, Exists, OuterRef
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Concat, Lower, Trim, Substr, NullIf
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from apps.common.responses import success_response, error_response
from apps.permissions.api_permissions import IsFinanceViewer
from apps.masterdata.models import StoreMaster
from .summary_scopes import request_access, store_ids, full_reader, signature
from .summary_service import require_access

KINDS = dict(sales='订单销售额', refund='订单退款', settlement='结算回款（参考）',
    order_fee='订单费用', adjustment='订单调整', shop_adjustment='店铺调整',
    warehouse_order='仓库处理费', warehouse_other='仓库其他处理费', gcash='GCash退款',
    promotion='刷单费用', advertising='广告实际消耗')
SALT = 'finance-source-flow-page-v1'
SOURCE_KINDS = {
    'finance-transaction':{'sales','refund','settlement','order_fee','adjustment','shop_adjustment'},
    'warehouse':{'warehouse_order','warehouse_other'},'registration':{'gcash','promotion'},
    'database-adjustment':{'adjustment','shop_adjustment'},
    'shopee-advertising':{'advertising'},'lazada-smax':{'advertising'},
}


@contextmanager
def read_budget():
    previous = None
    if connection.vendor=='mysql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT @@SESSION.MAX_EXECUTION_TIME');previous=int(cursor.fetchone()[0])
            cursor.execute('SET SESSION MAX_EXECUTION_TIME=%s',[min(previous,1000) if previous else 1000])
    try:
        yield
    except OperationalError as exc:
        if exc.args and exc.args[0] in {3024,1317}:
            raise ValidationError('原始流水读取超过时限，请选择具体店铺、缩短日期范围或使用完整订单号；未返回截断结果。') from None
        raise
    finally:
        if previous is not None:
            try:
                with connection.cursor() as cursor:cursor.execute('SET SESSION MAX_EXECUTION_TIME=%s',[previous])
            except DatabaseError:
                connection.close()


class FlowQuery(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    period_type = serializers.ChoiceField(choices=['month', 'week', 'half_month'], default='month')
    undated = serializers.BooleanField(default=False)
    store = serializers.IntegerField(min_value=1, required=False)
    country = serializers.RegexField(r'^[A-Z]{2}$', required=False)
    platform = serializers.ChoiceField(choices=['lazada', 'shopee', 'tiktok'], required=False)
    currency = serializers.RegexField(r'^[A-Z]{3}$', required=False)
    kind = serializers.ChoiceField(choices=list(KINDS), required=False)
    status = serializers.ChoiceField(choices=['confirmed', 'pending', 'reference'], required=False)
    order = serializers.CharField(max_length=191, required=False)
    keyword = serializers.CharField(max_length=100, required=False)
    cursor = serializers.CharField(max_length=2048, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)

    def validate(self, attrs):
        if not 0 <= (attrs['end'] - attrs['start']).days <= 365:
            raise ValidationError('请选择起止顺序正确且不超过366天的日期范围。')
        return attrs


def text_json(field, key):
    return NullIf(NullIf(Cast(KeyTextTransform(key, field), CharField()), Value('null')), Value(''))


def parsed_day(expr):
    # A month is not a day. Never substitute creation timestamps for business dates.
    return Cast(Substr(expr, 1, 10), DateField())


def streams(user, stores, query):
    from .models import PlatformFinanceTransaction
    from .warehouse_fee_models import WarehouseFee
    from .summary_models import FinanceSummaryInput
    from apps.sales_management.registration_models import OrderRegistration
    from apps.integrations.models import ShopeeAdvertisingRecord
    from apps.integrations.lazada_api_models import LazadaAdvertisingDailySpend
    common = dict(tenant_id=user.tenant_id, store_id__in=stores)
    result = []

    def add(key, qs, *, day, kind, amount, currency, order=Value(''), description=Value(''),
            state=Value('confirmed'), month=Value(''), sign=1, country=Value(''), label):
        if query.get('kind') and query['kind'] not in SOURCE_KINDS[key]:return
        qs = qs.annotate(flow_day=day, flow_month=month, flow_kind=kind,
            flow_amount=Cast(amount, CharField()), flow_currency=currency, flow_order=order,
            flow_description=description, flow_state=state, flow_country=country)
        qs = qs.annotate(flow_state=Case(
            When(Q(flow_amount__isnull=True) | Q(flow_currency='') | ~Q(flow_amount__regex=r'^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$'), then=Value('pending')),
            default=F('flow_state'), output_field=CharField()))
        if query.get('_detail'):
            pass
        elif query.get('undated'):
            qs = qs.filter(flow_day__isnull=True)
            # Month-only sources remain bounded to their declared billing month.
            qs = qs.filter(Q(flow_month='') | Q(flow_month__range=(str(query['start'])[:7], str(query['end'])[:7])))
        else:
            dates = Q(flow_day__range=(query['start'], query['end']))
            if query.get('period_type', 'month') == 'month':
                start, end = query['start'], query['end']
                first = start.replace(day=1) if start.day==1 else (start.replace(day=28)+timedelta(days=4)).replace(day=1)
                last = end.replace(day=1) if end.day==monthrange(end.year,end.month)[1] else (end.replace(day=1)-timedelta(days=1)).replace(day=1)
                if first<=last:dates |= Q(flow_day__isnull=True, flow_month__range=(str(first)[:7],str(last)[:7]))
            qs = qs.filter(dates)
        for param, field in [('kind', 'flow_kind'), ('currency', 'flow_currency'), ('status', 'flow_state'), ('order', 'flow_order')]:
            if query.get(param):qs = qs.filter(**{field: query[param]})
        if query.get('keyword') and query['keyword'].casefold() not in label.casefold():
            qs = qs.filter(flow_description__icontains=query['keyword'])
        # Undated rows sort after dated rows; their displayed month remains explicit.
        sort_date = F('flow_day') if key in {'finance-transaction','shopee-advertising','lazada-smax'} and not query.get('undated') else Coalesce('flow_day', Value(date(1900, 1, 1)), output_field=DateField())
        qs = qs.annotate(flow_date=sort_date)
        result.append((key, qs, sign, label))

    finance = PlatformFinanceTransaction.objects.filter(**common).annotate(fee_name=Lower(Trim('raw_fee_name')))
    kind = Case(
        When(fee_name__in=['item price credit', 'order_selling_price', 'order_original_price'], then=Value('sales')),
        When(fee_name='escrow_amount', then=Value('settlement')),
        When(Q(fee_category='refund') | Q(fee_name__in=['reversal item price', 'shipping fee refund to customer', 'seller_return_refund']), then=Value('refund')),
        When(Q(fee_category='adjustment') | Q(fee_name__in=['wrong shipping fee adjustment', 'lost claim', 'damaged claim', 'commission fee - correction for undercharge', 'payment fee - correction for undercharge']), then=Case(When(external_order_id='', then=Value('shop_adjustment')), default=Value('adjustment'))),
        default=Value('order_fee'), output_field=CharField())
    state = Case(When(match_status='conflict', then=Value('pending')),
        When(fee_name__in=['escrow_amount', 'order_original_price'], then=Value('reference')),
        default=Value('confirmed'), output_field=CharField())
    add('finance-transaction', finance, day=F('business_date'), kind=kind, amount=F('signed_amount'),
        currency=F('currency'), order=F('external_order_id'), description=F('raw_fee_name'), state=state, label='SaaS平台原始财务记录')

    fees = WarehouseFee.objects.filter(tenant_id=user.tenant_id, status='registered')
    permitted = Q(store_id__in=stores)
    if full_reader(user) and not query.get('store') and not query.get('platform'):
        permitted |= Q(store__isnull=True, **({'country':query['country']} if query.get('country') else {}))
    fees = fees.filter(permitted)
    add('warehouse', fees, day=F('occurred_on'), month=F('bill_month'),
        kind=Case(When(kind='order', then=Value('warehouse_order')), default=Value('warehouse_other'), output_field=CharField()),
        amount=F('amount'), currency=F('currency'), order=F('external_order_id'), description=F('fee_item'), sign=-1,
        country=F('country'), state=Case(When(source__type='warehouse_settlement_adjustment', then=Value('reference')), default=Value('confirmed'), output_field=CharField()), label='SaaS仓库处理费登记')

    registrations = OrderRegistration.objects.filter(**common, kind__in=['gcash', 'promotion'], deleted_at__isnull=True,
        status__in=['registered', 'historical_recorded', 'completed', 'applied'])
    registrations = registrations.filter(Q(order__isnull=True) | Q(order__tenant_id=user.tenant_id, order__store_id=F('store_id')))
    paid = Case(When(kind='gcash', then=text_json('payload', 'paid_at')), default=text_json('payload', 'rate_date'), output_field=CharField())
    value = Case(When(kind='gcash', then=text_json('payload', 'amount')), default=text_json('payload', 'cost'), output_field=CharField())
    add('registration', registrations, day=parsed_day(paid), kind=F('kind'), amount=value,
        currency=Coalesce(text_json('payload', 'currency'), Value('')), order=Coalesce(F('order__external_order_id'), Value('')),
        description=Case(When(kind='gcash',then=Value('GCash退款登记')),default=Value('订单推广登记'),output_field=CharField()), sign=-1, label='SaaS费用登记')

    adjustments = FinanceSummaryInput.objects.filter(**common, kind='adjustment')
    day_text = Coalesce(text_json('payload', 'occurred_at'), text_json('payload', 'date'),
        Case(When(period__regex=r'^\d{4}-\d{2}-\d{2}$', then=F('period')), default=Value(None), output_field=CharField()))
    add('database-adjustment', adjustments, day=parsed_day(day_text), month=Substr('period', 1, 7),
        kind=Case(When(Q(payload__order='') | Q(payload__order__isnull=True), then=Value('shop_adjustment')), default=Value('adjustment'), output_field=CharField()),
        amount=text_json('payload', 'amount'), currency=Coalesce(text_json('payload', 'currency'), F('store__currency')),
        order=Coalesce(text_json('payload', 'order'), Value('')), description=Coalesce(text_json('payload', 'scenario'), text_json('payload', 'fee_type'), Value('原始调整报表')), label='SaaS原始调整报表')

    ads = ShopeeAdvertisingRecord.objects.filter(**common, kind='shop_daily')
    newer = ShopeeAdvertisingRecord.objects.filter(tenant_id=user.tenant_id, kind='shop_daily',
        store_id=OuterRef('store_id'), report_date=OuterRef('report_date'), pk__gt=OuterRef('pk'))
    ads = ads.filter(~Exists(newer))
    add('shopee-advertising', ads, day=F('report_date'), kind=Value('advertising'), amount=text_json('data', 'expense'),
        currency=F('currency'), description=Value('店铺日报实际消耗'), sign=-1, label='SaaS Shopee广告日报（非扣款流水）')
    add('lazada-smax', LazadaAdvertisingDailySpend.objects.filter(**common), day=F('report_date'), kind=Value('advertising'),
        amount=F('spend'), currency=F('currency'), description=Value('Sponsored Max日报实际消耗'), sign=-1, label='SaaS Lazada广告日报（非扣款流水）')
    return result


def visible_stores(user, query):
    require_access(user)
    ids = store_ids(user)
    if query.get('store') and query['store'] not in ids:raise PermissionDenied('店铺不在当前授权范围内。')
    all_stores = list(StoreMaster.objects.filter(tenant_id=user.tenant_id, pk__in=ids).select_related('platform').order_by('code'))
    selected = [s for s in all_stores if (not query.get('store') or s.pk==query['store'])
        and (not query.get('country') or s.country_code==query['country'])
        and (not query.get('platform') or s.platform.platform_type==query['platform'])]
    return {s.pk:s for s in selected}, signature(user, ids), all_stores


FIELDS = ['pk', 'store_id', 'flow_day', 'flow_month', 'flow_date', 'flow_kind', 'flow_amount',
    'flow_currency', 'flow_order', 'flow_description', 'flow_state', 'flow_country']


def present(key, row, stores, sign, label):
    store = stores.get(row['store_id'])
    try:
        amount = Decimal(row['flow_amount'])
        if sign < 0:amount = amount.copy_negate()
        if not amount.is_finite():raise InvalidOperation
        amount = str(amount)
    except (InvalidOperation, TypeError):amount = None
    status = row['flow_state'] if amount is not None else 'pending'
    source_id = f"{key}:{row['pk']}"
    return {'key':source_id, 'source_id':source_id, 'kind':row['flow_kind'], 'label':KINDS[row['flow_kind']],
        'date':str(row['flow_day']) if row['flow_day'] else row['flow_month'] or '未注明日期',
        'date_basis':'原始业务日期' if row['flow_day'] else '仅有来源月份，未推断具体日期' if row['flow_month'] else '来源缺少业务日期',
        'original_amount':amount, 'original_currency':row['flow_currency'], 'amount':None, 'conversion':None,
        'identity':{'shop':store.code if store else '未归属店铺', 'store':str(store.pk) if store else '',
            'country':store.country_code if store else row['flow_country'],
            'platform':store.platform.platform_type if store else '', 'currency':row['flow_currency'], 'order':row['flow_order']},
        'mode_label':'原始记录（未分摊）', 'status':{'confirmed':'已确认','pending':'待核','reference':'参考，不重复计入'}[status],
        'source_status':status, 'source':label, 'description':row['flow_description'], 'editable':False,
        'edit_block_reason':'原始来源只读；此页不修改汇总参与状态。'}


def page(user, query):
    stores, access, all_stores = visible_stores(user, query)
    size = query.get('page_size', 50)
    identity = hashlib.sha256(json.dumps([user.pk, user.tenant_id, access,
        {k:str(v) for k,v in query.items() if k != 'cursor'}], sort_keys=True).encode()).hexdigest()
    cursor = None
    if query.get('cursor'):
        try:
            token = signing.loads(query['cursor'], salt=SALT, max_age=3600)
            if token['scope'] != identity:raise ValueError
            cursor = (date.fromisoformat(token['date']), int(token['rank']), int(token['pk']))
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            raise ValidationError('翻页条件或权限已变化，请重新查询第一页。')
    candidates = []
    with read_budget():
        for rank, (key, qs, sign, label) in enumerate(streams(user, stores, query)):
            if cursor:
                day, previous_rank, pk = cursor
                boundary = Q(flow_date__lt=day)
                if rank < previous_rank:boundary |= Q(flow_date=day)
                elif rank == previous_rank:boundary |= Q(flow_date=day, pk__lt=pk)
                qs = qs.filter(boundary)
            # A fixed per-source bound: never OFFSET, COUNT, or load the source body.
            for row in qs.order_by('-flow_date', '-pk').values(*FIELDS)[:size+1]:
                candidates.append(((row['flow_date'], rank, row['pk']), present(key,row,stores,sign,label)))
    candidates.sort(key=lambda item:item[0], reverse=True)
    selected = candidates[:size];more = len(candidates)>size
    next_cursor = None
    if more:
        day, rank, pk = selected[-1][0]
        next_cursor = signing.dumps({'scope':identity,'date':str(day),'rank':rank,'pk':pk},salt=SALT,compress=True)
    return {'rows':[r for _,r in selected], 'has_more':more, 'next_cursor':next_cursor, 'total':None,
        'page_size':size, 'tenant_id':str(user.tenant_id), 'access_signature':access, 'source_flows':True,
        'note':'实时原始记录，不依赖已发布汇总；广告日报不是扣款流水。未进行汇率折算、成本计算或分摊。',
        'period_warning':'待归期记录未推断日期；缺少来源月份的登记仅按授权店铺列出，不认定属于所选账期。' if query.get('undated') else '',
        'options':{'raw_flows':True,'stores':[{'id':str(s.pk),'code':s.code,'country':s.country_code,'platform':s.platform.platform_type,'currency':s.currency} for s in all_stores],
            'countries':{**{s.country_code:s.country_code for s in all_stores},**{r['identity']['country']:r['identity']['country'] for _,r in selected if r['identity']['country']}},'months':[],
            'currencies':sorted({s.currency for s in all_stores} | {r['original_currency'] for _,r in selected if r['original_currency']}),
            'kinds':[{'key':k,'label':v} for k,v in KINDS.items()]}}


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def source_flow_page(request):
    query = FlowQuery(data=request.query_params)
    try:
        if set(request.query_params)-set(query.fields):raise ValidationError('包含未支持的流水查询字段。')
        query.is_valid(raise_exception=True)
        response = success_response(page(request.user, query.validated_data))
    except ValidationError as exc:
        detail=exc.detail
        if isinstance(detail,dict):detail=[str(item) for values in detail.values() for item in (values if isinstance(values,list) else [values])]
        response=error_response('FINANCE_SOURCE_QUERY_INVALID','；'.join(map(str,detail if isinstance(detail,list) else [detail])))
    response['Cache-Control']='no-store'
    return response


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def source_flow_detail(request, source, pk):
    stores, _, _ = visible_stores(request.user, {})
    for key, qs, sign, label in streams(request.user, stores, {'_detail':True}):
        if key != source:continue
        row = qs.filter(pk=pk).values(*FIELDS).first()
        if not row:raise NotFound('原始流水不存在或不在当前授权范围内。')
        data = present(key,row,stores,sign,label)
        response=success_response({'title':'原始流水来源', 'amount':data['original_amount'],
            'note':data['source']+' · '+data['source_id']+' · '+data['date_basis']+'；原币 '+data['original_currency']+'，未折算、未分摊。',
            'parts':[{'label':data['description'] or data['label'],'amount':data['original_amount'],'source':data['source_id']}],
            'records':[], 'source_flow':data})
        response['Cache-Control']='no-store';return response
    raise NotFound('未支持的原始流水来源。')
