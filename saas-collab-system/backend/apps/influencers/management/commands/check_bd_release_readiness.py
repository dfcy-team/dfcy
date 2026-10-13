"""Read-only, tenant/month aggregate evidence; no source rows or automatic repair."""
import json
from django.core.management.base import BaseCommand, CommandError
from apps.tenants.models import Tenant
from apps.influencers.attribution import build_bd_performance, parse_performance_date
from apps.influencers.models import AffiliateOrderSnapshot


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument("--mode", choices=["strict", "fallback"], default="strict")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
        if tenant is None:
            raise CommandError("Unknown tenant")
        report = build_bd_performance(
            tenant=tenant, start_date=parse_performance_date(options["start_date"], field="start_date"),
            end_date=parse_performance_date(options["end_date"], field="end_date"), attribution=options["mode"],
        )
        eligibility = report["eligibility_diagnostic"]
        totals = report["totals"]
        indexed = not AffiliateOrderSnapshot.objects.filter(tenant=tenant, business_identity_digest__isnull=True).exists()
        complete = indexed and eligibility["eligibility_complete"] and not eligibility["valid_unmatched_line_count"] and totals["amount_complete"] and totals["cost_complete"]
        self.stdout.write(json.dumps({
            "status": "passed" if complete else "blocked", "source_rows": eligibility["order_row_count"],
            "target_rows": eligibility["verified_attributed_line_count"], "schema_diff_count": None,
            "constraint_violations": {"identity_index_incomplete": not indexed}, "mismatched_chunks": [],
            "sample_artifact": None, "eligibility": eligibility, "diagnostics": report["zero_gmv_diagnostic"],
            "recommended_action": "review monthly reconciliation" if complete else "review missing facts/index/attributions; do not infer settlement or zero costs",
        }, ensure_ascii=False))
