"""System-run bridge for bounded, tenant-scoped creator and video collection."""
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.influencers.models import TikTokCreatorProfileSnapshot
from .adapters import ProductionReadonlyAdapter
from .models import CollectionUnitReceipt, SyncJob


def collection_plan(policy, resource, today):
    if not isinstance(policy, dict) or type(policy.get("actor_id")) is not int or policy["actor_id"] <= 0:
        raise ValidationError("COLLECTION_ACTOR_REQUIRED")
    if resource == "video_metrics":
        page_size = policy.get("page_size", 10)
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise ValidationError("COLLECTION_PAGE_SIZE_INVALID")
        days = policy.get("recent_days", 1)
        if type(days) is not int or not 1 <= days <= 2:
            raise ValidationError("COLLECTION_DAY_LIMIT")
        units = [(today - timedelta(days=i)).isoformat() for i in range(days, 0, -1)]
    elif resource == "creator_profile":
        ids = policy.get("influencer_ids")
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 100
                or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids)):
            raise ValidationError("COLLECTION_EXPLICIT_IDENTITIES_REQUIRED")
        units = [str(i) for i in sorted(ids)]
    else:
        raise ValidationError("COLLECTION_RESOURCE_INVALID")
    plan = {"actor_id": policy["actor_id"], "resource": resource, "units": units}
    if resource == "video_metrics":
        plan["page_size"] = page_size
    return plan


class TikTokCollectionAdapter(ProductionReadonlyAdapter):
    adapter_name = "tiktok-system-collection"

    def validate_configuration(self, job):
        super().validate_configuration(job)
        from .creator_video_capability import require_collection_capability
        require_collection_capability(self.authorization, "VIDEO" if job.resource_type == "video_metrics" else "CREATOR")
        policy = (job.sync_scope or {}).get("collection")
        store_timezone = ZoneInfo(self.authorization.store.timezone)
        reference = getattr(job, "_video_scheduled_at", None) or timezone.now()
        plan = collection_plan(policy, job.resource_type, reference.astimezone(store_timezone).date())
        history_day = getattr(job, "_history_video_day", None)
        if history_day is not None:
            today = timezone.now().astimezone(store_timezone).date()
            if not today - timedelta(days=30) <= history_day < today:
                raise ValidationError("VIDEO_HISTORY_DAY_OUTSIDE_LAST_30_COMPLETE_DAYS")
            plan["units"] = [history_day.isoformat()]
        elif job.resource_type == "video_metrics" and "recovery_start" in policy:
            from apps.influencers.models import TikTokVideoSyncBatch
            from apps.influencers.tiktok_video_sync import VERSION

            today = timezone.now().astimezone(ZoneInfo(self.authorization.store.timezone)).date()
            first = max(date.fromisoformat(policy["recovery_start"]), today - timedelta(days=30))
            latest = today - timedelta(days=2)
            if first > latest or policy.get("recent_days", 1) != 1:
                raise ValidationError("VIDEO_RECOVERY_WINDOW_INVALID")
            done = set(TikTokVideoSyncBatch.objects.filter(
                tenant_id=job.tenant_id, store_id=self.authorization.store_id,
                api_version=VERSION, status="completed", window_start__gte=first,
                window_start__lte=latest,
            ).values_list("window_start", flat=True))
            candidates = (first + timedelta(days=i) for i in range((latest - first).days + 1))
            # One day per run avoids carrying a day cursor into another run.
            plan["units"] = [next((day for day in candidates if day not in done), latest).isoformat()]
        frozen = (getattr(job, "_frozen_sync_scope", None) or {}).get("collection_plan")
        if frozen is not None:
            if frozen.get("actor_id") != plan["actor_id"] or frozen.get("resource") != job.resource_type:
                raise ValidationError("COLLECTION_SOURCE_CHANGED")
            plan = frozen
        self.scope["collection_plan"] = plan
        self.actor = get_user_model().objects.filter(
            pk=plan["actor_id"], tenant_id=job.tenant_id, is_active=True).first()
        if self.actor is None:
            raise ValidationError("COLLECTION_ACTOR_UNAVAILABLE")
        if job.resource_type == "creator_profile":
            # Initial migration only refreshes identities already evidenced for this store.
            ids = {int(i) for i in plan["units"]}
            evidenced = set(TikTokCreatorProfileSnapshot.objects.filter(
                tenant_id=job.tenant_id, store_id=self.authorization.store_id,
                influencer_id__in=ids).values_list("influencer_id", flat=True))
            if evidenced != ids:
                raise ValidationError("COLLECTION_STORE_EVIDENCE_REQUIRED")

    def _receipt(self, job, key, result):
        run = self._require_run()
        with transaction.atomic():
            locked = SyncJob.objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
            if (not locked.is_enabled or locked.status != "running" or locked.lock_token != run.run_id
                    or not locked.lock_expires_at or locked.lock_expires_at <= timezone.now()):
                raise ValidationError("COLLECTION_LEASE_LOST")
            receipt, created = CollectionUnitReceipt.objects.get_or_create(
                sync_run=run, unit_key=key, defaults={"result": result})
            if not created and receipt.result != result:
                raise ValidationError("COLLECTION_RECEIPT_CONFLICT")
            return receipt

    def fetch_page(self, job, cursor_value=None):
        run = self._require_run()
        plan = self.scope["collection_plan"]
        prefix = f"collection:{run.run_id}:"
        if not cursor_value:
            index = 0
        else:
            if not isinstance(cursor_value, str) or not cursor_value.startswith(prefix):
                raise ValidationError("COLLECTION_CURSOR_INVALID")
            suffix = cursor_value[len(prefix):]
            if not suffix.isascii() or not suffix.isdecimal() or len(suffix) > 3:
                raise ValidationError("COLLECTION_CURSOR_INVALID")
            index = int(suffix)
        if not 0 <= index < len(plan["units"]):
            raise ValidationError("COLLECTION_CURSOR_INVALID")
        unit = plan["units"][index]
        key = f"{job.resource_type}:{unit}"
        receipt = CollectionUnitReceipt.objects.filter(sync_run=run, unit_key=key).first()
        if receipt is None:
            callback = lambda result: self._receipt(job, key, result)
            if job.resource_type == "video_metrics":
                from apps.influencers.tiktok_video_sync import run_day
                run_day(self.actor, self.authorization.store_id, date.fromisoformat(unit),
                        apply=True, refresh=False, commit_receipt=callback,
                        page_size=plan.get("page_size", 10), page_delay_seconds=2)
            else:
                from apps.influencers.tiktok_creator_lookup import lookup_tiktok_creator
                result = lookup_tiktok_creator(actor=self.actor, influencer_id=int(unit),
                    store_id=self.authorization.store_id, commit_receipt=callback, search_handle=True)
                if result.get("status") == "candidate":
                    callback({"created": 0, "updated": 0, "skipped": 1,
                              "identity_status": "candidate", "reason": result.get("reason"),
                              "candidate": result.get("candidate", {})})
            receipt = CollectionUnitReceipt.objects.get(sync_run=run, unit_key=key)
        return {"records": [{"unit_key": key}], "receipt_id": receipt.pk,
                "next_cursor": prefix + str(index + 1) if index + 1 < len(plan["units"]) else ""}

    def normalize_record(self, record):
        return record

    def persist_record(self, job, record):
        return {"action": "skipped", "idempotency_key": record["unit_key"]}

    def after_page_persist(self, job, page, results):
        run = self._require_run()
        receipts = list(CollectionUnitReceipt.objects.filter(sync_run=run).values_list("result", flat=True))
        run.created_count = sum(r.get("created", 0) for r in receipts)
        run.updated_count = sum(r.get("updated", 0) for r in receipts)
        run.skipped_count = sum(r.get("skipped", 0) for r in receipts)
        run.fetched_count = run.created_count + run.updated_count + run.skipped_count
        run.masked_log = {**(run.masked_log or {}), "collection_progress": {
            "completed_units": len(receipts), "total_units": len(self.scope["collection_plan"]["units"]),
            "matched": sum(r.get("identity_status") == "matched" for r in receipts),
            "unverified": sum(r.get("identity_status") not in (None, "matched") for r in receipts),
            "count_unit": "video_daily_metric" if job.resource_type == "video_metrics" else "creator_snapshot",
        }}
