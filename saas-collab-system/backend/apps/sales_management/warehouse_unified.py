"""Bridge unified warehouse SyncJobs to the durable per-order state machine."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.integrations.models import SyncJob
from .warehouse_order_models import OrderWarehouseLookup


def managed_country_pairs():
    """Tenant/country pairs claimed by any lookup job, enabled or not."""
    jobs = SyncJob.objects.filter(resource_type="warehouse_order_lookup",
                                  integration_config__environment='production',
                                  warehouse_authorization__isnull=False)
    return set((tenant_id, (country or "").upper()) for tenant_id, country in
               jobs.values_list("tenant_id", "warehouse_authorization__warehouse__country_code").distinct()
               if country)


def managed_for_order(order):
    country = getattr(order.store, 'country_code', '') or ''
    return bool(country and SyncJob.objects.filter(
        resource_type='warehouse_order_lookup', tenant_id=order.tenant_id,
        integration_config__environment='production',
        warehouse_authorization__warehouse__country_code__iexact=country).exists())


def managed_for_order_id(order_id):
    pair = OrderWarehouseLookup.objects.filter(pk=order_id).values_list(
        "order__tenant_id", "order__store__country_code").first()
    return bool(pair and (pair[0], (pair[1] or "").upper()) in managed_country_pairs())


def process_next_lookup(job, *, run_guard=None, readiness=None, permission_cache=None,
                        cleanup_expired_polling=True):
    """Process at most one eligible requested order for this job's authorization."""
    now = timezone.now()
    if run_guard is not None and not run_guard():
        from rest_framework.exceptions import ValidationError
        raise ValidationError('WAREHOUSE_LOOKUP_STOPPED')
    auth = job.warehouse_authorization
    if (job.resource_type != "warehouse_order_lookup" or not auth or
            auth.tenant_id != job.tenant_id or auth.warehouse.tenant_id != job.tenant_id):
        return None
    country = (auth.warehouse.country_code or "").upper()
    if not country:
        return None
    scoped = OrderWarehouseLookup.objects.filter(
        order__tenant_id=job.tenant_id, order__store__country_code__iexact=country,
    )
    if cleanup_expired_polling:
        scoped.exclude(status__in=['pending', 'running']).filter(next_query_at__lte=now).filter(
            Q(polling_until__isnull=True) | Q(polling_until__lte=now)
        ).update(next_query_at=None)
    eligible = scoped.filter(
        (Q(status="pending") & (Q(lease_until__isnull=True) | Q(lease_until__lte=now))) |
        Q(status="running", lease_until__lte=now) |
        (~Q(status__in=["pending", "running"]) & Q(next_query_at__lte=now) &
         Q(polling_until__gt=now))
    )
    # Bound database work and serialize competing unified dispatchers while selecting.
    with transaction.atomic():
        lookup_pk = eligible.select_for_update(skip_locked=True, of=('self',)).order_by(
            "requested_at", "pk").values_list("pk", flat=True).first()
        if lookup_pk is None:
            return None
        row = OrderWarehouseLookup.objects.select_related(
            "order__store", "requested_by").defer("order__source_details").get(pk=lookup_pk)
        if row.status not in {"pending", "running"}:
            if not row.polling_until or row.polling_until <= now:
                return None
            from .warehouse_order_policy import unpaid
            if unpaid(row.order):
                OrderWarehouseLookup.objects.filter(pk=row.pk, revision=row.revision).update(next_query_at=None)
                return {'lookup_id': row.pk, 'status': 'deferred', 'queried': False}
            blocked = row.status == 'blocked' or any(check.get('status') == 'blocked' for check in row.checks)
            if blocked:
                from .warehouse_orders import scheduled_ready
                if not scheduled_ready(row, readiness=readiness, permission_cache=permission_cache):
                    OrderWarehouseLookup.objects.filter(pk=row.pk, revision=row.revision).update(
                        next_query_at=min(now + timedelta(hours=1), row.polling_until))
                    return {'lookup_id': row.pk, 'status': 'blocked', 'queried': False}
            from .warehouse_orders import request_lookup
            renewed = request_lookup(row.order_id, row.requested_by, scheduled=True)
            if not renewed or renewed.status not in {"pending", "running"}:
                return None
            row = renewed
        lookup_id, revision = row.pk, str(row.revision)

    if run_guard is not None and not run_guard():
        return {"lookup_id": lookup_id, "status": "blocked", "queried": False}
    from .warehouse_orders import synchronize
    result = synchronize(lookup_id, revision, run_guard=run_guard)
    return {"lookup_id": lookup_id, "status": result,
            "queried": result not in {"superseded", "already_running", "cancelled"}}
