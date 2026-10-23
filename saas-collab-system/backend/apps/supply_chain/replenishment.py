"""Strategy-backed sales and replenishment references shared by supply and operating roles."""
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from math import ceil

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.masterdata.models import CountrySiteMaster
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.products.models import ProductSKU
from apps.sales_management import operating as operating_domain
from apps.supply_chain.api import validated
from apps.supply_chain.dates import business_date
from apps.supply_chain import services
from apps.supply_chain.models import ReplenishmentStrategy, domain_write
from apps.supply_chain.permissions import MANAGE, VIEW
from apps.supply_chain.replenishment_math import _as_decimal, forecast_timeline
from apps.supply_chain.views import ReadAPI

DEFAULTS = {'cycle_days': 10, 'lead_days': 45, 'safety_days': 35,
            'sales_model': 'weighted', 'sales_weights': {'7': 50, '15': 30, '30': 20}}
STRATEGY_PERMISSION = 'supply.v2.manage'


def weighted_daily_sales(daily_units, weights):
    if any(daily_units.get(day) is None for day in (7, 15, 30)):
        return None
    return sum((daily_units[day] * Decimal(weights[str(day)]) / Decimal(100) for day in (7, 15, 30)), Decimal(0))


def target_stock_quantity(daily_sales, start_date, horizon_days, activity_start=None, activity_end=None, activity_factor=Decimal(1)):
    return forecast_timeline(daily=daily_sales, today=start_date, lead_days=horizon_days,
        cycle_days=0, safety_days=0, stock=None, eta_rows=[], activity_start=activity_start,
        activity_end=activity_end, activity_factor=activity_factor)['target_stock']


def replenishment_quantities(target_stock, stock, incoming, submitted, draft_reserved, *, target_ratio=None):
    if any(value is None for value in (target_stock, stock, incoming, submitted, draft_reserved)):
        return None, None
    target = Fraction(*target_ratio) if target_ratio is not None else Fraction(target_stock)
    gap = max(Fraction(0), target - Fraction(stock) - Fraction(incoming))
    suggested = ceil(max(Fraction(0), target - Fraction(stock) - Fraction(incoming)
                         - Fraction(submitted) - Fraction(draft_reserved)))
    return _as_decimal(gap), suggested


def evaluate_replenishment_row(row, strategy, *, sales_end, activity_start=None, activity_end=None,
                               activity_factor=Decimal(1), today=None):
    """Single authoritative T/I/P/O/Q calculation for reference and order preview."""
    today = today or business_date()
    windows = {str(w['days']): w for w in row['sales_windows']}
    blocking = set(row.get('blocking_issues') or [])
    sales_unknown = any(windows[str(day)]['units'] is None or not windows[str(day)]['coverage_complete']
                        for day in (7, 15, 30)) or bool(blocking.intersection({
        'no_sales_facts', 'no_authorized_sales_store', 'invalid_store_timezone', 'unfinished_store_day',
        'bundle_composition_unverified', 'unmapped_sales_lines', 'collection_coverage_unproven'}))
    daily_values = {day: Decimal(str(windows[str(day)]['units'])) / Decimal(day)
                    for day in (7, 15, 30) if windows[str(day)]['units'] is not None}
    weights = {'7': 0, '15': 0, '30': 100} if strategy.sales_model == 'ordinary' else strategy.sales_weights
    daily = weighted_daily_sales(daily_values if not sales_unknown else {7: None, 15: None, 30: None}, weights)
    exact_daily = None if sales_unknown else sum((
        Fraction(Decimal(str(windows[str(day)]['units']))) * Fraction(Decimal(str(weights[str(day)])))
        / (day * 100) for day in (7, 15, 30)), Fraction(0))
    pipe = row['pipeline']
    stock_complete = bool(row.get('inventory_complete')) and not blocking.intersection({
        'missing_inventory_snapshot', 'available_quantity_unverified', 'inventory_source_incomplete',
        'stale_inventory_snapshot', 'ambiguous_inventory_aliases', 'unmapped_inventory'})
    stock = Decimal(row['available_stock']) if row['available_stock'] is not None and stock_complete else None
    supply_known = pipe.get('authorized') and not pipe.get('unknown_eta') and not pipe.get('received_awaiting_wms') and not any(
        issue in pipe.get('issues', []) for issue in ('warehouse_supply_scope_incomplete', 'unassigned_warehouse_supply',
            'wms_receipt_overlap_unresolved', 'dispatch_allocation_overallocated', 'shipment_receipt_overallocated',
            'overdue_eta', 'wms_allocation_requires_review'))
    submitted = Decimal(pipe['submitted_operating_demand']) if pipe.get('authorized') and pipe.get('submitted_operating_demand') is not None else None
    draft = Decimal(pipe['draft_reserved_demand']) if pipe.get('authorized') and pipe.get('draft_reserved_demand') is not None else None
    timeline = forecast_timeline(daily=daily, daily_ratio=exact_daily, today=today, lead_days=strategy.lead_days,
        cycle_days=strategy.cycle_days, safety_days=strategy.safety_days, stock=stock,
        eta_rows=pipe.get('eta_rows', []), activity_start=activity_start,
        activity_end=activity_end, activity_factor=activity_factor)
    incoming = timeline['target_incoming'] if supply_known else None
    gap, quantity = replenishment_quantities(timeline['target_stock'], stock, incoming, submitted, draft,
        target_ratio=timeline['target_stock_ratio'])
    return {'windows': windows, 'daily_values': daily_values, 'weights': weights, 'daily': daily,
        'sales_unknown': sales_unknown, 'stock': stock, 'supply_known': supply_known,
        'submitted': submitted, 'draft_reserved': draft, 'incoming': incoming,
        'timeline': timeline, 'gap': gap, 'suggested_quantity': quantity}


def _internal(actor):
    if not actor.is_active or actor.user_type != 'internal':
        raise PermissionDenied('仅内部业务账号可使用补货策略。')


def _scope_country_ids(actor, permission):
    scopes = get_permission_data_scopes(actor, permission)
    if actor.is_superuser or any(s['scope_type'] == DataScope.ScopeType.ALL for s in scopes):
        return None
    ids = set()
    for scope in scopes:
        if scope['scope_type'] != DataScope.ScopeType.CUSTOM:
            continue
        config = scope.get('config') or {}
        values = config.get('site_ids', config.get('country_ids', []))
        if isinstance(values, list):
            ids.update(int(value) for value in values if str(value).isdigit() and int(value) > 0)
    return ids


def _authorized_countries(actor, *, manage=False):
    _internal(actor)
    allowed_codes = []
    if manage:
        if not check_user_permission(actor, MANAGE):
            raise PermissionDenied('缺少供应链补货策略管理权限。')
        scopes = _scope_country_ids(actor, MANAGE)
        allowed_codes.append(None if scopes is None else scopes)
    else:
        if check_user_permission(actor, VIEW):
            scopes = _scope_country_ids(actor, VIEW)
            allowed_codes.append(None if scopes is None else scopes)
        if check_user_permission(actor, operating_domain.MANAGE):
            scopes = _scope_country_ids(actor, operating_domain.MANAGE)
            allowed_codes.append(None if scopes is None else scopes)
        if not allowed_codes:
            raise PermissionDenied('缺少采购查看或运营订货管理权限。')
    countries = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id, status='active')
    if not any(ids is None for ids in allowed_codes):
        union_ids = set().union(*(ids for ids in allowed_codes))
        countries = countries.filter(pk__in=union_ids)
    return countries.order_by('country_code', 'pk')


def _manageable_country_ids(actor):
    if not check_user_permission(actor, MANAGE):
        return set()
    return _scope_country_ids(actor, MANAGE)


def _country_option(country, manageable):
    return {'id': country.pk, 'name': country.name, 'country_code': country.country_code,
            'can_manage': manageable is None or country.pk in manageable}


def _country(actor, country_id, *, manage=False):
    country = _authorized_countries(actor, manage=manage).filter(pk=country_id).first()
    if not country:
        raise NotFound('国家不存在或不在当前业务数据范围内。')
    return country


def _strategy_json(row):
    return {'id': row.pk, 'country_id': row.country_id, 'name': row.name,
        'cycle_days': row.cycle_days, 'lead_days': row.lead_days, 'safety_days': row.safety_days,
        'sales_model': row.sales_model, 'sales_weights': row.sales_weights, 'active': row.active,
        'version': row.version, 'updated_at': row.updated_at.isoformat(), 'configured': True}


class StrategyInput(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=120)
    cycle_days = serializers.IntegerField(min_value=1, max_value=365)
    lead_days = serializers.IntegerField(min_value=1, max_value=365)
    safety_days = serializers.IntegerField(min_value=0, max_value=365)
    sales_model = serializers.ChoiceField(choices=('weighted', 'ordinary'), default='weighted')
    sales_weights = serializers.DictField(child=serializers.IntegerField(min_value=0, max_value=100), required=False)
    active = serializers.BooleanField(default=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)

    def validate(self, values):
        if sum(values[k] for k in ('cycle_days', 'lead_days', 'safety_days')) > 366:
            raise serializers.ValidationError('订货间隔、预计到仓和安全天数合计不能超过366天。')
        weights = values.get('sales_weights', DEFAULTS['sales_weights'])
        if values['sales_model'] == 'ordinary':
            weights = {'7': 0, '15': 0, '30': 100}
        elif set(weights) != {'7', '15', '30'} or sum(weights.values()) != 100:
            raise serializers.ValidationError({'sales_weights': '加权模型须提供7/15/30天权重且合计100%。'})
        values['sales_weights'] = {str(k): v for k, v in weights.items()}
        return values


class StrategyVersionConflict(APIException):
    status_code = 409
    default_detail = '补货策略已被其他人更新，请刷新后再保存。'
    default_code = 'strategy_version_conflict'


class ReferenceInput(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1)
    strategy_id = serializers.IntegerField(min_value=1, required=False)
    sales_end = serializers.DateField(required=False)
    source_kind = serializers.ChoiceField(choices=('cycle', 'season'), default='cycle')
    analysis_mode = serializers.ChoiceField(choices=('country', 'platform'), default='country')
    platform_type = serializers.CharField(max_length=80, allow_blank=True, default='')
    search = serializers.CharField(max_length=160, allow_blank=True, default='')
    quantity_filter = serializers.ChoiceField(choices=('positive', 'all', 'zero', 'unknown'), default='positive')
    limit = serializers.IntegerField(min_value=1, max_value=20, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    activity_start = serializers.DateField(required=False, allow_null=True)
    activity_end = serializers.DateField(required=False, allow_null=True)
    activity_factor = serializers.DecimalField(max_digits=8, decimal_places=4, min_value=Decimal('0.01'), max_value=Decimal('20'), default=Decimal('1'))
    exclude_operating_order_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, values):
        start, end = values.get('activity_start'), values.get('activity_end')
        if bool(start) != bool(end) or (start and end and start > end):
            raise serializers.ValidationError('活动开始、结束日期须同时填写，结束日期不能早于开始日期。')
        if values.get('source_kind') == 'season' and not start:
            raise serializers.ValidationError('季节订货必须填写活动开始和结束日期。')
        return values


class ReplenishmentStrategies(ReadAPI):
    def get(self, request):
        countries = _authorized_countries(request.user)
        manageable = _manageable_country_ids(request.user)
        country_id = request.query_params.get('country_id')
        if country_id:
            try:
                parsed_country_id = int(country_id)
            except (TypeError, ValueError):
                raise ValidationError({'country_id': '国家编号格式无效。'})
            country = _country(request.user, parsed_country_id)
            row = ReplenishmentStrategy.objects.filter(tenant_id=request.user.tenant_id, country=country).first()
            return Response({'data': {'countries': [_country_option(country, manageable)],
                'strategy': _strategy_json(row) if row else None, 'configured': bool(row),
                'proposed_defaults': DEFAULTS if not row else None,
                'can_manage': manageable is None or country.pk in manageable}})
        country_rows = list(countries)
        configured = {row.country_id: row for row in ReplenishmentStrategy.objects.filter(
            tenant_id=request.user.tenant_id, country_id__in=[c.pk for c in country_rows])}
        return Response({'data': {'countries': [_country_option(c, manageable) for c in country_rows],
            'strategies': [_strategy_json(configured[c.pk]) for c in country_rows if c.pk in configured],
            'proposed_defaults': DEFAULTS, 'can_manage': manageable is None or any(c.pk in manageable for c in country_rows)}})

    @transaction.atomic
    def put(self, request):
        values = validated(StrategyInput, request)
        services._tenant_lock(request.user)
        country = _country(request.user, values['country_id'], manage=True)
        row = ReplenishmentStrategy.objects.select_for_update().filter(tenant_id=request.user.tenant_id, country=country).first()
        if row and values.get('expected_version') != row.version:
            raise StrategyVersionConflict()
        if not row and values.get('expected_version') is not None:
            raise StrategyVersionConflict('此国家尚未配置补货策略，请刷新后再保存。')
        with domain_write():
            if row:
                row.version += 1
            else:
                row = ReplenishmentStrategy(tenant=request.user.tenant, created_by=request.user, country=country)
            for field in ('name', 'cycle_days', 'lead_days', 'safety_days', 'sales_model', 'sales_weights', 'active'):
                setattr(row, field, values[field])
            row.save()
        return Response({'data': _strategy_json(row)})


class ReplenishmentReferences(ReadAPI):
    def post(self, request):
        from apps.commerce import country_decisions

        trusted_chunk_ids = getattr(request, '_trusted_replenishment_chunk_ids', None)
        if trusted_chunk_ids is not None:
            serializer = ReferenceInput(data=request.data)
            serializer.is_valid(raise_exception=True)
            values = serializer.validated_data
        else:
            values = validated(ReferenceInput, request)
        actor = request.user
        country = _country(actor, values['country_id'])
        strategy_query = ReplenishmentStrategy.objects.filter(tenant_id=actor.tenant_id,
            country=country, active=True)
        if values.get('strategy_id'):
            strategy_query = strategy_query.filter(pk=values['strategy_id'])
        strategy = strategy_query.first()
        if not strategy:
            raise ValidationError('此国家尚未保存有效补货策略，请先在补货策略设置中保存参数。')
        sales_end = values.get('sales_end') or (business_date() - timedelta(days=1))
        if sales_end >= business_date():
            raise ValidationError('销量统计截止日须为已完成日期。')
        total_days = strategy.cycle_days + strategy.lead_days + strategy.safety_days
        if total_days > 366:
            raise ValidationError('策略覆盖天数不能超过366天。')
        platform_options = country_decisions.sales_platform_options(actor, country)
        selected_platform = values['platform_type'].strip()
        if values['analysis_mode'] == 'platform':
            if not selected_platform or selected_platform.casefold() not in {r['platform_type'].casefold() for r in platform_options}:
                raise ValidationError({'platform_type': '所选平台不在当前国家的授权活跃店铺范围内。'})
            selected_platform = next(r['platform_type'] for r in platform_options if r['platform_type'].casefold() == selected_platform.casefold())
        candidates = country_decisions.skus_for(actor, country).filter(
            is_active=True, spu__product_type='standard').exclude(inventory_type='virtual')
        if trusted_chunk_ids is not None:
            candidates = candidates.filter(pk__in=trusted_chunk_ids)
        term = values['search'].strip()
        if term:
            candidates = candidates.filter(Q(sku_code__icontains=term) | Q(legacy_sku_code__icontains=term) | Q(product_name__icontains=term))
        candidates = candidates.select_related('spu__category_node').order_by('sku_code', 'pk')
        count = candidates.count()
        skus = list(candidates[values['offset']:values['offset'] + values['limit']])
        weights = {'7': 0, '15': 0, '30': 100} if strategy.sales_model == 'ordinary' else strategy.sales_weights
        activities = []
        start, end = values.get('activity_start'), values.get('activity_end')
        factor = values['activity_factor']
        today = business_date()
        horizon_end = today + timedelta(days=total_days)
        if start and end < today:
            raise ValidationError('活动日期已结束，请选择当前或未来活动日期。')
        if start and start <= horizon_end and end >= today + timedelta(days=1):
            activities.append({'start': max(start, today + timedelta(days=1)), 'end': min(end, horizon_end), 'factor': factor})
        target_days = Decimal(total_days)
        if activities:
            event = activities[0]
            target_days += Decimal(max(0, (event['end'] - event['start']).days + 1)) * (event['factor'] - Decimal(1))
        exclude_order_id = values.get('exclude_operating_order_id')
        if exclude_order_id:
            from apps.sales_management.operating import order_for
            edited = order_for(actor, exclude_order_id)
            if edited.status != 'draft' or edited.country_id != country.pk:
                raise ValidationError('仅能在修改本国家运营订货草稿时排除本单预留量。')
        rows = country_decisions.decision_rows(actor, country, skus, target_days=total_days,
            window_days=30, end_date=sales_end, ratio=None, include_in_transit=True,
            windows=(7, 15, 30), exclude_order_id=exclude_order_id,
            demand_horizon_start=today + timedelta(days=1), demand_horizon_end=today + timedelta(days=total_days)) if skus else []
        platform_sales = {}
        if values['analysis_mode'] == 'platform' and skus:
            platform_sales = country_decisions.sales_windows(actor, country, [s.pk for s in skus],
                (7, 15, 30), end_date=sales_end, platform_type=selected_platform)
        output = []
        for row in rows:
            calculated = evaluate_replenishment_row(row, strategy, sales_end=sales_end,
                activity_start=(activities[0]['start'] if activities else None),
                activity_end=(activities[0]['end'] if activities else None), activity_factor=factor, today=today)
            windows = calculated['windows']; daily_values = calculated['daily_values']
            sales_unknown = calculated['sales_unknown']; forecast = calculated['daily']
            weights = calculated['weights']; pipe = row['pipeline']
            supply_known = calculated['supply_known']; stock = calculated['stock']
            submitted = calculated['submitted']; draft_reserved = calculated['draft_reserved']
            eta_rows = pipe.get('eta_rows', []); timeline = calculated['timeline']
            target_stock = timeline['target_stock']; incoming = calculated['incoming']
            gap = calculated['gap']; suggested = calculated['suggested_quantity']
            on_hand_days = timeline['on_hand_days']
            cover_days = ((stock + incoming) / forecast).quantize(Decimal('0.01')) if stock is not None and incoming is not None and forecast is not None and forecast > 0 else None
            eta_rows = sorted(eta_rows, key=lambda r: (r.get('expected_date') or '9999-99-99', r.get('batch_id') or 0))
            spu = next((s.spu for s in skus if s.pk == row['sku_id']), None)
            lifecycle = spu.lifecycle_status if spu else ''
            sales_status = spu.sales_status if spu else ''
            non_orderable = lifecycle == 'discontinued' or sales_status in {'paused', 'stopped', 'not_listed'}
            if non_orderable:
                suggested = 0 if suggested is not None else None
            issues = set(row['issues'])
            if sales_unknown or stock is None or not supply_known:
                risk = 'data_check'
            elif forecast == 0:
                risk = 'new_or_zero_sales'
            elif stock <= 0:
                risk = 'out_of_stock'
            elif timeline['arrival_gap']:
                risk = 'arrival_gap'
            elif timeline['needs_replenishment']:
                risk = 'replenish'
            else:
                risk = 'normal'
            evidence = {'daily_sales_formula': '普通日均=A30；加权日均=A7×w7+A15×w15+A30×w30',
                'sales': {str(d): {'units': windows[str(d)]['units'], 'daily_units': windows[str(d)]['daily_units'], 'weight': weights[str(d)]} for d in (7, 15, 30)},
                'target_days': str(target_days), 'target_stock': str(target_stock) if target_stock is not None else None,
                'reminder_stock': str(timeline['reminder_stock']) if timeline['reminder_stock'] is not None else None,
                'reminder_incoming': str(timeline['reminder_incoming']) if timeline['reminder_incoming'] is not None else None,
                'first_shortage_date': timeline['first_shortage_date'], 'needs_replenishment': timeline['needs_replenishment'],
                'arrival_gap': timeline['arrival_gap'],
                'available_stock': str(stock) if stock is not None else None, 'valid_incoming': str(incoming) if incoming is not None else None,
                'submitted_demand': str(submitted) if submitted is not None else None, 'draft_reserved_demand': str(draft_reserved) if draft_reserved is not None else None,
                'demand_horizon': pipe.get('demand_horizon'),
                'open_demand_basis': '覆盖期内日期重叠的未转采购需求；未填写需求日期的需求保守计入。',
                'needs_replenishment': timeline['needs_replenishment'],
                'recommendation_state': ('提醒线已触发' if timeline['needs_replenishment'] else
                    ('可提前备货参考' if suggested and suggested > 0 else '未触发')),
                'replenishment_gap': str(gap) if gap is not None else None, 'suggested_quantity': suggested,
                'formula': 'ceil(max(0, target_stock - available_stock - valid_incoming - submitted_demand - draft_reserved_demand))'}
            value = {**row, 'sku_code': row['sku'], 'forecast_daily_sales': str(forecast) if forecast is not None else None,
                'sales_trend_rate': (str((daily_values[7] - daily_values[30]) / daily_values[30]) if not sales_unknown and daily_values[30] > 0 else None),
                'on_hand_days': str(on_hand_days) if on_hand_days is not None else None,
                'supply_cover_days': str(cover_days) if cover_days is not None else None,
                'suggested_quantity': suggested, 'replenishment_gap': str(gap) if gap is not None else None,
                'submitted_demand': str(submitted) if submitted is not None else None,
                'draft_reserved_demand': str(draft_reserved) if draft_reserved is not None else None,
                'next_eta': eta_rows[0] if eta_rows else None, 'risk_level': 'manual_review' if non_orderable else risk,
                'product_status': f'{lifecycle or "unknown"}/{sales_status or "unknown"}',
                'formula_evidence': evidence, 'calculation_evidence': evidence,
                'needs_replenishment': timeline['needs_replenishment'],
                'recommendation_state': ('提醒线已触发' if timeline['needs_replenishment'] else
                    ('可提前备货参考' if suggested and suggested > 0 else '未触发')),
                'source_kind': values['source_kind'], 'issues': sorted(issues)}
            if values['analysis_mode'] == 'platform':
                value['platform_analysis'] = _platform_line(platform_sales, row['sku_id'], selected_platform, country, windows)
            output.append(value)
        qfilter = values['quantity_filter']
        if qfilter == 'positive': output = [r for r in output if r['suggested_quantity'] is not None and r['suggested_quantity'] > 0]
        elif qfilter == 'zero': output = [r for r in output if r['suggested_quantity'] == 0]
        elif qfilter == 'unknown': output = [r for r in output if r['suggested_quantity'] is None]
        notice = ('已使用国家授权的普通商品和组合组件销量。草稿预留量与已提交需求分开显示，均从新增建议量扣除；'
                  '采购供应按集货分配和预计到仓日期计量。数据或ETA缺失时建议量显示待核对。')
        return Response({'data': {'lines': output, 'count': count, 'candidate_count': count, 'limit': values['limit'],
            'offset': values['offset'], 'scanned_count': len(skus), 'next_offset': values['offset'] + len(skus),
            'has_more': values['offset'] + len(skus) < count, 'quantity_filter': qfilter,
            'analysis_mode': values['analysis_mode'], 'platform_options': platform_options,
            'parameters': {**_strategy_json(strategy), 'source_kind': values['source_kind'], 'sales_end': sales_end.isoformat(),
                'activity_start': str(start) if start else None, 'activity_end': str(end) if end else None,
                'activity_factor': str(factor), 'target_days': str(target_days)},
            'generated_at': timezone.now().isoformat(), 'formula': 'ceil(max(0,T-I-P-O-Q))；T=预测日需求合计，P=目标期有效到货，O=已提交未转采购，Q=草稿预留',
            'notice': notice}})


def _order_strategy_lines(actor, country, strategy, *, sku_ids, sales_end, source_kind,
                          activity_start=None, activity_end=None, activity_factor=Decimal(1),
                          exclude_order_id=None):
    """Bounded deterministic calculator shared by reference display and order preview validation."""
    from apps.commerce import country_decisions

    today = business_date()
    horizon = strategy.cycle_days + strategy.lead_days + strategy.safety_days
    skus = list(country_decisions.skus_for(actor, country).filter(pk__in=sku_ids)
        .select_related('spu__category_node').order_by('pk'))
    if len(skus) != len(sku_ids):
        raise ValidationError('商品不存在或不在当前国家库存商品授权范围内。')
    if any(s.inventory_type == 'virtual' or s.spu.product_type != 'standard' for s in skus):
        raise ValidationError('虚拟商品或非普通商品不能参与周期/季节订货。')
    windows = (7, 15, 30)
    rows = country_decisions.decision_rows(actor, country, skus,
        target_days=horizon,
        window_days=30, end_date=sales_end, ratio=None, include_in_transit=True,
        windows=windows, exclude_order_id=exclude_order_id,
        demand_horizon_start=today + timedelta(days=1), demand_horizon_end=today + timedelta(days=horizon))
    weights = {'7': 0, '15': 0, '30': 100} if strategy.sales_model == 'ordinary' else strategy.sales_weights
    factor = Decimal(activity_factor)
    event_start = max(activity_start, today + timedelta(days=1)) if activity_start else None
    event_end = min(activity_end, today + timedelta(days=horizon)) if activity_end else None
    if not event_start or not event_end or event_start > event_end:
        event_start = event_end = None
    signatures, output = [], []
    for row in rows:
        calculated = evaluate_replenishment_row(row, strategy, sales_end=sales_end,
            activity_start=event_start, activity_end=event_end, activity_factor=factor, today=today)
        by_days = calculated['windows']; daily_values = calculated['daily_values']; daily = calculated['daily']
        pipe = row['pipeline']; stock = calculated['stock']; supply_known = calculated['supply_known']
        submitted = calculated['submitted']; draft = calculated['draft_reserved']; incoming = calculated['incoming']
        timeline = calculated['timeline']; gap = calculated['gap']; quantity = calculated['suggested_quantity']
        unknown_sales = calculated['sales_unknown']; blocking = set(row.get('blocking_issues') or [])
        sku = next(s for s in skus if s.pk == row['sku_id'])
        non_orderable = sku.spu.lifecycle_status == 'discontinued' or sku.spu.sales_status in {'paused', 'stopped', 'not_listed'}
        if non_orderable:
            quantity = 0 if quantity is not None else None
        if unknown_sales or stock is None or not supply_known:
            risk = 'data_check'
        elif daily == 0:
            risk = 'new_or_zero_sales'
        elif stock <= 0:
            risk = 'out_of_stock'
        elif timeline['arrival_gap']:
            risk = 'arrival_gap'
        elif timeline['needs_replenishment']:
            risk = 'replenish'
        else:
            risk = 'normal'
        evidence = {'sales_model': strategy.sales_model, 'weights': weights,
            'sales_end': sales_end.isoformat(), 'forecast_daily_sales': str(daily) if daily is not None else None,
            'target_stock': str(timeline['target_stock']) if timeline['target_stock'] is not None else None,
            'reminder_stock': str(timeline['reminder_stock']) if timeline['reminder_stock'] is not None else None,
            'reminder_incoming': str(timeline['reminder_incoming']) if timeline['reminder_incoming'] is not None else None,
            'target_incoming': str(timeline['target_incoming']) if timeline['target_incoming'] is not None else None,
            'first_shortage_date': timeline['first_shortage_date'],
            'arrival_gap': timeline['arrival_gap'],
            'available_stock': str(stock) if stock is not None else None,
            'valid_incoming': str(incoming) if incoming is not None else None,
            'submitted_demand': str(submitted) if submitted is not None else None,
            'draft_reserved_demand': str(draft) if draft is not None else None,
            'demand_horizon': pipe.get('demand_horizon'),
            'open_demand_basis': '覆盖期内日期重叠的未转采购需求；未填写需求日期的需求保守计入。',
            'needs_replenishment': timeline['needs_replenishment'],
            'recommendation_state': ('提醒线已触发' if timeline['needs_replenishment'] else
                ('可提前备货参考' if quantity and quantity > 0 else '未触发')),
            'suggested_quantity': quantity, 'formula': 'ceil(max(0,T-I-P-O-Q))'}
        line = {'sku_id': row['sku_id'], 'sku': row['sku'], 'sku_code': row['sku'],
            'legacy_sku_code': row.get('legacy_sku_code', ''), 'product_name': row.get('product_name', ''),
            'product_details': row.get('product_details', {}), 'image_preview_url': row.get('image_preview_url', ''),
            'available_stock': str(stock) if stock is not None else None,
            'forecast_daily_sales': str(daily) if daily is not None else None,
            'sales_windows': row['sales_windows'], 'pipeline': pipe,
            'direct_sales_quantity': row.get('direct_sales_quantity'),
            'bundle_sales_quantity': row.get('bundle_sales_quantity'),
            'total_demand_quantity': row.get('total_demand_quantity'),
            'on_hand_days': str(timeline['on_hand_days']) if timeline['on_hand_days'] is not None else None,
            'submitted_demand': str(submitted) if submitted is not None else None,
            'draft_reserved_demand': str(draft) if draft is not None else None,
            'valid_incoming': str(incoming) if incoming is not None else None,
            'suggested_quantity': quantity, 'replenishment_gap': str(gap) if gap is not None else None,
            'needs_replenishment': timeline['needs_replenishment'],
            'recommendation_state': ('提醒线已触发' if timeline['needs_replenishment'] else
                ('可提前备货参考' if quantity and quantity > 0 else '未触发')),
            'risk_level': 'manual_review' if non_orderable else risk,
            'product_status': f'{sku.spu.lifecycle_status}/{sku.spu.sales_status}',
            'issues': sorted(set(row.get('issues') or []) | (set(pipe.get('issues') or []))),
            'formula_evidence': evidence, 'calculation_evidence': evidence,
            'next_eta': sorted(pipe.get('eta_rows', []), key=lambda r: r.get('expected_date') or '9999-99-99')[0]
                if pipe.get('eta_rows') else None}
        output.append(line)
        signatures.append({'sku_id': row['sku_id'], 'source_snapshot_ids': row.get('source_snapshot_ids'),
            'source_run_ids': row.get('source_run_ids'), 'available_stock': row.get('available_stock'),
            'inventory_complete': row.get('inventory_complete'), 'sales_windows': row.get('sales_windows'),
            'pipeline': pipe, 'issues': row.get('issues'), 'blocking_issues': row.get('blocking_issues')})
    from apps.supply_chain.services import request_hash
    return output, request_hash({'strategy_id': strategy.pk, 'strategy_version': strategy.version,
        'sales_end': sales_end, 'source_kind': source_kind, 'activity_start': activity_start,
        'activity_end': activity_end, 'activity_factor': factor, 'business_date': today,
        'demand_horizon': [today + timedelta(days=1), today + timedelta(days=horizon)],
        'rows': signatures}), country_decisions.permission_signature(actor)


def strategy_order_preview(actor, payload, key):
    from apps.sales_management.operating import _require, MANAGE, _country
    from apps.sales_management.operating_models import OperatingSuggestion
    from apps.supply_chain.services import request_hash

    _require(actor, MANAGE)
    services._tenant_lock(actor)
    country = _country(actor, payload['country_id'])
    strategy = ReplenishmentStrategy.objects.filter(tenant_id=actor.tenant_id, country=country,
        active=True).first()
    if not strategy or payload.get('strategy_id') not in (None, strategy.pk):
        raise ValidationError('国家补货策略尚未配置或已停用，请先保存有效策略。')
    sales_end = payload.get('sales_end') or (business_date() - timedelta(days=1))
    if sales_end >= business_date():
        raise ValidationError('销量统计截止日须为已完成日期。')
    start, end = payload.get('activity_start'), payload.get('activity_end')
    if payload['source_kind'] == 'season' and (not start or not end):
        raise ValidationError('季节订货必须填写活动日期。')
    if start and end < business_date():
        raise ValidationError('活动日期已结束，请选择当前或未来活动日期。')
    exclude_order_id = payload.get('exclude_operating_order_id')
    if exclude_order_id:
        from apps.sales_management.operating import order_for
        edited = order_for(actor, exclude_order_id)
        if edited.status != 'draft' or edited.country_id != country.pk:
            raise ValidationError('仅能在修改本国家运营订货草稿时排除本单预留量。')
    sku_ids = payload['sku_ids']
    if len(set(sku_ids)) != len(sku_ids):
        raise ValidationError('建议商品不能重复。')
    factor = payload.get('activity_factor', Decimal(1))
    lines, basis_signature, perm_signature = _order_strategy_lines(actor, country, strategy,
        sku_ids=sku_ids, sales_end=sales_end, source_kind=payload['source_kind'],
        activity_start=start, activity_end=end, activity_factor=factor,
        exclude_order_id=exclude_order_id)
    digest = request_hash(payload)
    token = request_hash({'actor': actor.pk, 'tenant': actor.tenant_id, 'key': services._key(key)})
    previous = OperatingSuggestion.objects.filter(token=token).first()
    if previous:
        if previous.snapshot.get('request_hash') != digest:
            raise ValidationError('建议幂等键不能用于不同输入。')
        validate_strategy_snapshot(actor, previous.snapshot)
        return {'preview_token': previous.token, **previous.snapshot}
    snapshot = {'demand_basis': 'weighted_replenishment_v1', 'algorithm_version': 'weighted_days_v1',
        'country_id': country.pk, 'strategy_id': strategy.pk, 'strategy_version': strategy.version,
        'source_kind': payload['source_kind'], 'sales_end': sales_end.isoformat(),
        'activity_start': start.isoformat() if start else None, 'activity_end': end.isoformat() if end else None,
        'activity_factor': str(factor), 'edited_order_id': exclude_order_id,
        'permission_signature': perm_signature, 'basis_signature': basis_signature,
        'open_demand_signature': (lines[0].get('pipeline') or {}).get('open_demand_signature') if lines else '',
        'request_hash': digest,
        'parameters': {'country_id': country.pk, 'sku_ids': list(sku_ids), 'strategy_id': strategy.pk,
            'source_kind': payload['source_kind'], 'sales_end': sales_end.isoformat(),
            'activity_start': start.isoformat() if start else None, 'activity_end': end.isoformat() if end else None,
            'activity_factor': str(factor), 'exclude_operating_order_id': exclude_order_id},
        'formula': 'ceil(max(0,T-I-P-O-Q))；T按日销量预测及活动系数逐日累加，P按ETA日期计入；缺数据则待核对。',
        'needs_review': True, 'generated_at': timezone.now().isoformat(), 'lines': lines}
    import json
    snapshot = json.loads(json.dumps(snapshot, default=str, ensure_ascii=False))
    with domain_write():
        suggestion = OperatingSuggestion.objects.create(tenant=actor.tenant, created_by=actor,
            country=country, token=token, snapshot=snapshot, expires_at=timezone.now() + timedelta(hours=2))
    return {'preview_token': suggestion.token, **snapshot}


def validate_strategy_snapshot(actor, snapshot, *, exclude_order_id=None):
    from apps.commerce.country_decisions import permission_signature

    strategy = ReplenishmentStrategy.objects.filter(tenant_id=actor.tenant_id,
        pk=snapshot.get('strategy_id'), country_id=snapshot.get('country_id'), active=True).first()
    if not strategy or strategy.version != snapshot.get('strategy_version'):
        raise ValidationError('补货策略已更新或停用，请重新计算建议。')
    if permission_signature(actor) != snapshot.get('permission_signature'):
        raise PermissionDenied('计算依据的数据授权已变化，请重新生成建议。')
    from apps.masterdata.models import CountrySiteMaster
    country = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id, pk=snapshot.get('country_id'), status='active').first()
    if not country:
        raise ValidationError('建议国家已不可用，请重新计算。')
    if exclude_order_id is None:
        exclude_order_id = snapshot.get('edited_order_id')
    lines, basis_signature, _ = _order_strategy_lines(actor, country, strategy,
        sku_ids=[line['sku_id'] for line in snapshot.get('lines', [])],
        sales_end=date.fromisoformat(snapshot['sales_end']), source_kind=snapshot['source_kind'],
        activity_start=date.fromisoformat(snapshot['activity_start']) if snapshot.get('activity_start') else None,
        activity_end=date.fromisoformat(snapshot['activity_end']) if snapshot.get('activity_end') else None,
        activity_factor=Decimal(snapshot.get('activity_factor') or '1'),
        exclude_order_id=exclude_order_id)
    if basis_signature != snapshot.get('basis_signature'):
        raise ValidationError('销量、库存、采购到货或运营需求依据已变化，请刷新建议后复核。')
    return lines


def _platform_line(platform_sales, sku_id, platform_type, country, windows):
    result = {}
    for days in (7, 15, 30):
        row = platform_sales[days]
        qty = row['units_by_sku'][sku_id]
        result[str(days)] = {'units': qty if row['coverage_complete'] and not row['unmapped'] else None,
            'daily_units': str(Decimal(qty) / Decimal(days)) if row['coverage_complete'] and not row['unmapped'] else None}
    return {'platform_type': platform_type, 'windows': result, 'contributes_to_suggestion': False}
