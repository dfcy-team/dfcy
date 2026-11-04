"""Stored TikTok spend, scoped to sales and analytics; no provider calls."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import DatabaseError, transaction
from rest_framework.exceptions import ValidationError
from apps.commerce.models import SalesOrder
from apps.integrations.models import TikTokAdsAdvertiserMapping
from apps.integrations.gmv_max_read import GMVMaxSnapshotOverflow
from .tiktok_source import preferred_tiktok_days
from apps.masterdata.exchange_rates import tenant_cny_rates
from apps.reports.advertising_dataset import advertising_store_scope
from apps.permissions.ui_p6_scopes import (
    INTEGRATION_SCOPE_KEYS, _validate_integration_configs, permission_scope_configs,
)
from apps.permissions.services import get_stored_business_read_scopes
from apps.sales_management.tiktok_gmvmax import _mapping_allowed


def _number(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() and n >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def tiktok_spend(request, sales_orders, params, *, store_days=None):
    """Verified GMV Max preferred per account/window; otherwise stored auction."""
    _, visible_ids = advertising_store_scope(request.user)
    pairs = set(sales_orders.order_by().values_list('store_id', 'currency').distinct())
    ids = {sid for sid, _ in pairs} & set(visible_ids)
    if not ids:
        return {}, {}
    mappings = list(TikTokAdsAdvertiserMapping.objects.filter(
        tenant_id=request.user.tenant_id, store_id__in=ids,
        store__tenant_id=request.user.tenant_id, store__platform__tenant_id=request.user.tenant_id,
        store__platform__platform_type='tiktok', integration_config__tenant_id=request.user.tenant_id,
        integration_config__platform='tiktok',
    ).select_related('store'))
    if not mappings:
        return {}, {}
    try:
        scopes = permission_scope_configs(request.user, 'integrations.store.view', INTEGRATION_SCOPE_KEYS,
            scope_resolver=get_stored_business_read_scopes)
        if scopes is not None:
            _validate_integration_configs(scopes)
    except Exception:
        scopes = []
    allowed_mappings = [m for m in mappings if _mapping_allowed(request.user, m, scopes)]
    hidden_store_ids = {m.store_id for m in mappings if m not in allowed_mappings}
    mappings = allowed_mappings
    if not mappings:
        return {}, {}
    by_mapping = {m.pk: m for m in mappings}
    mapped_ids = {m.store_id for m in mappings}
    keys = {key for key in pairs if key[0] in mapped_ids}
    # Check independently of selected currency: never charge an entire bill
    # once per sales currency when a store needs allocation rules.
    currencies = defaultdict(set)
    for sid, code in SalesOrder.objects.filter(tenant_id=request.user.tenant_id,
            store_id__in=mapped_ids).order_by().values_list('store_id', 'currency').distinct():
        currencies[sid].add(code)
    rates = tenant_cny_rates(request.user.tenant)
    amounts = defaultdict(lambda: [None, None])
    originals = defaultdict(lambda: defaultdict(Decimal))
    issues, fx_notes = defaultdict(set), defaultdict(set)
    identities, rows = defaultdict(set), []
    windows = ((params['date_from'], params['date_to']),
               (params.get('previous_from'), params.get('previous_to')))
    for key in keys:
        if key[0] in hidden_store_ids:
            issues[(key, 0)].add('部分广告账户受访问范围限制，店铺花费无法完整确认')
            issues[(key, 1)].add('部分广告账户受访问范围限制，店铺花费无法完整确认')
    start = min(w[0] for w in windows if w[0] is not None)
    end = params['date_to']
    if store_days:
        start, end = min(store_days.values()), max(store_days.values())

    def add(sid, code, day, amount, source):
        ix = (0 if day == store_days.get(sid) else None) if store_days else next(
            (i for i, (lo, hi) in enumerate(windows) if lo and lo <= day <= hi), None)
        if ix is None:
            return
        for key in keys:
            if key[0] != sid:
                continue
            value = _number(amount)
            if value is None:
                issues[(key, ix)].add('广告金额无效')
                continue
            originals[(key, ix)][(source, code)] += value
            target = key[1]
            if len(currencies[sid]) > 1:
                issues[(key, ix)].add('店铺存在多种销售币种，广告费尚未分摊')
                continue
            if code != target:
                src, dst = rates.get(code, {}), rates.get(target, {})
                a, b = _number(src.get('rate')), _number(dst.get('rate'))
                if not a or not b:
                    issues[(key, ix)].add(f'缺少有效 {code}/{target} 参考汇率')
                    continue
                value = value / a * b
                fx_notes[key].add(f'{code}÷{a}×{b}→{target}（参考汇率日期 {src.get("date") or "无"}/{dst.get("date") or "无"}）')
            amounts[key][ix] = (amounts[key][ix] or Decimal(0)) + value

    failure = None
    try:
        with transaction.atomic():
            for row in preferred_tiktok_days(request.user, mappings, start, end,
                                            store_days=store_days, windows=None if store_days else windows):
                mapping = by_mapping[row['mapping_id']]
                day = date.fromisoformat(row['date'])
                identities[(mapping.pk, day)].add((row.get('platform_store_id'), row.get('timezone'), row['currency']))
                rows.append((mapping, row, day))
            for mapping, row, day in rows:
                if len(identities[(mapping.pk, day)]) > 1:
                    for key in keys:
                        if key[0] == mapping.store_id:
                            ix = (0 if day == store_days.get(mapping.store_id) else None) if store_days else next(
                                (i for i, (lo, hi) in enumerate(windows) if lo and lo <= day <= hi), None)
                            if ix is not None:
                                issues[(key, ix)].add('同一广告账户日期的平台店铺或时区冲突，花费无法确定')
                    continue
                add(mapping.store_id, row['currency'], day, row['cost'], row['source'])
    except (DatabaseError, ValidationError, GMVMaxSnapshotOverflow, KeyError, ValueError, TypeError):
        failure = 'TK 广告读取暂不可用，请缩小日期范围或稍后重试'
    result, metadata = {}, {}
    for key in keys:
        values = amounts[key]
        for ix in (0, 1):
            if failure or issues[(key, ix)]:
                values[ix] = None
        result[key] = tuple(values)
        evidence = []
        for ix, label in ((0, '本期'), (1, '前期')):
            parts = [f'{source} {value:f} {code}' for (source, code), value in sorted(originals[(key, ix)].items())]
            if parts:
                evidence.append(f'{label}：' + ' + '.join(parts))
        evidence.extend(sorted(fx_notes[key]))
        evidence.append('TK 已入库已知花费小计，覆盖未验证，缺日不补零；广告报表日口径，可能与店铺当地日边界不同；同账户所选区间优先已验证 GMV Max，否则普通竞价；同一区间不混用来源')
        metadata[key] = {'ad_basis': '；'.join(evidence),
                         'ad_reason': failure or '；'.join(sorted(issues[(key, 0)])) or None}
    return result, metadata


def attach_tiktok_basis(request, rows, groups):
    metadata = getattr(request, '_tiktok_ad_metadata', {})
    for row in rows:
        item = metadata.get((row['store_id'], row['currency']))
        if item:
            row['ad_basis'] = item['ad_basis']
            if item['ad_reason']:
                row.update(ad_reason=item['ad_reason'], ad_status='unavailable')
            elif row.get('ad_spend') is not None:
                row['ad_status'] = 'provisional'
    for group in groups:
        items = [v for (_, code), v in metadata.items() if code == group['currency']]
        if items:
            group['ad_basis'] = '含 TK 已验证 GMV Max 优先、普通竞价回退的已知花费；异币按系统参考汇率折算，原币金额及汇率见店铺取值依据；覆盖未验证。'
            if group.get('ad_spend') is not None:
                group['ad_status'] = 'provisional'
            if any(v['ad_reason'] for v in items):
                group['ad_reason'] = (group.get('ad_reason') or '') + '；部分 TK 店铺未能换算或读取，未计入此小计，请查看店铺取值依据。'
