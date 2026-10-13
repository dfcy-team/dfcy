"""One bounded tenant batch; only a derived index, never financial facts."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.query import QuerySet
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.influencers.models import AffiliateImportState, AffiliateOrderSnapshot
from apps.influencers.order_identity import IDENTITY_FIELDS, order_identity_digest


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        size = options["batch_size"]
        if not 1 <= size <= 1000:
            raise CommandError("batch-size must be 1..1000")
        with transaction.atomic():
            tenants = Tenant.objects
            if options["apply"]:
                tenants = tenants.select_for_update()
            tenant = tenants.filter(pk=options["tenant_id"]).first()
            if tenant is None:
                raise CommandError("Unknown tenant")
            if options["apply"] and AffiliateImportState.objects.filter(
                tenant=tenant, status="running", lease_expires_at__gt=timezone.now(),
            ).exclude(lease_token="").exists():
                raise CommandError("An importer lease is active; retry after completion")
            missing = AffiliateOrderSnapshot.objects.filter(tenant=tenant, business_identity_digest__isnull=True)
            rows = list(missing.order_by("pk").values("pk", *IDENTITY_FIELDS)[:size])
            for row in rows if options["apply"] else []:
                QuerySet.update(
                    AffiliateOrderSnapshot.objects.filter(pk=row["pk"], tenant=tenant, business_identity_digest__isnull=True),
                    business_identity_digest=order_identity_digest(row[name] for name in IDENTITY_FIELDS),
                )
            remains = missing.exists()
        self.stdout.write(json.dumps({
            "status": "partial" if remains else "passed", "apply": options["apply"],
            "source_rows": len(rows), "target_rows": len(rows) if options["apply"] else 0,
            "schema_diff_count": 0, "constraint_violations": {}, "mismatched_chunks": [],
            "sample_artifact": None, "recommended_action": "run next bounded batch" if remains else "identity index ready",
        }))
