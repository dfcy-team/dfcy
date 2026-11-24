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
from apps.supply_chain.country_listing_evidence import country_listing_evidence
from apps.supply_chain.inventory_listing_risk import classify_country_risk
from apps.supply_chain.sales_archive_issues import sales_archive_issues
from apps.supply_chain.country_spu_summary import country_spu_summary
from apps.supply_chain.models import ReplenishmentStrategy, domain_write
from apps.supply_chain.permissions import MANAGE, VIEW
from apps.supply_chain.replenishment_math import _as_decimal, forecast_timeline
from apps.supply_chain.views import ReadAPI

DEFAULTS = {'cycle_days': 10, 'lead_days': 45, 'safety_days': 35,
            'sales_model': 'weighted', 'sales_weights': {'7': 50, '15': 30, '30': 20}}
STRATEGY_PERMISSION = 'supply.v2.manage'


def active_sales_days(weights):
    return tuple(day for day in (7, 15, 30) if Decimal(weights[str(day)]) != 0)


def weighted_daily_sales(daily_units, weights):
    days = active_sales_days(weights)
    if any(daily_units.get(day) is None for day in days):
        return None
    return sum((daily_units[day] * Decimal(weights[str(day)]) / Decimal(100) for day in days), Decimal(0))


def confirmed_reference_deductions(pipe, submitted, reserved):
    incoming = pipe.get('effective_incoming') if pipe.get('authorized') else None
    if set(pipe.get('issues', ())) & {'dispatch_allocation_overallocated', 'shipment_receipt_overallocated',
                                     'wms_allocation_requires_review', 'wms_receipt_overlap_unresolved'}:
        incoming = None
    if incoming is not None:
        incoming = Decimal(str(incoming)) + Decimal(str(pipe.get('unknown_eta') or 0))
    return {'confirmed_incoming': incoming, 'confirmed_submitted_demand': submitted,
            'confirmed_draft_reserved': reserved}


def restore_snapshot_suggestion(row):
    from .snapshot_payload import unpack_payload
    row = unpack_payload(row)
    reference = row.get('recognized_reference') or {}
    if not reference.get('has_observed_basis') or 'confirmed_deductions' in reference:
        return row
    target = reference.get('target_stock_reference')
    stock = reference.get('observed_available_stock')
    if target is None or stock is None:
        return row
    pipe = row.get('pipeline') or {}
    deductions = confirmed_reference_deductions(pipe, row.get('submitted_demand'), row.get('draft_reserved_demand'))
    net = Fraction(target) - Fraction(stock) - sum(
        (Fraction(value) for value in deductions.values() if value is not None), Fraction(0))
    return {**row, 'recognized_reference': {**reference,
        'quantity_reference': max(0, ceil(net)),
        'confirmed_deductions': {key: str(value) if value is not None else None for key, value in deductions.items()},
        'excluded_unknown_eta': 0}}


def recognized_reference(row, strategy, *, calculated, today, activity_start=None,
                         activity_end=None, activity_factor=Decimal(1)):
    """Show observed facts for an incomplete row without authorizing procurement."""
    if calculated['suggested_quantity'] is not None:
        return None
    weights = calculated['weights']
    windows = calculated['windows']
    days = active_sales_days(weights)
    units = {day: windows[str(day)].get('recognized_units') for day in days}
    warehouse_values = [Decimal(warehouse['available_qty']) for warehouse in row.get('warehouses', [])
                        if warehouse.get('available_qty') is not None]
    stock = calculated['stock']
    if stock is None and warehouse_values:
        stock = sum(warehouse_values, Decimal(0))
    daily = calculated['daily']
    target_ratio = calculated['timeline']['target_stock_ratio']
    target = Fraction(*target_ratio) if target_ratio is not None else None
    if daily is None and any(units.values()) and all(value is not None for value in units.values()):
        observed_daily = sum((Fraction(units[day]) * Fraction(Decimal(weights[str(day)]))
                              / (day * 100) for day in days), Fraction(0))
        daily = _as_decimal(observed_daily)
        horizon = strategy.lead_days + strategy.cycle_days + strategy.safety_days
        activity_days = 0
        if activity_start and activity_end:
            first = max(today + timedelta(days=1), activity_start)
            last = min(today + timedelta(days=horizon), activity_end)
            activity_days = max(0, (last - first).days + 1)
        target = observed_daily * (horizon + activity_days * (Fraction(activity_factor) - 1))
    scope_codes = {'unmapped_sales_lines', 'bundle_composition_unverified',
        'collection_coverage_unproven', 'no_authorized_sales_store',
        'invalid_store_timezone', 'unfinished_store_day', 'unmapped_inventory'}
    issues = set(row.get('issues', ())) | set(row.get('blocking_issues', ()))
    deductions = confirmed_reference_deductions(row['pipeline'], calculated['submitted'], calculated['draft_reserved'])
    deducted = sum((Fraction(value) for value in deductions.values() if value is not None), Fraction(0))
    gap = max(Fraction(0), target - Fraction(stock) - deducted) if target is not None and stock is not None else None
    return {'scope': 'recognized_skus_only', 'complete': False, 'can_create_order': False,
        'notice': '按已采集销量及已核验仓库库存展示。参考缺口扣除已确认的在途及订货占用，仅供核对。',
        'observed_sales_windows': {
            str(day): units[day] if units[day] or windows[str(day)]['coverage_complete'] else None
            for day in days
        },
        'forecast_daily_sales': str(daily) if daily is not None else None,
        'target_stock_reference': str(_as_decimal(target)) if target is not None else None,
        'observed_available_stock': str(stock) if stock is not None else None,
        'available_stock': str(stock) if stock is not None else None,
        'unresolved': (['库存完整性待核实'] if calculated['stock'] is None else [])
            + (['在途到货日期或供应数据待核实'] if not calculated['supply_known'] else []),
        'confirmed_deductions': {key: str(value) if value is not None else None for key, value in deductions.items()},
        'excluded_unknown_eta': '0',
        'quantity_reference': ceil(gap) if gap is not None else None,
        'scope_issues': sorted(issues & scope_codes),
        'item_issues': sorted(issues - scope_codes),
        'has_observed_basis': daily is not None and stock is not None}


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


def _replenishment_risk(*, unknown, forecast, stock, timeline):
    """Keep urgent arrival gaps distinct while surfacing every forecast shortage."""
    if unknown:
        return 'data_check'
    if forecast == 0:
        return 'new_or_zero_sales'
    if stock <= 0:
        return 'out_of_stock'
    if timeline['arrival_gap'] or timeline['first_shortage_date']:
        return 'arrival_gap'
    if timeline['needs_replenishment']:
        return 'replenish'
    return 'normal'


def _supply_action(timeline, suggested, decision=None):
    if decision is not None:
        if decision.get('requires_expedite'):
            return 'purchase_and_expedite' if suggested and suggested > 0 else 'expedite_or_transfer'
        return 'purchase' if suggested and suggested > 0 else None
    if suggested is None or not timeline['first_shortage_date']:
        return None
    return 'purchase_and_expedite' if suggested and suggested > 0 else 'expedite_or_transfer'


def evaluate_replenishment_row(row, strategy, *, sales_end, activity_start=None, activity_end=None,
                               activity_factor=Decimal(1), today=None):
    """One business decision for listing, order preview and save-time revalidation."""
    from apps.supply_chain.replenishment_decision import calculate_decision
    today = today or business_date()
    windows = {str(window['days']): window for window in row['sales_windows']}
    policies = getattr(strategy, 'sku_policies', {}) or {}
    policy = policies.get(str(row.get('sku_id')), {})
    mode = policy.get('mode', strategy.sales_model)
    weights = {'7': 0, '15': 0, '30': 100} if mode == 'ordinary' else strategy.sales_weights
    daily_values = {}
    for day in (7, 15, 30, 90):
        window = windows.get(str(day))
        if window is None:
            continue
        units = window.get('recognized_units', window.get('units'))
        if units is not None:
            daily_values[day] = Decimal(str(units)) / Decimal(day)
    days = active_sales_days(weights)
    ratio = None
    if mode == 'manual':
        manual = policy.get('manual_daily_sales')
        ratio = Fraction(Decimal(str(manual))) if manual is not None else None
    elif mode == 'low_frequency':
        ratio = Fraction(Decimal(str(windows['90'].get('recognized_units', windows['90'].get('units'))))) / 90 if 90 in daily_values else None
    elif all(day in daily_values for day in days):
        ratio = sum((Fraction(Decimal(str(windows[str(day)].get('recognized_units',
                          windows[str(day)].get('units'))))) * Fraction(Decimal(str(weights[str(day)])))
                      / (day * 100) for day in days), Fraction(0))
    observed_days = (90,) if mode == 'low_frequency' else days
    sales_complete = mode == 'manual' or all(
        windows.get(str(day), {}).get('coverage_complete', True) for day in observed_days
    )
    if ratio == 0 and not sales_complete:
        ratio = None
    daily = _as_decimal(ratio) if ratio is not None else None
    blocking = set(row.get('blocking_issues') or ())
    stock_complete = bool(row.get('inventory_complete')) and not blocking.intersection({
        'missing_inventory_snapshot', 'available_quantity_unverified', 'inventory_source_incomplete',
        'stale_inventory_snapshot', 'ambiguous_inventory_aliases', 'unmapped_inventory',
    })
    stock = Decimal(str(row['available_stock'])) if stock_complete and row['available_stock'] is not None else None
    pipe = row['pipeline']
    supply_known = bool(pipe.get('authorized')) and not pipe.get('received_awaiting_wms') and not any(
        issue in pipe.get('issues', ()) for issue in (
            'warehouse_supply_scope_incomplete', 'unassigned_warehouse_supply',
            'wms_receipt_overlap_unresolved', 'dispatch_allocation_overallocated',
            'shipment_receipt_overallocated', 'wms_allocation_requires_review',
        )
    )
    submitted = pipe.get('submitted_operating_demand') if pipe.get('authorized') else None
    draft = pipe.get('draft_reserved_demand') if pipe.get('authorized') else None
    submitted = Decimal(str(submitted)) if submitted is not None else None
    draft = Decimal(str(draft)) if draft is not None else None
    lead = policy.get('lead_days', strategy.lead_days)
    safety = policy.get('safety_days', strategy.safety_days)
    event_start = activity_start or (date.fromisoformat(policy['activity_start']) if policy.get('activity_start') else None)
    event_end = activity_end or (date.fromisoformat(policy['activity_end']) if policy.get('activity_end') else None)
    factor = activity_factor if activity_start else Decimal(str(policy.get('activity_factor', 1)))
    shipments = pipe.get('shipment_outstanding', pipe.get('eta_rows', []))
    production = pipe.get('production_unshipped') or 0
    if not shipments and 'shipment_outstanding' not in pipe:
        legacy_quantity = max(Decimal(0), Decimal(str(pipe.get('effective_incoming') or 0))
            + Decimal(str(pipe.get('unknown_eta') or 0)) - Decimal(str(production)))
        if legacy_quantity:
            shipments = [{'quantity': legacy_quantity, 'expected_date': None}]
    decision = calculate_decision(daily_sales=daily, daily_ratio=(ratio.numerator, ratio.denominator) if ratio is not None else None,
        available_stock=stock if supply_known and sales_complete else None, production_unshipped=production, shipment_rows=shipments,
        submitted_demand=submitted, draft_reserved=draft, today=today, lead_days=lead,
        cycle_days=strategy.cycle_days, safety_days=safety,
        purchase_multiple=policy.get('purchase_multiple', 1), carton_quantity=policy.get('carton_quantity', 1),
        minimum_order=policy.get('minimum_order', 0), activity_start=event_start,
        activity_end=event_end, activity_factor=factor)
    estimated_rows = []
    for shipment in shipments:
        raw = shipment.get('expected_date')
        expected = date.fromisoformat(raw) if isinstance(raw, str) else raw
        if expected is None or expected < today:
            expected = today + timedelta(days=lead)
        estimated_rows.append({**shipment, 'expected_date': expected})
    if production:
        estimated_rows.append({'expected_date': today + timedelta(days=lead), 'quantity': production})
    timeline = forecast_timeline(daily=daily, daily_ratio=ratio,
        today=today, lead_days=lead, cycle_days=strategy.cycle_days, safety_days=safety, stock=stock,
        eta_rows=estimated_rows, activity_start=event_start, activity_end=event_end, activity_factor=factor)
    incoming = sum((Decimal(str(item['quantity'])) for item in shipments), Decimal(0)) + Decimal(str(production))
    incoming = incoming if supply_known else None
    gap = max(Decimal(0), timeline['target_stock'] - stock - incoming) if daily is not None and stock is not None and incoming is not None else None
    return {'daily_ratio': (ratio.numerator, ratio.denominator) if ratio is not None else None, 'windows': windows, 'daily_values': daily_values, 'weights': weights, 'daily': daily,
        'sales_unknown': daily is None, 'stock': stock, 'supply_known': supply_known,
        'submitted': submitted, 'draft_reserved': draft, 'incoming': incoming,
        'timeline': timeline, 'gap': gap, 'suggested_quantity': decision['suggested_quantity'],
        'business_decision': decision, 'policy': policy, 'target_days': lead + strategy.cycle_days + safety}


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
        'sku_policies': row.sku_policies, 'version': row.version, 'updated_at': row.updated_at.isoformat(), 'configured': True}


class StrategyInput(serializers.Serializer):
    sku_policies = serializers.JSONField(required=False)
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
        if 'sku_policies' in values:
            from .replenishment_policy import validate_sku_policies
            values['sku_policies'] = validate_sku_policies(values['sku_policies'])
        for policy in values.get('sku_policies', {}).values():
            if policy.get('lead_days', values['lead_days']) + policy.get('safety_days', values['safety_days']) + values['cycle_days'] > 366:
                raise serializers.ValidationError({'sku_policies': '商品覆盖天数合计不能超过366天。'})
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
    analysis_mode = serializers.ChoiceField(choices=('country',), default='country')
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
        from .replenishment_policy import validate_sku_policies
        policies = values.get('sku_policies', row.sku_policies if row else {})
        policies = validate_sku_policies(policies, actor=request.user, country=country)
        for policy in policies.values():
            if policy.get('lead_days', values['lead_days']) + policy.get('safety_days', values['safety_days']) + values['cycle_days'] > 366:
                raise ValidationError({'sku_policies': '商品覆盖天数合计不能超过366天。'})
        with domain_write():
            if row:
                row.version += 1
            else:
                row = ReplenishmentStrategy(tenant=request.user.tenant, created_by=request.user, country=country)
            row.sku_policies = policies
            for field in ('name', 'cycle_days', 'lead_days', 'safety_days', 'sales_model', 'sales_weights', 'active'):
                setattr(row, field, values[field])
            row.save()
        return Response({'data': _strategy_json(row)})


def strategy_decision_rows(actor, country, skus, strategy, *, today, **kwargs):
    from collections import defaultdict
    from apps.commerce import country_decisions
    groups = defaultdict(list)
    policies = getattr(strategy, 'sku_policies', {}) or {}
    for sku in skus:
        policy = policies.get(str(sku.pk), {})
        horizon = strategy.cycle_days + policy.get('lead_days', strategy.lead_days) + policy.get('safety_days', strategy.safety_days)
        groups[horizon].append(sku)
    rows = []
    for horizon, members in groups.items():
        params = {**kwargs, 'target_days': horizon,
                  'demand_horizon_start': today + timedelta(days=1),
                  'demand_horizon_end': today + timedelta(days=horizon)}
        rows.extend(country_decisions.decision_rows(actor, country, members, **params))
    return rows


class ReplenishmentReferences(ReadAPI):
    def post(self, request):
        from apps.commerce import country_decisions

        trusted_chunk_ids = getattr(request, '_trusted_replenishment_chunk_ids', None)
        if trusted_chunk_ids is not None:
            serializer = ReferenceInput(data=request.data)
            serializer.is_valid(raise_exception=True)
            values = serializer.validated_data
            internal_batch = getattr(request, '_trusted_replenishment_batch_size', 20)
            if not isinstance(internal_batch, int) or not 1 <= internal_batch <= 1000 or len(trusted_chunk_ids) > internal_batch:
                raise ValidationError('内部补货计算批量参数无效。')
            values['limit'] = internal_batch
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
            is_active=True, product_type='standard').exclude(inventory_type='virtual')
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
        today = (getattr(request, '_trusted_replenishment_business_day', None) if trusted_chunk_ids is not None else None) or business_date()
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
        rows = strategy_decision_rows(actor, country, skus, strategy, today=today, target_days=total_days,
            window_days=30, end_date=sales_end, ratio=None, include_in_transit=True,
            windows=(7, 15, 30, 90), exclude_order_id=exclude_order_id,
            demand_horizon_start=today + timedelta(days=1), demand_horizon_end=today + timedelta(days=total_days),
            platform_type=selected_platform if values["analysis_mode"] == "platform" else None) if skus else []
        listing_evidence = country_listing_evidence(actor, country.country_code, skus)
        archive_issues = sales_archive_issues(actor=actor, country=country, end_date=sales_end,
            platform_type=selected_platform if values["analysis_mode"] == "platform" else None)
        spu_summaries = country_spu_summary(actor, country, skus)
        output = []
        sku_by_id = {sku.pk: sku for sku in skus}
        for row in rows:
            calculated = evaluate_replenishment_row(row, strategy, sales_end=sales_end,
                activity_start=start,
                activity_end=end, activity_factor=factor, today=today)
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
            sku = sku_by_id[row['sku_id']]
            spu = sku.spu
            lifecycle = spu.lifecycle_status if spu else ''
            sales_status = spu.sales_status if spu else ''
            non_orderable = lifecycle == 'discontinued' or sales_status in {'paused', 'stopped', 'not_listed'}
            country_risk = classify_country_risk(on_hand_qty=(Decimal(str(row["on_hand_stock"])) if row.get("on_hand_stock") is not None else None),
                in_transit_qty=Decimal(str(row.get("wms_in_transit_stock") or 0)),
                available_qty=stock, inventory_known=stock is not None,
                inventory_type=sku.inventory_type, listing_states=listing_evidence.get(sku.pk, ()),
                has_mapping=bool(listing_evidence.get(sku.pk)))
            row = {**row, 'country_inventory_status': country_risk}
            if non_orderable:
                suggested = 0
                calculated['business_decision'].update(category='inactive', suggested_quantity=0, can_order=False)
            issues = set(row['issues'])
            decision = calculated['business_decision']
            risk = ('arrival_gap' if decision.get('requires_expedite') else
                    {'purchase': 'replenish', 'no_sales': 'new_or_zero_sales',
                     'sufficient': 'normal', 'hidden': 'normal', 'unavailable': 'data_check'}.get(decision['category'], 'normal'))
            supply_action = _supply_action(timeline, suggested, calculated['business_decision'])
            evidence = {'daily_sales_formula': '普通日均=A30；加权日均=A7×w7+A15×w15+A30×w30',
                'sales': {str(d): {'units': windows[str(d)].get('recognized_units', windows[str(d)]['units']), 'daily_units': str(daily_values[d]) if d in daily_values else None, 'weight': weights[str(d)]} for d in (7, 15, 30)},
                'target_days': str(calculated['target_days']), 'target_stock': str(target_stock) if target_stock is not None else None,
                'reminder_stock': str(timeline['reminder_stock']) if timeline['reminder_stock'] is not None else None,
                'reminder_incoming': str(timeline['reminder_incoming']) if timeline['reminder_incoming'] is not None else None,
                'first_shortage_date': timeline['first_shortage_date'], 'supply_action': supply_action,
                'needs_replenishment': timeline['needs_replenishment'],
                'arrival_gap': timeline['arrival_gap'],
                'available_stock': str(stock) if stock is not None else None, 'valid_incoming': str(incoming) if incoming is not None else None,
                'submitted_demand': str(submitted) if submitted is not None else None, 'draft_reserved_demand': str(draft_reserved) if draft_reserved is not None else None,
                'demand_horizon': pipe.get('demand_horizon'),
                'open_demand_basis': '覆盖期内日期重叠的未转采购需求；未填写需求日期的需求保守计入。',
                'needs_replenishment': timeline['needs_replenishment'], 'supply_action': supply_action,
                'recommendation_state': ('提醒线已触发' if timeline['needs_replenishment'] else
                    ('可提前备货参考' if suggested and suggested > 0 else '未触发')),
                'replenishment_gap': str(gap) if gap is not None else None, 'suggested_quantity': suggested,
                'formula': 'ceil(max(0, target_stock - available_stock - valid_incoming - submitted_demand - draft_reserved_demand))'}
            value = {**row, 'available_stock': str(stock) if stock is not None else None, 'business_decision': calculated['business_decision'], 'sales_archive_issues': archive_issues, 'country_spu_summary': spu_summaries.get(sku.spu_id), 'recognized_reference': recognized_reference(row, strategy, calculated=calculated, today=today, activity_start=start, activity_end=end, activity_factor=factor), 'sku_code': row['sku'], 'forecast_daily_sales': str(forecast) if forecast is not None else None,
                'sales_trend_rate': (str((daily_values[7] - daily_values[30]) / daily_values[30]) if not sales_unknown and 7 in daily_values and daily_values.get(30, 0) > 0 else None),
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
                value['platform_analysis'] = {'platform_type': selected_platform, 'windows': {str(w['days']): {'units': w['units'], 'daily_units': w['daily_units']} for w in row['sales_windows']}, 'contributes_to_suggestion': True, 'shared_country_inventory': True, 'additive': False, 'notice': '按该平台自身销量计算；使用国家共享库存参考，各平台建议不可直接相加。'}
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
            'notice': '建议按已有销量、库存及供应计算；点击计算依据查看取整和扣减。'}})


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
    if any(s.inventory_type == 'virtual' or s.product_type != 'standard' for s in skus):
        raise ValidationError('虚拟商品或非普通商品不能参与周期/季节订货。')
    windows = (7, 15, 30, 90)
    rows = strategy_decision_rows(actor, country, skus, strategy, today=today,
        target_days=horizon,
        window_days=30, end_date=sales_end, ratio=None, include_in_transit=True,
        windows=windows, exclude_order_id=exclude_order_id,
        demand_horizon_start=today + timedelta(days=1), demand_horizon_end=today + timedelta(days=horizon))
    weights = {'7': 0, '15': 0, '30': 100} if strategy.sales_model == 'ordinary' else strategy.sales_weights
    factor = Decimal(activity_factor)
    event_start = max(activity_start, today + timedelta(days=1)) if activity_start else None
    event_end = activity_end
    if not event_start or not event_end or event_start > event_end:
        event_start = event_end = None
    listing_evidence = country_listing_evidence(actor, country.country_code, skus)
    archive_issues = sales_archive_issues(actor=actor, country=country, end_date=sales_end)
    spu_summaries = country_spu_summary(actor, country, skus)
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
        country_risk = classify_country_risk(on_hand_qty=(Decimal(str(row["on_hand_stock"])) if row.get("on_hand_stock") is not None else None),
                in_transit_qty=Decimal(str(row.get("wms_in_transit_stock") or 0)),
                available_qty=stock, inventory_known=stock is not None,
            inventory_type=sku.inventory_type, listing_states=listing_evidence.get(sku.pk, ()),
            has_mapping=bool(listing_evidence.get(sku.pk)))
        row = {**row, 'country_inventory_status': country_risk}
        if non_orderable:
            quantity = 0
            calculated['business_decision'].update(category='inactive', suggested_quantity=0, can_order=False)
        decision = calculated['business_decision']
        risk = ('arrival_gap' if decision.get('requires_expedite') else
                {'purchase': 'replenish', 'no_sales': 'new_or_zero_sales',
                 'sufficient': 'normal', 'hidden': 'normal', 'unavailable': 'data_check'}.get(decision['category'], 'normal'))
        supply_action = _supply_action(timeline, quantity, calculated['business_decision'])
        evidence = {'target_days': calculated['target_days'], 'sales_model': calculated['policy'].get('mode', strategy.sales_model), 'weights': calculated['weights'],
            'sales_end': sales_end.isoformat(), 'forecast_daily_sales': str(daily) if daily is not None else None,
            'target_stock': str(timeline['target_stock']) if timeline['target_stock'] is not None else None,
            'reminder_stock': str(timeline['reminder_stock']) if timeline['reminder_stock'] is not None else None,
            'reminder_incoming': str(timeline['reminder_incoming']) if timeline['reminder_incoming'] is not None else None,
            'target_incoming': str(timeline['target_incoming']) if timeline['target_incoming'] is not None else None,
            'first_shortage_date': timeline['first_shortage_date'], 'supply_action': supply_action,
            'arrival_gap': timeline['arrival_gap'],
            'available_stock': str(stock) if stock is not None else None,
            'valid_incoming': str(incoming) if incoming is not None else None,
            'submitted_demand': str(submitted) if submitted is not None else None,
            'draft_reserved_demand': str(draft) if draft is not None else None,
            'demand_horizon': pipe.get('demand_horizon'),
            'open_demand_basis': '覆盖期内日期重叠的未转采购需求；未填写需求日期的需求保守计入。',
            'needs_replenishment': timeline['needs_replenishment'], 'supply_action': supply_action,
            'recommendation_state': ('提醒线已触发' if timeline['needs_replenishment'] else
                ('可提前备货参考' if quantity and quantity > 0 else '未触发')),
            'suggested_quantity': quantity, 'formula': 'ceil(max(0,目标备货－可售库存－采购未发货－发货在途－已提交需求－草稿预留))，再按采购倍数、装箱数和起订量取整'}
        line = {'business_decision': calculated['business_decision'], 'sales_archive_issues': archive_issues, 'country_spu_summary': spu_summaries.get(sku.spu_id), 'recognized_reference': recognized_reference(row, strategy, calculated=calculated, today=today, activity_start=event_start, activity_end=event_end, activity_factor=factor), 'country_inventory_status': country_risk, 'sku_id': row['sku_id'], 'sku': row['sku'], 'sku_code': row['sku'],
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
            'needs_replenishment': timeline['needs_replenishment'], 'supply_action': supply_action,
            'recommendation_state': ('提醒线已触发' if timeline['needs_replenishment'] else
                ('可提前备货参考' if quantity and quantity > 0 else '未触发')),
            'risk_level': 'manual_review' if non_orderable else risk,
            'product_status': f'{sku.spu.lifecycle_status}/{sku.spu.sales_status}',
            'issues': sorted(set(row.get('issues') or []) | (set(pipe.get('issues') or []))),
            'formula_evidence': evidence, 'calculation_evidence': evidence,
            'next_eta': sorted(pipe.get('eta_rows', []), key=lambda r: r.get('expected_date') or '9999-99-99')[0]
                if pipe.get('eta_rows') else None}
        output.append(line)
        signatures.append({'country_listing_evidence': sorted(listing_evidence.get(sku.pk, ())), 'country_inventory_status': country_risk, 'master_status': [sku.spu.lifecycle_status, sku.spu.sales_status], 'sku_id': row['sku_id'], 'source_snapshot_ids': row.get('source_snapshot_ids'),
            'source_run_ids': row.get('source_run_ids'), 'available_stock': row.get('available_stock'),
            'inventory_complete': row.get('inventory_complete'), 'sales_windows': row.get('sales_windows'),
            'pipeline': pipe, 'issues': row.get('issues'), 'blocking_issues': row.get('blocking_issues')})
    from apps.supply_chain.services import request_hash
    return output, request_hash({'strategy_id': strategy.pk, 'strategy_version': strategy.version, 'sku_policies': getattr(strategy, 'sku_policies', {}),
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
