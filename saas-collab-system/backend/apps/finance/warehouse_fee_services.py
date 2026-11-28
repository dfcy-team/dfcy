"""Warehouse billing facts only: no payments, platform clients, or order updates."""
import hashlib
import json
from decimal import Decimal, localcontext, ROUND_HALF_UP

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.commerce.models import SalesOrder
from apps.common.exceptions import StateConflict
from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from .models import FinanceAuditLog
from .warehouse_fee_models import WarehouseFee

PREFIX = 'finance.warehouse_fees.'
CURRENCIES = ['CNY', 'PHP', 'THB', 'MYR', 'USD', 'SGD', 'HKD', 'EUR', 'BRL', 'TWD', 'IDR', 'VND', 'JPY', 'KRW']
FIELDS = ['kind', 'country', 'warehouse_id', 'store_id', 'external_order_id', 'bill_number', 'bill_month',
          'fee_item', 'reference', 'amount', 'currency', 'original_amount', 'original_currency',
          'exchange_rate', 'rate_date', 'rate_source', 'occurred_on', 'note']
EDIT_FIELDS = {'amount', 'currency', 'original_amount', 'original_currency', 'exchange_rate',
               'rate_date', 'rate_source', 'occurred_on', 'note'}


def hash_value(value):
    return hashlib.sha256(json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require(user, action):
    if not user.is_active or user.user_type != 'internal' or not check_user_permission(user, PREFIX + action):
        raise PermissionDenied('没有当前处理费操作权限。')


def scope_configs(user, action):
    require(user, action)
    scopes = get_permission_data_scopes(user, PREFIX + action)
    if any(s['scope_type'] == 'all' for s in scopes):
        return None
    configs = []
    allowed = {'store_ids', 'warehouse_ids', 'site_ids', 'regions', 'platforms', 'currencies'}
    for scope in scopes:
        cfg = scope.get('config') or {}
        if scope['scope_type'] != 'custom' or not cfg or set(cfg) - allowed:
            continue
        if any(not isinstance(v, list) or not v for v in cfg.values()):
            continue
        branch = {k: list(v) for k, v in cfg.items()}
        if 'site_ids' in branch:
            branch['site_countries'] = list(CountrySiteMaster.objects.filter(
                tenant=user.tenant, pk__in=branch.pop('site_ids')).values_list('country_code', flat=True))
        configs.append(branch)
    return configs


def scoped(user, action='view'):
    qs = WarehouseFee.objects.filter(tenant=user.tenant)
    configs = scope_configs(user, action)
    if configs is None:
        return qs
    allowed = Q(pk__in=[])
    fields = {'store_ids': 'store_id', 'warehouse_ids': 'warehouse_id', 'site_countries': 'country',
              'regions': 'country', 'platforms': 'store__platform__platform_type', 'currencies': 'currency'}
    for cfg in configs:
        branch = Q()
        for key, values in cfg.items():
            branch &= Q(**{fields[key] + '__in': values})
        allowed |= branch
    return qs.filter(allowed)


def values_allowed(user, action, values, store):
    configs = scope_configs(user, action)
    if configs is None:
        return True
    dimensions = {'store_ids': values.get('store_id'), 'warehouse_ids': values['warehouse_id'],
                  'regions': values['country'], 'site_countries': values['country'],
                  'platforms': store.platform.platform_type if store else None, 'currencies': values['currency']}
    return any(all(str(dimensions[k]) in {str(v) for v in allowed} for k, allowed in cfg.items()) for cfg in configs)


class FeeInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['order', 'other'])
    country = serializers.RegexField(r'^[A-Z]{2}$')
    warehouse_id = serializers.IntegerField(min_value=1, allow_null=True)
    store_id = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    external_order_id = serializers.CharField(max_length=191, required=False, allow_blank=True, default='')
    bill_number = serializers.CharField(max_length=191)
    bill_month = serializers.RegexField(r'^\d{4}-(0[1-9]|1[0-2])$')
    fee_item = serializers.CharField(max_length=80)
    reference = serializers.CharField(max_length=191)
    amount = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal('0.000001'))
    currency = serializers.ChoiceField(choices=CURRENCIES)
    original_amount = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal('0.000001'), required=False, allow_null=True, default=None)
    original_currency = serializers.ChoiceField(choices=['', *CURRENCIES], required=False, default='')
    exchange_rate = serializers.DecimalField(max_digits=24, decimal_places=10, min_value=Decimal('0.0000000001'), required=False, allow_null=True, default=None)
    rate_date = serializers.DateField(required=False, allow_null=True, default=None)
    rate_source = serializers.CharField(max_length=191, required=False, allow_blank=True, default='')
    occurred_on = serializers.DateField(required=False, allow_null=True, default=None)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.context.get('settlement_adjustment'):
            self.fields['amount'] = serializers.DecimalField(max_digits=20, decimal_places=6)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(FIELDS):
            raise ValidationError({'non_field_errors': ['包含未支持字段。']})
        if 'external_order_id' in data and not isinstance(data['external_order_id'], str):
            raise ValidationError({'external_order_id': '订单号必须为文本。'})
        return super().to_internal_value(data)

    def validate(self, value):
        adjustment = self.context.get('settlement_adjustment') and value['kind'] == 'other'
        if not adjustment and (value['warehouse_id'] is None or value['amount'] <= 0):
            raise ValidationError('普通处理费须指定仓库，且金额必须大于0；结算差额由账单统一计算。')
        if value['kind'] == 'order' and (not value['external_order_id'] or
                (not value['store_id'] and not self.context.get('allow_unmatched'))):
            raise ValidationError('订单处理费必须填写店铺和平台订单号。')
        if value['kind'] == 'other' and (value['store_id'] or value['external_order_id']):
            raise ValidationError('仓库其他处理费归属国家，不填写店铺或订单。')
        if value['original_amount'] is not None:
            if not value['original_currency'] or not value['exchange_rate'] or not value['rate_date'] or not value['rate_source']:
                raise ValidationError('填写原币金额时，须同时填写原币、兑换汇率、汇率日期及来源；1原币=汇率×结算币。')
            with localcontext() as context:
                context.prec = 50
                converted = (value['original_amount'] * value['exchange_rate']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if converted != value['amount'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):
                raise ValidationError('原币金额乘兑换汇率与结算金额不一致。')
        elif value['original_currency'] or value['exchange_rate'] is not None or value['rate_date'] or value['rate_source']:
            raise ValidationError('原币金额与换汇信息必须一并填写或全部留空。')
        return value


def validate_input(user, data, action, *, allow_unmatched=False):
    serializer = FeeInput(data=data, context={'allow_unmatched': allow_unmatched})
    serializer.is_valid(raise_exception=True)
    value = dict(serializer.validated_data)
    country = value['country']
    if not CountrySiteMaster.objects.filter(tenant=user.tenant, country_code=country).exists():
        raise ValidationError({'country': '国家不在当前租户档案中。'})
    warehouse = WarehouseMaster.objects.filter(tenant=user.tenant, pk=value['warehouse_id'], country_code=country).first()
    if not warehouse:
        raise ValidationError({'warehouse_id': '仓库不存在、不属于当前租户或国家不一致。'})
    store = None
    if value['store_id']:
        store = StoreMaster.objects.select_related('platform').filter(tenant=user.tenant, pk=value['store_id'], country_code=country).first()
        if not store:
            raise ValidationError({'store_id': '店铺不存在、不属于当前租户或国家不一致。'})
    if not values_allowed(user, action, value, store):
        raise PermissionDenied('费用不在当前授权的国家、仓库、店铺或币种范围内。')
    key = hash_value([value[k] for k in ['kind', 'country', 'warehouse_id', 'store_id', 'bill_number',
                    'bill_month', 'external_order_id', 'fee_item', 'reference']])
    return value, key


def match_order(user, value):
    if value['kind'] == 'other':
        return None, 'not_applicable'
    ids = list(SalesOrder.objects.filter(tenant=user.tenant, store_id=value['store_id'],
        external_order_id=value['external_order_id']).values_list('pk', flat=True)[:2])
    return (ids[0], 'matched') if len(ids) == 1 else (None, 'ambiguous' if ids else 'unmatched')


def content(row):
    return {field: getattr(row, field) for field in FIELDS}


def representation(row, *, audit=False):
    value = {**content(row), 'id': row.pk, 'order_id': row.order_id, 'status': row.status,
             'match_status': row.match_status, 'version': row.version, 'source': row.source,
             'store_code': row.store.code if row.store_id else '', 'warehouse_code': row.warehouse.code if row.warehouse_id else '待分配',
             'created_by': row.created_by_id, 'created_at': row.created_at, 'updated_at': row.updated_at}
    # Stable textual decimals prevent browser floating point from changing fee facts.
    for field in ['amount', 'original_amount', 'exchange_rate']:
        value[field] = str(value[field]) if value[field] is not None else None
    if audit:
        value['possible_duplicate_count'] = WarehouseFee.objects.filter(tenant=row.tenant, warehouse=row.warehouse,
            kind=row.kind, bill_number=row.bill_number, bill_month=row.bill_month, store_id=row.store_id,
            external_order_id=row.external_order_id, fee_item=row.fee_item, currency=row.currency).exclude(pk=row.pk).exclude(status='void').count()
        value['audit'] = [{'id': event.pk, 'action': event.action, 'detail': event.masked_detail,
                           'actor': event.actor_id, 'created_at': event.created_at}
                          for event in FinanceAuditLog.objects.filter(tenant=row.tenant, object_type='warehouse_fee', object_id=str(row.pk)).order_by('id')]
    return value


def log(row, user, action, before=None, reason=''):
    detail = json.loads(json.dumps({'before': before, 'after': representation(row), 'reason': reason}, cls=DjangoJSONEncoder))
    FinanceAuditLog.objects.create(tenant=row.tenant, actor=user, object_type='warehouse_fee',
        object_id=str(row.pk), action=action, masked_detail=detail)


@transaction.atomic
def create_fee(user, data, *, action='create', source=None, preview=False):
    from .warehouse_fee_registration import simple_source
    simple = simple_source(source)
    value, key = validate_input(user, data, action, allow_unmatched=simple)
    if simple:
        key = hash_value(['cny_simple', *(value[k] for k in ['kind', 'country', 'warehouse_id', 'bill_month', 'reference'])])
    if value['reference'].startswith('SETTLEMENT:'):
        raise ValidationError('结算差额编号由原账单统一维护，不能手动新增。')
    if source and source.get('type') == 'warehouse_original_xlsx' and source.get('sha256'):
        if WarehouseFee.objects.filter(tenant=user.tenant, source__sha256=source['sha256']).exclude(
                bill_number=value['bill_number']).exclude(status='void').exists():
            raise ValidationError('同一原账单已按其他名称登记，不能改名后重复导入。')
    WarehouseMaster.objects.select_for_update().get(pk=value['warehouse_id'], tenant=user.tenant)
    existing = WarehouseFee.objects.filter(tenant=user.tenant, business_key=key).select_related('store', 'warehouse').first()
    if existing:
        if existing.content_hash != hash_value(value) or existing.status == 'void':
            raise StateConflict('该费用已登记但内容不同或已作废，请核对原记录，不重复新增。')
        if not scoped(user, action).filter(pk=existing.pk).exists():
            raise PermissionDenied('已有费用不在当前权限范围内。')
        return existing, False
    order_id, match_status = match_order(user, value)
    if simple and source.get('matching', {}).get('status') == 'ambiguous':
        match_status = 'ambiguous'
    if not simple and value['kind'] == 'order' and match_status != 'matched' and (
            action == 'import' or source and source.get('type') == 'warehouse_original_xlsx'):
        raise ValidationError('订单处理费必须唯一关联本地销售订单；未关联或有歧义的记录保留待核对，不导入。')
    if preview:
        return WarehouseFee(tenant=user.tenant, **value, order_id=order_id, match_status=match_status), True
    row = WarehouseFee.objects.create(tenant=user.tenant, **value, order_id=order_id, match_status=match_status,
        business_key=key, content_hash=hash_value(value), source=source or {'type': 'manual'}, created_by=user)
    log(row, user, 'create')
    return row, True


@transaction.atomic
def operate(user, pk, operation, expected_version, *, changes=None, reason=''):
    if not isinstance(reason, str) or len(reason) > 500:
        raise ValidationError('操作原因必须为不超过500字符的文本。')
    permission = {'register': 'register', 'void': 'void', 'correct': 'edit', 'edit': 'edit', 'link': 'edit'}[operation]
    require(user, permission)
    from apps.tenants.models import Tenant
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    try:
        row = scoped(user, permission).select_for_update().select_related('store', 'warehouse').get(pk=pk)
    except WarehouseFee.DoesNotExist:
        raise NotFound('处理费不存在或不在授权范围。') from None
    if type(expected_version) is not int or expected_version != row.version:
        raise StateConflict('费用版本已变化，请刷新后重新核对。')
    before = representation(row)
    from .warehouse_fee_registration import simple_source, resolve_number
    simple = simple_source(row.source)
    from .warehouse_bill_settlement import managed, refresh_for_fee
    if managed(row.source):
        raise ValidationError('结算差额由账单统一重算，不能作为独立费用编辑或作废。')
    if row.source.get('type') == 'warehouse_file_supplement' and operation != 'register':
        raise ValidationError('原文件补差依据不可直接编辑或作废，请核对原文件版本。')
    if operation in {'correct', 'edit'}:
        required_status = 'registered' if operation == 'correct' else 'draft'
        if row.status != required_status:
            raise StateConflict('当前状态不能执行此修改。')
        if operation == 'correct' and not str(reason).strip():
            raise ValidationError('请填写更正原因。')
        if not isinstance(changes, dict) or not changes or set(changes) - EDIT_FIELDS:
            raise ValidationError('只能修改金额、结算币种、日期、换汇信息和备注。')
        if simple or row.source.get('registration_mode') in {'cny_original_v1','file_settlement_v2'}:
            if set(changes) - {'amount', 'occurred_on', 'note'}:
                raise ValidationError('本批登记固定使用CNY，只能调整金额、日期和备注。')
            if 'amount' in changes and not reason.strip():
                raise ValidationError('调整金额须填写原因，原登记金额会保留。')
        value, _ = validate_input(user, {**content(row), **changes}, permission, allow_unmatched=simple)
        for key, value_part in value.items():
            setattr(row, key, value_part)
        row.content_hash = hash_value(value)
    elif operation == 'register':
        from .warehouse_file_registration import registration_guard
        registration_guard(user, row)
        if row.status != 'draft':
            raise StateConflict('只能确认草稿费用；已登记不代表已付款。')
        validate_input(user, content(row), permission, allow_unmatched=simple)
        row.status = 'registered'
    elif operation == 'void':
        if row.status != 'registered' or not str(reason).strip():
            raise ValidationError('只能作废已登记费用，且须填写原因。')
        row.status = 'void'
    elif operation == 'link':
        if row.kind != 'order' or row.status == 'void':
            raise StateConflict('当前费用不能关联订单。')
        if simple:
            value = content(row)
            row.order_id, row.match_status = resolve_number(user, value, row.source)
            validate_input(user, value, permission, allow_unmatched=True)
            row.store_id, row.external_order_id = value['store_id'], value['external_order_id']
            row.content_hash = hash_value(value)
        else:
            row.order_id, row.match_status = match_order(user, content(row))
    if row.status == 'registered' and row.kind == 'order':
        row.order_id, row.match_status = match_order(user, content(row))
        if row.match_status != 'matched':
            raise ValidationError('订单处理费必须唯一关联本地销售订单；未关联或有歧义的记录保留待核对，不能登记。')
    row.version += 1
    row.save()
    log(row, user, operation, before, str(reason)[:500])
    if operation in {'register', 'correct', 'void'}:
        refresh_for_fee(user, row)
    return row
