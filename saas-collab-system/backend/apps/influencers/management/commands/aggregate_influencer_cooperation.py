from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Tenant

from ...cooperation_aggregation import aggregate_influencer_cooperation


class Command(BaseCommand):
    help = "Rebuild tenant-scoped automatic influencer cooperation aggregates."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int)
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        tenant_id = options.get("tenant_id")
        if tenant_id:
            tenants = Tenant.objects.filter(pk=tenant_id)
            if not tenants.exists():
                raise CommandError("Tenant does not exist.")
        else:
            tenants = Tenant.objects.all()
        totals = {"tenants": 0, "profiles_created": 0, "profiles_updated": 0, "profiles_unchanged": 0}
        for tenant in tenants.iterator():
            result = aggregate_influencer_cooperation(
                tenant=tenant,
                batch_size=options["batch_size"],
            )
            totals["tenants"] += 1
            for key in ("profiles_created", "profiles_updated", "profiles_unchanged"):
                totals[key] += result[key]
        self.stdout.write(
            "tenants={tenants} profiles_created={profiles_created} "
            "profiles_updated={profiles_updated} profiles_unchanged={profiles_unchanged}".format(**totals)
        )
