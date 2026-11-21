import json
import os
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Min, Q
from django.utils import timezone
from apps.commerce.models import SalesOrderItem
from apps.products.models import ProductSKU, ProductSPU


class Command(BaseCommand):
    help = "Backfill earliest known paid sale dates from retained sales facts. Default is dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-path")
        parser.add_argument("--recent-hours", type=int)

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        if options["apply"] and not options["audit_path"]:
            raise CommandError("--apply requires --audit-path")
        valid_source = Q(sales_order__source_run__status="success", sales_order__source_run__failed_count=0) | Q(sales_order__internal_sync_batch__status__in=["success", "completed"])
        facts = SalesOrderItem.objects.filter(
            sales_order__tenant_id=tenant_id, quantity__gt=0,
            sales_order__paid_at_utc__isnull=False,
            sales_order__paid_at_utc__lte=timezone.now(),
            sales_order__normalized_status__in=["confirmed", "fulfilled", "completed"],
        ).filter(valid_source)
        if options.get("recent_hours"):
            since = timezone.now() - timedelta(hours=options["recent_hours"])
            facts = facts.filter(Q(updated_at__gte=since) | Q(sales_order__source_run__finished_at__gte=since) | Q(sales_order__updated_at_utc__gte=since))
        sku_dates, spu_dates = {}, {}
        invalid_timezone_groups = 0
        for field, dates in [("internal_sku_id", sku_dates), ("internal_spu_id", spu_dates)]:
            scoped_facts = facts.filter(internal_sku__isnull=True) if field == "internal_spu_id" else facts
            groups = scoped_facts.filter(**{field + "__isnull": False}).order_by().values(field, "sales_order__store__timezone").annotate(first_paid=Min("sales_order__paid_at_utc"))
            for row in groups.iterator(chunk_size=1000):
                try:
                    tz = ZoneInfo(row["sales_order__store__timezone"] or "")
                except (ValueError, ZoneInfoNotFoundError):
                    invalid_timezone_groups += 1
                    continue
                day = row["first_paid"].astimezone(tz).date()
                key = row[field]
                dates[key] = min(dates.get(key, day), day)
        skus = ProductSKU.objects.filter(spu__tenant_id=tenant_id).only("pk", "spu_id", "first_sale_date")
        sku_changes = []
        for sku in skus.iterator(chunk_size=1000):
            observed = sku_dates.get(sku.pk)
            effective = min(d for d in [observed, sku.first_sale_date] if d is not None) if observed or sku.first_sale_date else None
            if effective is not None:
                spu_dates[sku.spu_id] = min(spu_dates.get(sku.spu_id, effective), effective)
            if observed and (sku.first_sale_date is None or observed < sku.first_sale_date):
                sku_changes.append((sku.pk, observed))
        spu_changes = [(spu.pk, spu_dates[spu.pk]) for spu in ProductSPU.objects.filter(tenant_id=tenant_id).only("pk", "first_sale_date") if spu.pk in spu_dates and (spu.first_sale_date is None or spu_dates[spu.pk] < spu.first_sale_date)]
        report = {"tenant_id": tenant_id, "mode": "apply" if options["apply"] else "dry_run", "matched_skus": len(sku_dates), "sku_candidates": len(sku_changes), "spu_candidates": len(spu_changes), "invalid_timezone_groups": invalid_timezone_groups}
        if options["apply"]:
            audit_path = Path(options["audit_path"])
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("x", encoding="utf-8") as audit:
                for model, changes, tenant_filter, label in [(ProductSKU, sku_changes, {"spu__tenant_id": tenant_id}, "sku"), (ProductSPU, spu_changes, {"tenant_id": tenant_id}, "spu")]:
                    written = 0
                    for start in range(0, len(changes), 500):
                        pending = dict(changes[start:start + 500])
                        with transaction.atomic():
                            rows = list(model.objects.select_for_update().filter(pk__in=pending, **tenant_filter))
                            update_rows = []
                            for row in rows:
                                day = pending[row.pk]
                                if row.first_sale_date is not None and row.first_sale_date <= day:
                                    continue
                                audit.write(json.dumps({"model": label, "id": row.pk, "before": str(row.first_sale_date) if row.first_sale_date else None, "after": str(day)}) + "\n")
                                row.first_sale_date = day
                                update_rows.append(row)
                            audit.flush()
                            os.fsync(audit.fileno())
                            model.objects.bulk_update(update_rows, ["first_sale_date"], batch_size=500)
                            written += len(update_rows)
                    report[label + "_updated"] = written
            report["audit_path"] = str(audit_path)
        self.stdout.write(json.dumps(report))
