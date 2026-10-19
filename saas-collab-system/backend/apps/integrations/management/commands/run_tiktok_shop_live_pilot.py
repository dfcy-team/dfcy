"""Run one approved, bounded TikTok Shop pilot job synchronously."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.management.commands.import_tiktok_shop_live_pilot import _complete_ph_range
from apps.integrations.models import MarketplaceStoreAuthorization, SyncJob, SyncRun
from apps.integrations.sync_services import run_sync_job, validate_manual_sync_job
from apps.masterdata.models import StoreMaster


SHOP_IDS = {"TK1PH": "7495739162492111766", "TKKJ1PH": "7495704131459517026"}
RESOURCES = (SyncJob.ResourceType.PLATFORM_PRODUCT, SyncJob.ResourceType.SALES_ORDER)


class Command(BaseCommand):
    help = "Dry-run or execute one verified VM34 TikTok Shop seven-day readonly job."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--shop", choices=SHOP_IDS, required=True)
        parser.add_argument("--resource", choices=RESOURCES, required=True)
        parser.add_argument("--attempt", type=int, default=1)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if options["tenant_id"] != 1 or options["actor"] != "yxj":
            raise CommandError("This pilot requires tenant 1 and actor yxj.")
        attempt = options["attempt"]
        if attempt < 1 or attempt > 10:
            raise CommandError("Pilot attempt must be between 1 and 10.")
        if not get_user_model().objects.filter(
            username="yxj", tenant_id=1, is_active=True, is_staff=True,
            is_superuser=True, user_type="internal",
        ).exists():
            raise CommandError("The approved yxj administrator is unavailable.")
        code = options["shop"]
        store = StoreMaster.objects.filter(
            tenant_id=1, code=code, external_store_id=SHOP_IDS[code],
        ).first()
        if store is None or store.platform.platform_type != "tiktok":
            raise CommandError("Pilot shop identity is not verified.")
        job = SyncJob.objects.select_related("integration_config", "store_authorization").filter(
            tenant_id=1, store_authorization__store=store,
            resource_type=options["resource"],
            integration_config__account_alias=f"live-pilot-{code.lower()}",
            integration_config__environment="pilot",
        ).first()
        if job is None:
            raise CommandError("Approved pilot job is unavailable.")
        config = job.integration_config
        auth = job.store_authorization
        start_at, end_at = _complete_ph_range()
        if (config.status != config.Status.VERIFIED or not config.network_enabled
                or not config.sync_read_enabled or config.sync_write_enabled
                or auth.status != MarketplaceStoreAuthorization.Status.ACTIVE
                or auth.platform_store_id != SHOP_IDS[code]
                or job.schedule_type != SyncJob.ScheduleType.MANUAL
                or job.sync_scope.get("query") != {"mode": "range", "start_at": start_at, "end_at": end_at}
                or job.is_enabled or job.status != SyncJob.Status.DISABLED):
            raise CommandError("Pilot authorization, date scope, or disabled job state changed.")
        key_prefix = f"tiktok-pilot:{code}:{options['resource']}:{start_at}"
        if attempt > 1:
            previous = SyncRun.objects.filter(
                tenant_id=1, sync_job=job, idempotency_key=f"{key_prefix}:attempt-{attempt - 1}",
            ).first()
            if previous is None or previous.status != SyncRun.Status.FAILED:
                raise CommandError("A later attempt requires the preceding attempt to have failed.")
        if not options["apply"]:
            self.stdout.write(f"DRY RUN: {code} {options['resource']} verified; no network or database writes.")
            return
        with transaction.atomic():
            locked = SyncJob.objects.select_for_update().get(pk=job.pk, tenant_id=1)
            if locked.is_enabled or locked.status != SyncJob.Status.DISABLED or locked.lock_token:
                raise CommandError("Pilot job is already active or leased.")
            locked.is_enabled = True
            locked.status = SyncJob.Status.IDLE
            validate_manual_sync_job(locked, live_only=True)
            locked.save(update_fields=["is_enabled", "status", "updated_at"])
        try:
            run, created = run_sync_job(
                locked, idempotency_key=f"{key_prefix}:attempt-{attempt}",
            )
        finally:
            SyncJob.objects.filter(pk=job.pk, tenant_id=1).update(is_enabled=False)
            SyncJob.objects.filter(
                pk=job.pk, tenant_id=1, lock_token="",
                status__in=[SyncJob.Status.IDLE, SyncJob.Status.FAILED],
            ).update(status=SyncJob.Status.DISABLED)
        if run.status != "success":
            raise CommandError(f"Pilot job ended with status {run.status}; inspect its run and alert.")
        self.stdout.write(
            f"SUCCESS: {code} {options['resource']} run_id={run.run_id} created={run.created_count} "
            f"updated={run.updated_count} skipped={run.skipped_count} reused={not created}"
        )
