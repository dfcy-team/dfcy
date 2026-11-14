"""Prepare disabled native video jobs; scheduling remains an explicit user action."""
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.masterdata.models import StoreMaster
from .models import MarketplaceStoreAuthorization, SyncJob
from .sync_services import validate_manual_sync_job


def prepare_video_job(*, actor, store_id, commit=False, authorization_id=None):
    if not actor.is_active or not actor.tenant_id:
        raise ValidationError("VIDEO_ACTOR_UNAVAILABLE")
    with transaction.atomic():
        # Serialize creation across different authorizations of the same shop.
        store = StoreMaster.objects.select_for_update().get(
            pk=store_id, tenant_id=actor.tenant_id, platform__platform_type="tiktok")
        if store.status != "active":
            raise ValidationError("VIDEO_STORE_INACTIVE")
        existing = list(SyncJob.objects.filter(
            tenant_id=actor.tenant_id, store_authorization__store_id=store.pk,
            resource_type="video_metrics").order_by("pk")[:2])
        if len(existing) > 1:
            raise ValidationError("VIDEO_DUPLICATE_JOBS")
        if existing:
            if authorization_id is not None and existing[0].store_authorization_id != authorization_id:
                raise ValidationError("VIDEO_EXISTING_AUTHORIZATION_DIFFERS")
            return {"store_id": store.pk, "job_id": existing[0].pk, "action": "existing"}
        auths = list(MarketplaceStoreAuthorization.objects.select_related(
            "integration_config", "store").filter(
                tenant_id=actor.tenant_id, store_id=store.pk,
                platform="tiktok", status="active")[:2])
        if len(auths) != 1:
            raise ValidationError("VIDEO_SINGLE_ACTIVE_AUTHORIZATION_REQUIRED")
        auth = auths[0]
        if authorization_id is not None and auth.pk != authorization_id:
            raise ValidationError("VIDEO_AUTHORIZATION_CHANGED")
        job = SyncJob(tenant_id=actor.tenant_id, integration_config=auth.integration_config,
            store_authorization=auth, resource_type="video_metrics", schedule_type="manual",
            status="disabled", is_enabled=False, next_run_at=None,
            max_retry_count=0, backoff_base_seconds=5,
            sync_scope={"execution_mode": "live_readonly",
                "collection": {"actor_id": actor.pk, "recent_days": 1},
                "schedule": {"timezone": "Asia/Shanghai", "catch_up": "skip",
                             "execution_budget_seconds": 300}})
        job.full_clean()
        validate_manual_sync_job(job, live_only=True)
        if commit:
            job.save()
        return {"store_id": store.pk, "job_id": job.pk,
                "action": "created_disabled" if commit else "would_create_disabled"}
