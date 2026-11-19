"""Register nightly standard inbound sync jobs for verified Jifeng warehouses."""

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.jifeng_inbound import JifengInboundAdapter
from apps.integrations.models import SyncJob, WarehouseAuthorization
from apps.integrations.scheduler import calculate_next_run_at
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Preview or register a daily 02:00 Asia/Shanghai inbound sync per verified Jifeng warehouse."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            pk=options["actor_id"], tenant_id=options["tenant_id"], is_active=True,
        ).first()
        if not actor or not check_user_permission(actor, "integrations.manage"):
            raise CommandError("A same-tenant integrations manager is required.")

        authorizations = WarehouseAuthorization.objects.filter(
            tenant_id=actor.tenant_id, provider="jifeng_wms", status="active",
            warehouse__tenant_id=actor.tenant_id, warehouse__status="active",
            integration_config__tenant_id=actor.tenant_id,
            integration_config__platform="jifeng_wms",
            integration_config__environment="production",
            integration_config__sync_write_enabled=False,
        ).select_related("warehouse", "integration_config").order_by("pk")

        results = []
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=actor.tenant_id)
            seen_warehouses = set()
            for auth in authorizations:
                if not integration_values_allowed(
                    actor, "integrations.manage", platform=auth.provider, environment="production",
                    regions=[auth.external_warehouse_region], config_id=auth.integration_config_id,
                    warehouse_id=auth.warehouse_id,
                ):
                    continue
                if auth.warehouse_id in seen_warehouses:
                    raise CommandError("Multiple eligible authorizations for one warehouse require review.")
                seen_warehouses.add(auth.warehouse_id)
                existing = list(SyncJob.objects.filter(
                    tenant_id=actor.tenant_id, resource_type=SyncJob.ResourceType.INBOUND,
                    warehouse_authorization__warehouse_id=auth.warehouse_id,
                )[:2])
                if len(existing) > 1:
                    raise CommandError("Multiple inbound jobs for one warehouse require review.")
                if existing:
                    results.append({"warehouse_id": auth.warehouse_id, "job_id": existing[0].pk, "status": "existing"})
                    continue

                job = SyncJob(
                    tenant_id=actor.tenant_id, integration_config=auth.integration_config,
                    warehouse_authorization=auth, resource_type=SyncJob.ResourceType.INBOUND,
                    schedule_type="daily", is_enabled=True, max_retry_count=2,
                    sync_scope={"execution_mode": "live_readonly", "schedule": {
                        "local_time": "02:00", "timezone": "Asia/Shanghai", "catch_up": "run_once",
                    }},
                )
                job.full_clean()
                JifengInboundAdapter(auth.integration_config).validate_configuration(job)
                job.next_run_at = calculate_next_run_at(job)
                if options["apply"]:
                    job.save()
                results.append({
                    "warehouse_id": auth.warehouse_id, "job_id": job.pk,
                    "status": "registered" if job.pk else "eligible",
                    "next_run_at": job.next_run_at.isoformat(),
                })
        if not results:
            raise CommandError("No eligible warehouse authorizations.")
        self.stdout.write(json.dumps(results))
