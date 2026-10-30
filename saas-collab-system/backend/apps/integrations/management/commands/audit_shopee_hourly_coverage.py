import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from django.db.models.functions import Cast
from django.db.models import IntegerField
from rest_framework.exceptions import ValidationError

from apps.integrations.models import ShopeeAdvertisingRecord, SyncJob
from apps.integrations.shopee_advertising import advertising_sync_scope


class Command(BaseCommand):
    help = "Read-only, bounded audit of Shopee shop-hourly advertising coverage."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", required=True, type=int)
        parser.add_argument("--store-id", required=True, type=int)
        parser.add_argument("--date-from", required=True)
        parser.add_argument("--date-to", required=True)

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options["date_from"])
            end = date.fromisoformat(options["date_to"])
        except ValueError as exc:
            raise CommandError("Dates must use YYYY-MM-DD.") from exc
        if end < start or (end - start).days >= 7:
            raise CommandError("The inclusive date range must contain 1 to 7 days.")

        jobs = SyncJob.objects.filter(
            tenant_id=options["tenant_id"],
            store_authorization__store_id=options["store_id"],
            store_authorization__platform="shopee",
            resource_type=SyncJob.ResourceType.ADVERTISING_REPORT,
        ).select_related("integration_config", "store_authorization")
        job_summaries = []
        for job in jobs:
            try:
                scope = advertising_sync_scope(job.integration_config, job.sync_scope, job.store_authorization)
                datasets = scope["advertising_datasets"]
            except ValidationError:
                # Invalid or stale configuration is reported as an unresolved dataset set.
                datasets = []
            latest_run = job.runs.order_by("-enqueued_at", "-started_at", "-id").only("id", "status").first()
            job_summaries.append({
                "id": job.id,
                "enabled": job.is_enabled,
                "schedule": job.schedule_type,
                "shop_hourly_enabled": "shop_hourly" in datasets,
                "recent_run": ({"id": latest_run.id, "status": latest_run.status} if latest_run else None),
            })

        rows = (ShopeeAdvertisingRecord.objects.filter(
            tenant_id=options["tenant_id"], store_id=options["store_id"],
            kind="shop_hourly", report_date__gte=start, report_date__lte=end,
        ).annotate(hour=Cast("data__hour", IntegerField()))
            .values("report_date", "hour")
            .annotate(record_count=Count("id"), missing_expense_count=Count("id", filter=Q(data__expense__isnull=True)))
            .order_by("report_date", "hour"))
        payload = {
            "tenant_id": options["tenant_id"], "store_id": options["store_id"],
            "date_from": start.isoformat(), "date_to": end.isoformat(),
            "jobs": job_summaries,
            "coverage": [
                {"date": row["report_date"].isoformat(), "hour": row["hour"],
                 "record_count": row["record_count"], "missing_expense_count": row["missing_expense_count"]}
                for row in rows
            ],
            "completeness": "unverified; sparse hourly records alone do not prove completeness",
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
