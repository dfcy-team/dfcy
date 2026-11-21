"""Compare report totals with independently checked source totals."""
import csv
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from apps.masterdata.models import StoreMaster
from apps.reports.datasets import query_dataset


METRICS = {
    "sales": ("order_count", "valid_order_count", "cancelled_order_count", "gross_sales"),
    "sales_skus": ("order_count", "units_sold", "gross_sales", "unmapped_count"),
    "refunds": ("case_count", "requested_amount", "completed_amount", "unlinked_count"),
}
KEY_FIELDS = ("dataset", "store_id", "date", "currency")


def read_source(path, store_id, start, end):
    totals = {}
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            dataset, store, day, currency = (row[key] for key in KEY_FIELDS)
            if int(store) != store_id or not start <= date.fromisoformat(day) <= end:
                raise ValueError("Source totals must match the requested store and dates.")
            key = (dataset, store_id, day, currency)
            if not currency or key in totals:
                raise ValueError("Blank currency or duplicate source group.")
            values = {metric: Decimal(row[metric]) for metric in METRICS[dataset]}
            if any(not value.is_finite() for value in values.values()):
                raise ValueError("Source metric must be finite.")
            totals[key] = values
    if not totals:
        raise ValueError("Source file has no groups.")
    return totals


class Command(BaseCommand):
    help = (
        "Compare uncached sales, SKU sales and refund reports with a CSV of independently "
        "verified source totals. Use one row per dataset, store_id, local date and currency. "
        "Supply the applicable metric columns using report metric keys."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--store-id", type=int, required=True)
        parser.add_argument("--date-from", type=date.fromisoformat, required=True)
        parser.add_argument("--date-to", type=date.fromisoformat, required=True)
        parser.add_argument("--source-csv", required=True)

    def handle(self, *args, **options):
        start, end = options["date_from"], options["date_to"]
        store = options["store_id"]
        if end < start:
            raise CommandError("date-to must be on or after date-from.")
        try:
            source = read_source(options["source_csv"], store, start, end)
        except (OSError, KeyError, TypeError, ValueError, InvalidOperation, csv.Error) as error:
            raise CommandError("Invalid source totals CSV.") from error
        user = get_user_model().objects.filter(pk=options["user_id"], is_active=True).first()
        if user is None or user.tenant_id is None:
            raise CommandError("An active tenant user is required.")
        if not StoreMaster.objects.filter(pk=store, tenant_id=user.tenant_id).exists():
            raise CommandError("The store must belong to the report user tenant.")
        request = SimpleNamespace(user=user, query_params={})
        target = {}
        for offset in range((end - start).days + 1):
            day_text = (start + timedelta(days=offset)).isoformat()
            for dataset, metrics in METRICS.items():
                try:
                    report = query_dataset(request, {
                        "dataset": dataset,
                        "dimensions": list(KEY_FIELDS[1:]),
                        "metrics": list(metrics),
                        "filters": {"store_id": str(store), "date_from": day_text, "date_to": day_text},
                    }, use_cache=False)
                except APIException as error:
                    raise CommandError(f"Report query failed for {dataset}.") from error
                if report["truncated"]:
                    raise CommandError(f"Report groups truncated for {dataset} on {day_text}.")
                for row in report["rows"]:
                    key = (dataset, row["store_id"], str(row["date"]), row["currency"])
                    target[key] = {
                        metric: Decimal(str(row[metric])) if row[metric] is not None else None
                        for metric in metrics
                    }

        mismatches = [key for key in source.keys() | target.keys() if source.get(key) != target.get(key)]
        self.stdout.write(json.dumps({
            "status": "failed" if mismatches else "passed",
            "source_groups": len(source),
            "report_groups": len(target),
            "mismatched_groups": len(mismatches),
            "samples": [
                {
                    "group": key,
                    "source": source.get(key),
                    "report": target.get(key),
                }
                for key in sorted(mismatches, key=str)[:20]
            ],
        }, default=str))
        if mismatches:
            raise CommandError("Sales and refund reconciliation found differences.")
