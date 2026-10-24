from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant
from apps.sales_management.nine_snapshot_capture import capture_store


class Command(BaseCommand):
    help = "Dry-run or capture observed store-local 09:00 sales snapshots once."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--store-id", type=int)
        parser.add_argument("--write", action="store_true", help="Persist snapshots; omitted means dry-run.")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        if not Tenant.objects.filter(pk=tenant_id).exists():
            raise CommandError("Tenant does not exist.")
        stores = StoreMaster.objects.filter(tenant_id=tenant_id).order_by("pk")
        if options["store_id"] is not None:
            stores = stores.filter(pk=options["store_id"])
            if not stores.exists():
                raise CommandError("Store does not belong to the requested tenant.")

        for store in stores:
            now = timezone.now()
            zone_name = str(store.timezone or "").strip()
            try:
                local_now = now.astimezone(ZoneInfo(zone_name)) if zone_name else None
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                local_now = None
            eligible = bool(local_now and (local_now.hour == 9 and local_now.minute < 5))
            if not eligible:
                self.stdout.write(f"store={store.pk} skipped (outside 09:00-09:05 or timezone unavailable)")
                continue
            if not options["write"]:
                self.stdout.write(f"store={store.pk} eligible; dry-run, no snapshot written")
                continue
            snapshot, created = capture_store(store, now=now)
            if snapshot is None:
                self.stdout.write(f"store={store.pk} skipped (invalid timezone or capture window)")
            else:
                self.stdout.write(f"store={store.pk} snapshot={snapshot.pk} created={str(created).lower()}")
