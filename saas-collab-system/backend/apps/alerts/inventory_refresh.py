"""Coalesced dirty watches: business writes never wait for Celery or recompute a catalog."""
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.db.models import F

from .models import InventoryAlert, InventoryDecisionAssessment


@transaction.atomic
def invalidate_decisions(tenant_id, *, country_id=None, reason='source_changed'):
    from .inventory_views import invalidate_views
    invalidate_views(tenant_id, country_id)
    watches = InventoryDecisionAssessment.objects.filter(tenant_id=tenant_id, auto_refresh=True)
    if country_id is not None:
        watches = watches.filter(country_id=country_id)
    # Keeping the watch even after a failed evaluation makes retry observable.
    watches.filter(needs_refresh=False).update(needs_refresh=True, refresh_after=timezone.now())
    alerts = InventoryAlert.objects.filter(tenant_id=tenant_id,
        source_summary__mode='real_observation').exclude(status=InventoryAlert.Status.CLOSED).exclude(evaluation_state='pending')
    if country_id is not None:
        alerts = alerts.filter(source_summary__country_id=country_id)
    # A constant number of SQL updates, regardless of how many alerts a sync
    # affects. Detailed evidence is recorded by the subsequent evaluation.
    alerts.update(evaluation_state='pending', version=F('version') + 1)


def mark_after_commit(tenant_id, *, country_id=None, reason='source_changed'):
    transaction.on_commit(lambda: invalidate_decisions(tenant_id, country_id=country_id, reason=reason))


def refresh_due_decisions(limit=50):
    from collections import defaultdict
    from django.db.models import Q
    from rest_framework.exceptions import APIException
    from django.core.exceptions import ValidationError
    from .inventory_decisions import evaluate_country, bind_actor_context
    now = timezone.now()
    # A short DB claim prevents overlapping Beat runs from duplicating work.
    with transaction.atomic():
        claimed_ids = list(InventoryDecisionAssessment.objects.select_for_update().filter(auto_refresh=True).filter(
            Q(needs_refresh=True) | Q(refresh_after__lte=now)).order_by('refresh_after', 'pk')[:max(1, min(limit, 100))]
            .values_list('pk', flat=True))
        InventoryDecisionAssessment.objects.filter(pk__in=claimed_ids).update(
            needs_refresh=False, refresh_after=now + timedelta(minutes=10))
    # Lock only the assessment rows above. Joining the nullable SKU category
    # relation into SELECT FOR UPDATE fails on PostgreSQL; these relations are
    # loaded after the bounded claim commits and do not need to be locked.
    loaded = InventoryDecisionAssessment.objects.filter(pk__in=claimed_ids).select_related(
        'actor__tenant', 'country', 'sku__spu__category_node')
    by_id = {watch.pk: watch for watch in loaded}
    watches = [by_id[pk] for pk in claimed_ids if pk in by_id]
    groups = defaultdict(list)
    for watch in watches:
        groups[(watch.actor_id, watch.membership_id, watch.country_id, watch.window_days, watch.target_days)].append(watch)
    result = {'processed': 0, 'pending': 0}
    for (_, membership, _, window, target), batch in groups.items():
        first = batch[0]
        try:
            bind_actor_context(first.actor, membership)
            outcome = evaluate_country(first.actor, first.country, [w.sku for w in batch],
                                       window_days=window, target_days=target, automatic=True)
            skipped = {row['sku_id'] for row in outcome['skipped'] if row['issues'] == ['alert_target_not_authorized']}
            if skipped:
                InventoryDecisionAssessment.objects.filter(pk__in=[w.pk for w in batch if w.sku_id in skipped]).update(
                    state='pending', issues=['alert_target_not_authorized'], refresh_after=now + timedelta(minutes=5))
            result['processed'] += len(batch)
            result['pending'] += len(outcome['skipped'])
        except (APIException, ValidationError):
            InventoryDecisionAssessment.objects.filter(pk__in=[w.pk for w in batch]).update(
                state='pending', issues=['evaluation_authorization_or_data_changed'],
                needs_refresh=False, refresh_after=now + timedelta(minutes=5))
            result['pending'] += len(batch)
    return result
