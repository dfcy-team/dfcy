from django.core.management.base import BaseCommand

from apps.masterdata.country_seed import seed_country_sites
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Seed common cross-border country/site records for existing tenants."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="tenant_code", help="Only seed the tenant with this code.")
        parser.add_argument("--dry-run", action="store_true", help="Report changes without writing rows.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.all().order_by("id")
        if options.get("tenant_code"):
            tenants = tenants.filter(code=options["tenant_code"])
        total = {"created": 0, "updated": 0, "skipped": 0, "total": 0}
        for tenant in tenants.iterator():
            result = seed_country_sites(tenant=tenant, dry_run=options["dry_run"])
            for key in total:
                total[key] += result[key]
            self.stdout.write(f"{tenant.code}: {result}")
        self.stdout.write(self.style.SUCCESS(f"Country site seed complete: {total}"))
