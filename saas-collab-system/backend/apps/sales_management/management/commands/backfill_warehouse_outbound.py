from django.core.management.base import BaseCommand
from django.db import transaction

from apps.sales_management.outbound_movements import replace_shipment_lines, shipment_projection
from apps.sales_management.warehouse_order_models import OrderWarehouseLookup


class Command(BaseCommand):
    help = "Project saved WMS package snapshots into outbound lines. Reports counts by default."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", required=True, type=int)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        candidates = OrderWarehouseLookup.objects.filter(
            order__tenant_id=tenant_id, warehouse__tenant_id=tenant_id, snapshot_at__isnull=False,
        ).order_by("pk")
        lookup_count = line_count = piece_count = isolated = 0
        reason_counts = {}
        for pk in candidates.values_list("pk", flat=True).iterator(chunk_size=500):
            with transaction.atomic():
                selected = candidates.select_for_update() if options["apply"] else candidates
                row = selected.filter(pk=pk).first()
                if row is None:
                    continue
                packages = (row.snapshot or {}).get("packages") or []
                site_code = (row.snapshot or {}).get("site_code")
                lines, reasons = shipment_projection(packages, site_code=site_code)
                if not site_code:
                    reasons = {"missing_snapshot_site_code": 1}
                    lines = []
                isolated += sum(reasons.values())
                for reason, count in reasons.items():
                    reason_counts[reason] = reason_counts.get(reason, 0) + count
                lookup_count += 1
                line_count += len(lines)
                piece_count += sum(line[-1] for line in lines)
                if options["apply"]:
                    replace_shipment_lines(row.pk, tenant_id, row.warehouse_id, packages, site_code=site_code)
        mode = "applied" if options["apply"] else "dry-run"
        self.stdout.write(f"{mode} lookups={lookup_count} lines={line_count} pieces={piece_count} isolated={isolated} reasons={reason_counts}")
