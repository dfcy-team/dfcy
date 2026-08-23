from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Tenant

from ...attribution import refresh_order_attributions


class Command(BaseCommand):
    help = "Refresh deterministic BD owner attribution snapshots from imported order facts."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int)
        parser.add_argument("--attribution", "--mode", dest="attribution", choices=("strict", "fallback"), default="strict")
        parser.add_argument("--rule-version")

    def handle(self, *args, **options):
        tenants = Tenant.objects.filter(pk=options["tenant_id"]) if options.get("tenant_id") else Tenant.objects.all()
        if options.get("tenant_id") and not tenants.exists():
            raise CommandError("Tenant does not exist.")
        totals = {"created": 0, "updated": 0, "noop": 0, "rejected": 0, "deleted": 0}
        rule_version = options.get("rule_version") or None
        for tenant in tenants.iterator():
            result = refresh_order_attributions(
                tenant=tenant,
                attribution=options["attribution"],
                rule_version=rule_version,
            )
            for key in totals:
                totals[key] += result[key]
        self.stdout.write(
            "created={created} updated={updated} noop={noop} rejected={rejected} deleted={deleted}".format(**totals)
        )
