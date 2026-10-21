"""Indexed menu pagination over background-built, permission-bound observations."""
import json
import hashlib
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.commerce import country_decisions as domain
from .models import InventoryDecisionView, InventoryDecisionRow


def _view_scope_signature(actor, permission_cache=None, membership_id=None):
    """Bind menu materializations to both effective permissions and identity."""
    base_signature = domain.permission_signature(actor, permission_cache)
    payload = json.dumps([base_signature, membership_id], separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def invalidate_views(tenant_id, country_id=None):
    views = InventoryDecisionView.objects.filter(tenant_id=tenant_id)
    if country_id is not None:
        views = views.filter(country_id=country_id)
    views.exclude(state='pending').update(state='pending', revision=F('revision') + 1)


def menu_page(actor, country, *, decision_state, window_days, target_days, search, offset, limit,
              permission_cache=None, refresh=False):
    domain.require_metrics(actor, permission_cache)
    now = timezone.now()
    membership_id = getattr(actor, '_active_membership_id', None)
    scope_hash = _view_scope_signature(actor, permission_cache, membership_id)
    view, _ = InventoryDecisionView.objects.get_or_create(tenant_id=actor.tenant_id, actor=actor,
        country=country, scope_signature=scope_hash, window_days=window_days, target_days=target_days,
        defaults={'requested_at': now, 'membership_id': membership_id})
    # No catalog scan, broker publish, or network access on the menu request.
    with transaction.atomic():
        view = InventoryDecisionView.objects.select_for_update().get(pk=view.pk)
        if refresh or (view.state == 'failed' and view.updated_at < now - timedelta(seconds=30)) or (view.state == 'ready' and (
                not view.expires_at or view.expires_at <= now)):
            view.state = 'pending'
            view.revision += 1
        view.requested_at = now
        # Polling is not a worker heartbeat. Preserve updated_at so an
        # abandoned claim can expire even while the user keeps this page open.
        view.save(update_fields=['state', 'revision', 'requested_at'])
    if view.state == 'failed':
        return {'results': [], 'count': 0, 'summary': None, 'query_state': 'failed',
                'processed_count': view.processed_count, 'notice': '后台核对暂未完成，请稍后重新查询。'}
    if view.state != 'ready' and (view.state == 'pending' or view.build_revision != view.revision or not view.processed_count):
        return {'results': [], 'count': 0, 'summary': None, 'query_state': 'building',
                'processed_count': view.processed_count,
                'notice': '正在后台核对并整理库存结果，完成后自动显示；当前不能判断是否需要补货或是否存在预警。'}
    rows = InventoryDecisionRow.objects.filter(view=view, revision=view.revision)
    if search.strip():
        value = search.strip()
        rows = rows.filter(Q(sku__sku_code__icontains=value) | Q(sku__legacy_sku_code__icontains=value) |
                           Q(sku__product_name__icontains=value))
    summary = rows.aggregate(total=Count('id'), ready=Count('id', filter=Q(decision_state='ready')),
        positive=Count('id', filter=Q(suggested_quantity__gt=0)), pending=Count('id', filter=Q(decision_state='pending')),
        **{state: Count('id', filter=Q(evaluation_status=state)) for state in ('normal', 'risk', 'not_evaluated', 'no_rules')})
    if decision_state in ('ready', 'pending'):
        rows = rows.filter(decision_state=decision_state)
    elif decision_state == 'positive':
        # An explicit equality also lets SQLite use the boolean key as a
        # constrained index prefix rather than scanning both boolean groups.
        rows = rows.filter(has_suggestion__in=[True])
    elif decision_state != 'all':
        rows = rows.filter(evaluation_status=decision_state)
    # The exact filtered count is already in this aggregation. A separate
    # COUNT repeats the same scan on every page and every progress poll.
    count = summary['total' if decision_state == 'all' else decision_state]
    page_limit = min(limit, max(0, count - offset))
    payloads = list(rows.order_by('sku_code_snapshot', 'sku_id').values_list('payload', flat=True)[
        offset:offset + page_limit]) if page_limit else []
    # Invalidation can commit while the page is read. Never return a mixture
    # from an obsolete generation, even across multiple web workers.
    if not InventoryDecisionView.objects.filter(pk=view.pk, state__in=['ready', 'building', 'claimed'], revision=view.revision).exists():
        return {'results': [], 'count': 0, 'summary': None, 'query_state': 'building',
                'processed_count': 0, 'notice': '数据已更新，正在重新核对。'}
    complete = view.state == 'ready'
    return {'results': payloads, 'count': count, 'summary': summary,
            'query_state': 'ready' if complete else 'building', 'counts_complete': complete,
            'notice': domain.NOTICE if complete else '已核对的结果先行显示，后台继续整理其余商品；数量统计尚未完成。',
            'generated_at': view.generated_at, 'processed_count': view.processed_count}


def build_pending_views(limit=1, batch_size=100):
    """One bounded chunk per view; row generations switch only after completion."""
    from .inventory_decisions import decorate_rows, bind_actor_context
    now = timezone.now()
    ids = list(InventoryDecisionView.objects.filter(state__in=['pending', 'building'],
        requested_at__gte=now - timedelta(minutes=10)).order_by('updated_at', 'pk').values_list('pk', flat=True)[:limit])
    processed = completed = failed = 0
    for pk in ids:
        # This lock only protects a single background chunk, never a menu GET.
        # Claims move out of the queue so a second dispatcher cannot do the
        # same chunk. A timed-out claim is recovered by the periodic worker.
        with transaction.atomic():
            view = InventoryDecisionView.objects.select_for_update().select_related('actor__tenant', 'country').get(pk=pk)
            if view.state not in ('pending', 'building'):
                continue
            if view.build_revision != view.revision:
                view.cursor = 0
                view.processed_count = 0
                view.build_revision = view.revision
                view.expires_at = None
            view.state = 'claimed'
            view.save()
            revision, cursor = view.revision, view.cursor
        try:
            bind_actor_context(view.actor, view.membership_id)
            domain.require_metrics(view.actor)
            country = domain.country_for(view.actor, view.country_id)
            if _view_scope_signature(view.actor, membership_id=view.membership_id) != view.scope_signature:
                raise APIException('Inventory data scope changed.')
            batch_limit = max(1, min(batch_size, 100))
            candidates = list(domain.skus_for(view.actor, country).filter(pk__gt=cursor).select_related(
                'spu__category_node').order_by('pk')[:batch_limit + 1])
            has_more = len(candidates) > batch_limit
            skus = candidates[:batch_limit]
            observations = domain.decision_rows(view.actor, country, skus,
                window_days=view.window_days, target_days=view.target_days)
            decorate_rows(view.actor, country, observations, window_days=view.window_days, target_days=view.target_days)
            with transaction.atomic():
                current = InventoryDecisionView.objects.select_for_update().get(pk=pk)
                if current.revision != revision or current.state != 'claimed':
                    continue
                InventoryDecisionRow.objects.bulk_create([InventoryDecisionRow(view=current, revision=revision,
                    sku_id=row['sku_id'], decision_state=row['decision_state'], evaluation_status=row['evaluation_status'],
                    sku_code_snapshot=row['sku'], has_suggestion=row['suggested_quantity'] is not None and row['suggested_quantity'] > 0,
                    suggested_quantity=row['suggested_quantity'],
                    payload=json.loads(json.dumps(row, cls=DjangoJSONEncoder))) for row in observations])
                deadlines = [row['data_at'] + timedelta(hours=24) for row in observations
                             if row['decision_state'] == 'ready' and row['data_at']]
                deadlines += [current.expires_at] if current.expires_at else []
                current.expires_at = min(deadlines) if deadlines else None
                current.cursor = skus[-1].pk if skus else cursor
                current.processed_count += len(skus)
                current.state = 'building' if has_more else 'ready'
                if current.state == 'ready':
                    current.generated_at = timezone.now()
                    current.expires_at = min([current.generated_at + timedelta(minutes=5),
                                             *([current.expires_at] if current.expires_at else [])])
                    InventoryDecisionRow.objects.filter(view=current).exclude(revision=revision).delete()
                    completed += 1
                current.save()
            processed += len(skus)
        except APIException:
            InventoryDecisionView.objects.filter(pk=pk, revision=revision).update(state='failed')
            failed += 1
        except Exception:
            InventoryDecisionView.objects.filter(pk=pk, revision=revision).update(state='failed')
            raise
    return {'processed': processed, 'completed': completed, 'failed': failed}


def recover_views():
    now = timezone.now()
    InventoryDecisionView.objects.filter(state='claimed', updated_at__lt=now - timedelta(minutes=5)).update(
        state='pending', revision=F('revision') + 1)
    # Old permission signatures and unused parameter combinations expire.
    InventoryDecisionView.objects.filter(requested_at__lt=now - timedelta(days=1)).delete()
