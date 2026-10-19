"""Create an isolated TikTok Shop mock sync in a chosen administrator's tenant."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.adapters import MockPlatformAdapter
from apps.integrations.models import PlatformIntegrationConfig, SyncJob
from apps.integrations.sync_services import run_sync_job


ALIAS = "tiktok-shop-readonly-demo-20260929"
SCOPE = {"scenario": "tiktok_shop_readonly"}
RUN_KEY = "tiktok-shop-readonly-demo-20260929-v1"


class Command(BaseCommand):
    help = "Preview or run an isolated TikTok Shop read-only mock; never calls TikTok or writes commerce facts."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["username"], is_active=True).first()
        if not user or not user.is_superuser or not user.tenant_id:
            raise CommandError("An active tenant-bound superuser is required.")

        existing = PlatformIntegrationConfig.objects.filter(
            tenant_id=user.tenant_id,
            platform="mock",
            environment=PlatformIntegrationConfig.Environment.MOCK,
            account_alias=ALIAS,
        ).first()
        if existing and (existing.network_enabled or existing.sync_write_enabled or existing.sync_read_enabled):
            raise CommandError("Existing demo config has network or sync access enabled; refusing to reuse it.")

        self.stdout.write(
            f"tenant_id={user.tenant_id} scenario=tiktok_shop_readonly "
            f"existing_config_id={existing.id if existing else 'none'} "
            "network=false business_writes=false"
        )
        if not options["apply"]:
            self.stdout.write("Dry run only. Pass --apply to create and run the mock task.")
            return

        with transaction.atomic():
            config, _ = PlatformIntegrationConfig.objects.get_or_create(
                tenant_id=user.tenant_id,
                platform="mock",
                environment=PlatformIntegrationConfig.Environment.MOCK,
                account_alias=ALIAS,
                defaults={
                    "status": PlatformIntegrationConfig.Status.CONFIGURED,
                    "created_by": user,
                },
            )
            if config.network_enabled or config.sync_read_enabled or config.sync_write_enabled:
                raise CommandError("Demo config must not enable network or platform synchronization.")
            job, _ = SyncJob.objects.get_or_create(
                tenant_id=user.tenant_id,
                integration_config=config,
                resource_type=SyncJob.ResourceType.MOCK_RECORD,
                defaults={"schedule_type": SyncJob.ScheduleType.MANUAL, "sync_scope": SCOPE},
            )
            if (
                job.sync_scope != SCOPE
                or job.schedule_type != SyncJob.ScheduleType.MANUAL
                or not job.is_enabled
                or job.store_authorization_id
                or job.warehouse_authorization_id
            ):
                raise CommandError("Existing demo job is not an isolated manual mock task.")

        run, created = run_sync_job(job, adapter=MockPlatformAdapter(), idempotency_key=RUN_KEY)
        self.stdout.write(
            f"config_id={config.id} job_id={job.id} run_id={run.id} "
            f"created={created} status={run.status} fetched={run.fetched_count} "
            f"skipped={run.skipped_count}"
        )
