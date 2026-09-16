import logging

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant

from .attribution import refresh_order_attributions
from .bd_config import bd_performance_settings
from .models import AffiliateOrderSnapshot, SampleFulfillment
from .services import SAMPLE_TIMEOUT_CANDIDATE_STATUSES, mark_overdue_sample_fulfillments


logger = logging.getLogger(__name__)


@shared_task(name="influencers.refresh_affiliate_order_attributions")
def refresh_affiliate_order_attributions_task(tenant_id):
    """Refresh both deterministic attribution modes for one tenant only."""
    result = {"tenant_id": tenant_id, "modes": {}}
    if not Tenant.objects.filter(pk=tenant_id).exists():
        return {**result, "status": "tenant_not_found"}

    for mode in ("strict", "fallback"):
        # Serializing on the tenant row makes duplicate queue deliveries harmless
        # while keeping each refresh transaction and rule version independent.
        with transaction.atomic():
            tenant = Tenant.objects.select_for_update().get(pk=tenant_id)
            result["modes"][mode] = refresh_order_attributions(
                tenant=tenant,
                attribution=mode,
            )
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
    for tenant_id in tenant_ids:
        if not bd_performance_settings(tenant_id)["daily_attribution_reconciliation_enabled"]:
            skipped_tenant_ids.append(tenant_id)
            continue
        refresh_affiliate_order_attributions_task.delay(tenant_id=tenant_id)
        queued_tenant_ids.append(tenant_id)
    return {
        "status": "queued",
        "tenant_count": len(queued_tenant_ids),
        "tenant_ids": queued_tenant_ids,
        "skipped_tenant_ids": skipped_tenant_ids,
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
    result = {"tenants": 0, "marked": 0, "skipped_with_video": 0, "skipped_without_actor": 0}
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
        )
        result["tenants"] += 1
        result["marked"] += tenant_result["marked"]
        result["skipped_with_video"] += tenant_result["skipped_with_video"]
    return result
