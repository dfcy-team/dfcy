"""Scheduled GMV Max collection through the existing verified Ads mapping."""
from datetime import date, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.permissions.services import user_has_integration_permission

from .ads_subject import mapping_allowed
from .ads_sync import AdsExecutionStopped, load_mapping, validate_mapping
from .collection_sync import TikTokCollectionAdapter
from .gmv_max_sync import run_day, shop_authorization
from .models import CollectionUnitReceipt, SyncJob


class TikTokGmvMaxAdapter(TikTokCollectionAdapter):
    adapter_name = "tiktok-gmv-max"

    def validate_configuration(self, job):
        mapping = load_mapping(job)
        validate_mapping(mapping)
        auth = shop_authorization(mapping)
        policy = (job.sync_scope or {}).get("gmv_max") or {}
        actor_id = policy.get("actor_id")
        if type(actor_id) is not int or actor_id <= 0:
            raise ValidationError("GMV_MAX_ACTOR_REQUIRED")
        self.actor = get_user_model().objects.filter(pk=actor_id, tenant_id=job.tenant_id, is_active=True).first()
        if (self.actor is None or not user_has_integration_permission(self.actor, "integrations.store.authorize")
                or not mapping_allowed(self.actor, mapping, "integrations.store.authorize")):
            raise ValidationError("GMV_MAX_ACTOR_OUT_OF_SCOPE")
        local_now = timezone.now().astimezone(ZoneInfo(mapping.timezone))
        today = local_now.date()
        self.shop_authorization_id = auth.pk
        binding = {"actor_id": actor_id, "mapping_id": mapping.pk,
                   "shop_binding": sha256(f"{job.tenant_id}:{mapping.pk}:{auth.pk}".encode()).hexdigest(),
                   "timezone": mapping.timezone}
        frozen = (getattr(job, "_frozen_sync_scope", None) or {}).get("gmv_max_plan")
        if frozen is None:
            offsets = (1,) if job.schedule_type == "interval" and local_now.hour != 3 else (2, 1)
            days = [(today - timedelta(days=n)).isoformat() for n in offsets]
        else:
            if any(frozen.get(k) != v for k, v in binding.items()):
                raise ValidationError("GMV_MAX_SOURCE_CHANGED")
            days = frozen.get("days")
            if not isinstance(days, list) or len(days) not in (1, 2):
                raise ValidationError("GMV_MAX_INVALID_WINDOW")
            parsed = [date.fromisoformat(day) for day in days]
            if (not today - timedelta(days=30) <= parsed[0] <= parsed[-1] < today
                    or (len(parsed) == 2 and parsed[1] - parsed[0] != timedelta(days=1))):
                raise ValidationError("GMV_MAX_INVALID_WINDOW")
        self.scope = {"gmv_max_plan": {**binding, "days": days}}

    def release(self):
        # Each day owns and releases its Ads tenant lease in run_day.
        pass

    def fetch_page(self, job, cursor_value=None):
        run = self._require_run()
        plan = self.scope["gmv_max_plan"]
        continuation = f"gmv:{run.run_id}:1"
        if cursor_value not in (None, "", continuation) or (cursor_value and len(plan["days"]) == 1):
            raise ValidationError("GMV_MAX_CURSOR_INVALID")
        day = plan["days"][int(cursor_value == continuation)]
        key = f"gmv_max:{day}"

        def guard(*, lock=False):
            jobs = SyncJob.objects.select_for_update() if lock else SyncJob.objects
            active = jobs.filter(pk=job.pk, tenant_id=job.tenant_id, ads_mapping_id=plan["mapping_id"],
                                 is_enabled=True, status="running", lock_token=run.run_id,
                                 lock_expires_at__gt=timezone.now()).first()
            if active is None or (active.sync_scope.get("gmv_max") or {}).get("actor_id") != plan["actor_id"]:
                raise AdsExecutionStopped("GMV Max job authorization or lease changed.")

        if not CollectionUnitReceipt.objects.filter(sync_run=run, unit_key=key).exists():
            def receipt(result):
                self._receipt(job, key, {"date": day, "campaign_count": result["campaign_count"],
                                         "created": result["created"], "audit_id": result["audit_id"]})
            run_day(actor=self.actor, mapping_id=plan["mapping_id"], day=date.fromisoformat(day),
                    commit=True, guard_job=guard, commit_receipt=receipt,
                    expected_shop_authorization_id=self.shop_authorization_id)
        return {"records": [{"unit_key": key}], "next_cursor": continuation if not cursor_value and len(plan["days"]) == 2 else ""}

    def after_page_persist(self, job, page, results):
        run = self._require_run()
        receipts = list(CollectionUnitReceipt.objects.filter(sync_run=run).values_list("result", flat=True))
        run.fetched_count = sum(r["campaign_count"] for r in receipts)
        run.created_count = sum(bool(r["created"]) for r in receipts)
        run.skipped_count = len(receipts) - run.created_count
        run.masked_log = {**(run.masked_log or {}), "gmv_max_progress": {
            "count_unit": "gmv_max_campaign_day", "snapshot_count": len(receipts),
            "completed_days": sorted(r["date"] for r in receipts),
        }}
