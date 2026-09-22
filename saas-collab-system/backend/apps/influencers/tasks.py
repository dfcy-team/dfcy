import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant

from .attribution import refresh_order_attributions
from .bd_config import bd_performance_settings
from .models import AffiliateImportState, AffiliateOrderSnapshot, SampleFulfillment
from .services import SAMPLE_TIMEOUT_CANDIDATE_STATUSES, mark_overdue_sample_fulfillments


logger = logging.getLogger(__name__)

HISTORICAL_ATTRIBUTION_SOURCE = "bd_attribution_history"
HISTORICAL_ATTRIBUTION_BATCH_SIZE = 5000


@shared_task(name="influencers.refresh_affiliate_order_attributions")
def refresh_affiliate_order_attributions_task(tenant_id, changed_since=None):
    """Refresh both deterministic attribution modes for one tenant only."""
    result = {"tenant_id": tenant_id, "modes": {}}
    if not Tenant.objects.filter(pk=tenant_id).exists():
        return {**result, "status": "tenant_not_found"}

    parsed_changed_since = None
    if changed_since:
        parsed_changed_since = datetime.fromisoformat(changed_since)
        if timezone.is_naive(parsed_changed_since):
            parsed_changed_since = timezone.make_aware(parsed_changed_since, timezone.get_current_timezone())
    with transaction.atomic():
        # The tenant lock serializes duplicate deliveries and advances the history
        # cursor only after both attribution modes complete successfully.
        tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
        state, _ = AffiliateImportState.objects.select_for_update().get_or_create(
            tenant=tenant,
            source=HISTORICAL_ATTRIBUTION_SOURCE,
        )
        try:
            cursor_id = max(0, int(state.cursor or "0"))
        except (TypeError, ValueError):
            cursor_id = 0
        historical_ids = list(
            AffiliateOrderSnapshot.objects.filter(
                tenant=tenant,
                pk__gt=cursor_id,
                updated_at__lt=parsed_changed_since,
            ).order_by("pk").values_list("pk", flat=True)[:HISTORICAL_ATTRIBUTION_BATCH_SIZE]
        ) if parsed_changed_since is not None else []
        for mode in ("strict", "fallback"):
            result["modes"][mode] = refresh_order_attributions(
                tenant=tenant,
                attribution=mode,
                changed_since=parsed_changed_since,
                order_ids=historical_ids,
            )
        cycle_completed = parsed_changed_since is not None and not historical_ids
        state.cursor = "0" if cycle_completed else str(historical_ids[-1] if historical_ids else cursor_id)
        state.last_row_count = len(historical_ids)
        state.last_error_code = ""
        state.status = AffiliateImportState.Status.IDLE
        state.save(update_fields=["cursor", "last_row_count", "last_error_code", "status", "updated_at"])
        result["historical_backfill"] = {
            "batch_size": len(historical_ids),
            "cursor": state.cursor,
            "cycle_completed": cycle_completed,
        }
    result["status"] = "completed"
    return result


@shared_task(name="influencers.dispatch_daily_affiliate_order_attribution_refreshes")
def dispatch_daily_affiliate_order_attribution_refreshes_task():
    """Queue one tenant-isolated attribution refresh for tenants with order facts."""
    tenant_ids = list(
        AffiliateOrderSnapshot.objects.order_by()
        .values_list("tenant_id", flat=True)
        .distinct()
    )
    queued_tenant_ids = []
    skipped_tenant_ids = []
    changed_since = timezone.now() - timedelta(days=7)
    for tenant_id in tenant_ids:
        if not bd_performance_settings(tenant_id)["daily_attribution_reconciliation_enabled"]:
            skipped_tenant_ids.append(tenant_id)
            continue
        refresh_affiliate_order_attributions_task.delay(
            tenant_id=tenant_id,
            changed_since=changed_since.isoformat(),
        )
        queued_tenant_ids.append(tenant_id)
    return {
        "status": "queued",
        "tenant_count": len(queued_tenant_ids),
        "tenant_ids": queued_tenant_ids,
        "skipped_tenant_ids": skipped_tenant_ids,
        "changed_since": changed_since.isoformat(),
    }


@shared_task(name="influencers.mark_overdue_sample_fulfillments")
def mark_overdue_sample_fulfillments_task():
    """Daily tenant-isolated reconciliation; it never calls an external platform."""
    now = timezone.now()
    tenant_ids = list(
        SampleFulfillment.objects.filter(
            is_deleted=False,
            video_deadline_at__lt=now,
            status__in=SAMPLE_TIMEOUT_CANDIDATE_STATUSES,
        )
        .filter(Q(outreach_task__isnull=True) | Q(outreach_task__is_deleted=False))
        .values_list("tenant_id", flat=True)
        .distinct()
    )
    result = {
        "tenants": 0,
        "marked": 0,
        "skipped_with_video": 0,
        "skipped_without_actor": 0,
        "notifications_created": 0,
    }
    for tenant_id in tenant_ids:
        actor = (
            CustomUser.objects.filter(
                tenant_id=tenant_id,
                is_active=True,
                user_type=CustomUser.UserType.INTERNAL,
            )
            .filter(
                Q(owned_sample_fulfillments__is_deleted=False)
                | Q(owned_outreach_tasks__is_deleted=False)
            )
            .distinct()
            .order_by("id")
            .first()
        )
        if actor is None:
            result["skipped_without_actor"] += 1
            logger.warning("No active internal audit actor for overdue samples tenant=%s", tenant_id)
            continue
        tenant_result = mark_overdue_sample_fulfillments(
            actor=actor,
            tenant=actor.tenant,
            now=now,
            notify_overdue=bd_performance_settings(tenant_id)["sample_overdue_notification_enabled"],
        )
        result["tenants"] += 1
        result["marked"] += tenant_result["marked"]
        result["skipped_with_video"] += tenant_result["skipped_with_video"]
        result["notifications_created"] += tenant_result["notifications_created"]
    return result
