"""Register GMV Max mappings as disabled native synchronization tasks."""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.gmv_max_job import TikTokGmvMaxAdapter
from apps.integrations.gmv_max_relationship import probe_relationship
from apps.integrations.gmv_max_schedule import safe_error_code
from apps.integrations.models import SyncJob, TikTokAdsAdvertiserMapping


class Command(BaseCommand):
    help = "Validate existing GMV Max authorizations and register disabled native tasks."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--mapping-id", type=int, action="append", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            pk=options["actor_id"], tenant_id=options["tenant_id"], is_active=True).first()
        if actor is None:
            raise CommandError("GMV Max actor is unavailable for this tenant.")
        mapping_ids = sorted(set(options["mapping_id"]))
        for index, mapping_id in enumerate(mapping_ids):
            result = {"mapping_id": mapping_id}
            try:
                mapping = TikTokAdsAdvertiserMapping.objects.select_related("integration_config").get(
                    pk=mapping_id, tenant_id=actor.tenant_id, enabled=True,
                    integration_config__platform="tiktok", integration_config__environment="production")
                minutes = (2 * index) % 60
                clock = f"{2 + index // 30:02d}:{minutes:02d}"
                job = SyncJob(tenant_id=actor.tenant_id, integration_config=mapping.integration_config,
                              ads_mapping=mapping, resource_type=SyncJob.ResourceType.GMV_MAX_REPORT,
                              schedule_type=SyncJob.ScheduleType.DAILY, sync_scope={
                                  "execution_mode": "live_readonly", "gmv_max": {"actor_id": actor.pk},
                                  "schedule": {"timezone": "Asia/Shanghai", "local_time": clock,
                                               "local_times": [clock], "catch_up": "skip",
                                               "execution_budget_seconds": 300},
                              })
                job.full_clean(validate_unique=False, validate_constraints=False)
                adapter = TikTokGmvMaxAdapter(mapping.integration_config)
                adapter.validate_configuration(job)
                relation = probe_relationship(actor=actor, mapping_id=mapping.pk)
                if relation["relationship_status"] != "current_verified":
                    result.update(status="blocked", reason="GMV_MAX_RELATIONSHIP_UNVERIFIED")
                elif options["apply"]:
                    with transaction.atomic():
                        TikTokAdsAdvertiserMapping.objects.select_for_update().get(
                            pk=mapping.pk, tenant_id=actor.tenant_id, updated_at=mapping.updated_at)
                        saved = SyncJob.objects.filter(tenant_id=actor.tenant_id, ads_mapping=mapping,
                                                       resource_type=job.resource_type).first()
                        if saved is None:
                            job.save()
                            saved = job
                        result.update(status="registered", job_id=saved.pk, enabled=saved.is_enabled)
                else:
                    result.update(status="eligible", schedule=clock)
            except Exception as exc:
                result.update(status="blocked", reason=safe_error_code(exc))
            self.stdout.write(json.dumps(result))
