"""Country decision classification and audited real-data alert evaluation."""
import hashlib
import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.commerce import country_decisions as domain
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from .models import InventoryAlert, InventoryAlertEvent, InventoryAlertRule, InventoryDecisionAssessment


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def bind_actor_context(actor, membership_id):
    """Restore, and revalidate, the department context used to authorize work."""
    if membership_id is not None:
        from django.db.models import Q
        from apps.permissions.models import OrgMembership
        if not OrgMembership.objects.filter(pk=membership_id, user=actor, tenant_id=actor.tenant_id,
                status='active', department__status='active').filter(
                Q(valid_until__isnull=True) | Q(valid_until__gt=timezone.now())).exists():
            raise PermissionDenied('评估所用组织身份已失效，请重新选择有效身份。')
    actor._active_membership_id = membership_id
    return actor


def active_rules(tenant_id):
    latest = {}
    for rule in InventoryAlertRule.objects.filter(tenant_id=tenant_id, effective_at__lte=timezone.now()
            ).order_by('rule_code', '-version', '-pk'):
        latest.setdefault(rule.rule_code, rule)
    return [rule for rule in latest.values() if rule.is_enabled]


def rules_signature(rules):
    return digest([(r.pk, r.version, r.alert_type, r.severity, r.threshold_config) for r in rules])


def source_signature(row):
    return digest({key: row.get(key) for key in (
        'source_snapshot_ids', 'source_run_ids', 'available_stock', 'daily_sales', 'sales_windows',
        'pipeline', 'blocking_issues', 'data_at', 'suggested_quantity')})


def decorate_rows(actor, country, rows, *, window_days, target_days, rules=None):
    """Read-only: a GET can never generate or resolve an alert."""
    rules = active_rules(actor.tenant_id) if rules is None else rules
    rule_hash = rules_signature(rules)
    scope_hash = domain.permission_signature(actor)
    latest = {}
    for assessment in InventoryDecisionAssessment.objects.filter(
            tenant_id=actor.tenant_id, country=country, sku_id__in=[r['sku_id'] for r in rows],
            window_days=window_days, target_days=target_days, scope_signature=scope_hash
            ).order_by('-evaluated_at', '-pk'):
        latest.setdefault(assessment.sku_id, assessment)
    versions = [{'rule_code': r.rule_code, 'version': r.version, 'alert_type': r.alert_type,
                 'threshold': r.threshold_config, 'severity': r.severity} for r in rules]
    for row in rows:
        assessment = latest.get(row['sku_id'])
        current = bool(assessment and not assessment.needs_refresh and
                       assessment.source_signature == source_signature(row) and
                       assessment.rules_signature == rule_hash)
        if row['decision_state'] == 'pending':
            state = 'pending'
        elif not rules:
            state = 'no_rules'
        elif current:
            state = assessment.state
        else:
            state = 'not_evaluated'
        row.update(evaluation_status=state, evaluated_at=assessment.evaluated_at if assessment else None,
                   rule_versions=versions)
    return rows


def decision_page(actor, country, skus, *, decision_state, window_days, target_days, offset, limit):
    # Compatibility path for consumers that request an unclassified page.
    rows = domain.decision_rows(actor, country, list(skus[offset:offset + limit]),
                                window_days=window_days, target_days=target_days)
    decorate_rows(actor, country, rows, window_days=window_days, target_days=target_days)
    return rows, skus.count(), None


def evaluation_allowed(actor, sku, country, permission_cache=None):
    if not actor.is_active or actor.user_type != 'internal' or not check_user_permission(actor, 'alerts.evaluate', cache=permission_cache):
        return False
    scopes = get_permission_data_scopes(actor, 'alerts.evaluate', cache=permission_cache)
    alert_allowed = actor.is_superuser or any(s['scope_type'] == 'all' or (
        s['scope_type'] == 'custom' and set(s.get('config') or {}) == {'sku_ids'} and
        sku.pk in s['config']['sku_ids']) for s in scopes)
    if not alert_allowed:
        return False
    # A country alert is shared with other readers. Partial store/warehouse
    # observations must never replace a full-country risk or resolve it.
    for code, resource in ((domain.INVENTORY, 'commerce.inventory'), (domain.SALES, 'sales_management.sales')):
        if not check_user_permission(actor, code, cache=permission_cache):
            return False
        scopes = get_permission_data_scopes(actor, code, resource_code=resource, cache=permission_cache)
        complete = actor.is_superuser or any(s['scope_type'] == 'all' for s in scopes)
        if code == domain.INVENTORY:
            for scope in scopes:
                config = scope.get('config') or {}
                if scope['scope_type'] == 'custom' and config and set(config) <= {'sku_ids', 'spu_ids', 'regions'}:
                    complete |= (('sku_ids' not in config or sku.pk in config['sku_ids']) and
                                 ('spu_ids' not in config or sku.spu_id in config['spu_ids']) and
                                 ('regions' not in config or country.country_code.upper() in config['regions']))
        if not complete:
            return False
    code = 'sales_management.supply_summary.view'
    scopes = get_permission_data_scopes(actor, code, resource_code='sales_management.supply_summary', cache=permission_cache)
    return check_user_permission(actor, code, cache=permission_cache) and (actor.is_superuser or any(
        scope['scope_type'] == 'all' or (scope['scope_type'] == 'custom' and
        country.pk in (scope.get('config') or {}).get('site_ids', [])) for scope in scopes))


def _existing(actor, country, sku):
    return InventoryAlert.objects.select_for_update().select_related('rule').filter(tenant_id=actor.tenant_id, sku=sku,
        warehouse_code=f'COUNTRY:{country.country_code.upper()}', source_summary__mode='real_observation')


def _mark_pending(alerts, issues, now):
    for alert in alerts.exclude(status=InventoryAlert.Status.CLOSED):
        summary = {**alert.source_summary, 'evaluation_status': 'pending', 'blocked_issues': issues}
        if summary == alert.source_summary:
            continue
        alert.source_summary = summary
        alert.evaluation_state = 'pending'
        alert.version += 1
        alert.save(update_fields=['source_summary', 'evaluation_state', 'version', 'updated_at'])
        InventoryAlertEvent.objects.create(tenant_id=alert.tenant_id, alert=alert,
            event_type=InventoryAlertEvent.EventType.DEDUPLICATED,
            detail={'evaluation_status': 'pending', 'issues': issues, 'evaluated_at': now.isoformat()})


def _resolve(alert, now, reason):
    before_status = alert.status
    alert.status = InventoryAlert.Status.CLOSED
    alert.closed_at = now
    alert.silenced_until = None
    alert.resolution = reason
    alert.evaluation_state = 'normal'
    alert.source_summary = {**alert.source_summary, 'evaluation_status': 'normal',
                            'evaluated_at': now.isoformat(), 'resolution_reason': reason}
    alert.version += 1
    alert.save()
    InventoryAlertEvent.objects.create(tenant_id=alert.tenant_id, alert=alert,
        event_type=InventoryAlertEvent.EventType.CLOSED,
        detail={'automatic': True, 'reason': reason, 'before_status': before_status})


@transaction.atomic
def evaluate_country(actor, country, skus, *, window_days=30, target_days=60, automatic=False):
    from apps.supply_chain.services import _tenant_lock
    from .services import evaluate_inventory_alert
    _tenant_lock(actor)
    country = domain.country_for(actor, country.pk)
    domain.require_metrics(actor)
    if automatic:
        # A task may have claimed an old watch just before a manual policy
        # switch. Recheck inside the same tenant lock used by manual writes.
        watched = set(InventoryDecisionAssessment.objects.filter(tenant_id=actor.tenant_id, country=country,
            actor=actor, window_days=window_days, target_days=target_days, auto_refresh=True,
            membership_id=getattr(actor, '_active_membership_id', None),
            sku_id__in=[s.pk for s in skus]).values_list('sku_id', flat=True))
        skus = [sku for sku in skus if sku.pk in watched]
        if not skus:
            return {'mode': 'real_observation', 'created': 0, 'updated': 0, 'closed': 0, 'normal': 0,
                    'skipped': [], 'rule_count': 0, 'notification_sent': False}
    permitted = set(domain.skus_for(actor, country).filter(pk__in=[s.pk for s in skus]).values_list('pk', flat=True))
    if any(s.pk not in permitted for s in skus):
        raise PermissionDenied('商品不在当前库存授权范围内。')
    rules = active_rules(actor.tenant_id)
    now = timezone.now()
    observations = domain.decision_rows(actor, country, skus, window_days=window_days, target_days=target_days)
    by_id = {s.pk: s for s in skus}
    result = {'mode': 'real_observation', 'created': 0, 'updated': 0, 'closed': 0, 'normal': 0,
              'skipped': [], 'rule_count': len(rules), 'notification_sent': False}
    scope_hash = domain.permission_signature(actor)
    evaluation_cache = {}
    for row in observations:
        sku = by_id[row['sku_id']]
        if not evaluation_allowed(actor, sku, country, evaluation_cache):
            result['skipped'].append({'sku_id': sku.pk, 'issues': ['alert_target_not_authorized']})
            continue
        issues = row['blocking_issues']
        previous = _existing(actor, country, sku)
        provenance = {'mode': 'real_observation', 'contains_real_data': True,
            'country_id': country.pk, 'country_code': country.country_code, 'window_days': window_days,
            'target_days': target_days, 'source_snapshot_ids': row['source_snapshot_ids'],
            'source_run_ids': row['source_run_ids'], 'data_at': row['data_at'].isoformat() if row['data_at'] else None,
            'evaluated_at': now.isoformat(), 'evaluation_status': 'risk', 'blocked_issues': [],
            'issues': row['issues'], 'automatic': automatic, 'evaluated_by': actor.pk,
            'formula': '（可用库存 + 按期有效到货）÷ 窗口日均销量'}
        state, matched = 'normal', set()
        if row['decision_state'] == 'pending':
            state = 'pending'
            pending_issues = issues
            _mark_pending(previous, pending_issues, now)
            result['skipped'].append({'sku_id': sku.pk, 'issues': pending_issues})
        else:
            for rule in rules:
                alert, created = evaluate_inventory_alert(tenant=actor.tenant, rule=rule, sku=sku,
                    warehouse_code=f'COUNTRY:{country.country_code.upper()}',
                    available_stock=row['available_stock'], in_transit_stock=row['pipeline']['effective_incoming'],
                    average_daily_sales=row['daily_sales'], source_summary=provenance, evaluated_at=now)
                if alert:
                    matched.add(alert.pk)
                    result['created' if created else 'updated'] += 1
            state = ('risk' if matched else 'normal') if rules else 'no_rules'
            if not matched and rules:
                result['normal'] += 1
            for alert in previous.exclude(status=InventoryAlert.Status.CLOSED).exclude(pk__in=matched):
                current = next((r for r in rules if r.rule_code == alert.rule.rule_code), None)
                reason = ('完整数据重新评估后已不再命中预警阈值。' if current else '对应规则已停用，预警已解除。')
                _resolve(alert, now, reason)
                result['closed'] += 1
        if not automatic:
            # One active measurement policy per country/SKU. Historical
            # windows stay visible but cannot race to overwrite that alert.
            InventoryDecisionAssessment.objects.filter(tenant_id=actor.tenant_id, country=country,
                sku=sku, auto_refresh=True).update(auto_refresh=False, needs_refresh=True)
        InventoryDecisionAssessment.objects.update_or_create(tenant_id=actor.tenant_id,
            country=country, sku=sku, actor=actor, window_days=window_days, target_days=target_days,
            defaults={'scope_signature': scope_hash, 'source_signature': source_signature(row),
                'membership_id': getattr(actor, '_active_membership_id', None),
                'rules_signature': rules_signature(rules), 'state': state,
                'issues': issues or (['no_active_rules'] if not rules else []),
                'evaluated_at': now, 'data_at': row['data_at'], 'needs_refresh': False, 'auto_refresh': True,
                'refresh_after': now + timedelta(minutes=5)})
    from .inventory_views import invalidate_views
    invalidate_views(actor.tenant_id, country.pk)
    return result
