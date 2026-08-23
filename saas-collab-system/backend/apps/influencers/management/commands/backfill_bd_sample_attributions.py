from django.core.management.base import BaseCommand

from apps.tenants.models import Tenant

from ...attribution import backfill_sample_attributions


class Command(BaseCommand):
    help = "Backfill frozen BD sample attribution facts without guessing current ownership."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int)

    def handle(self, *args, **options):
        tenant = None
        if options.get("tenant_id") is not None:
            tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
            if tenant is None:
                self.stderr.write("tenant_not_found")
                return
        result = backfill_sample_attributions(tenant=tenant)
        self.stdout.write(f"created={result['created']} existing={result['existing']} legacy_inferred=true")
