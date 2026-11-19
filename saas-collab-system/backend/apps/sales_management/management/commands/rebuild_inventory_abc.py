"""Management command source for the daily inventory ABC snapshot worker."""

from django.contrib.auth import get_user_model

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.masterdata.models import CountrySiteMaster, InventoryABCRun, StoreMaster
from apps.permissions.role_catalog import effective_administrator_bindings
from apps.tenants.models import Tenant
from apps.sales_management.abc_service import calculate_country


class Command(BaseCommand):
    help = "Rebuild bounded inventory ABC snapshots for active country/store scopes."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--country-code", type=str, default="")
        parser.add_argument("--actor-id", type=int)
        parser.add_argument("--queued-only", action="store_true")

    def _actor(self, tenant_id, actor_id=None):
        tenant = Tenant.objects.filter(pk=tenant_id).first()
        if tenant is None:
            raise CommandError("Tenant does not exist.")
        platform_users = get_user_model().objects.filter(tenant_id=tenant_id, is_active=True, is_superuser=True, user_type="internal")
        if actor_id:
            platform_users = platform_users.filter(pk=actor_id)
        platform_user = platform_users.order_by("pk").first()
        if platform_user:
            return platform_user
        administrators = effective_administrator_bindings(tenant).filter(user__user_type="internal")
        if actor_id:
            administrators = administrators.filter(user_id=actor_id)
        user_role = administrators.select_related("user").order_by("user_id").first()
        if user_role:
            return user_role.user
        fallback = get_user_model().objects.filter(tenant_id=tenant_id, is_active=True, is_superuser=True, user_type="internal")
        if actor_id:
            fallback = fallback.filter(pk=actor_id)
        platform_admin = fallback.order_by("pk").first()
        if platform_admin:
            return platform_admin
        if actor_id:
            raise CommandError("The selected actor is not an effective internal tenant administrator.")
        raise CommandError("No active internal tenant administrator is available for this tenant.")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        country_code = (options.get("country_code") or "").strip().upper()
        actor = self._actor(tenant_id, options.get("actor_id"))
        # Express active-store existence without multiplying countries by stores.
        active_store = StoreMaster.objects.filter(
            tenant_id=tenant_id,
            status="active",
            country_code__iexact=OuterRef("country_code"),
        )
        countries = CountrySiteMaster.objects.filter(
            tenant_id=tenant_id,
            status="active",
        ).annotate(has_active_store=Exists(active_store)).filter(has_active_store=True)
        if country_code:
            countries = countries.filter(country_code__iexact=country_code)
        if options["queued_only"]:
            stale_before = timezone.now() - timedelta(hours=2)
            InventoryABCRun.objects.filter(
                tenant_id=tenant_id,
                status="building",
                created_at__lt=stale_before,
            ).update(status="queued", issues=[], completed_at=None)
            runs = InventoryABCRun.objects.filter(
                tenant_id=tenant_id,
                status="queued",
                country__status="active",
                country__country_code__in=countries.values("country_code"),
            ).select_related("country").order_by("cutoff_date", "country_id", "pk")
            if country_code:
                runs = runs.filter(country__country_code__iexact=country_code)
            work = [(run.country, run) for run in runs]
        else:
            work = [(country, None) for country in countries.order_by("country_code", "pk")]

        if not work:
            self.stdout.write("No eligible ABC country runs.")
            return
        succeeded = failed = 0
        for country, run in work:
            try:
                result = calculate_country(actor, country, run=run)
                succeeded += 1
                self.stdout.write(f"{country.country_code}: {result.status}")
            except Exception as exc:
                failed += 1
                if run and run.status in {"queued", "building"}:
                    run.status = "failed"
                    run.issues = [f"worker_preflight_error:{type(exc).__name__}"]
                    run.completed_at = timezone.now()
                    run.save(update_fields=["status", "issues", "completed_at"])
                # Service records a bounded issue on the run. Do not print fact
                # payloads, query parameters, or raw third-party responses.
                self.stderr.write(f"{country.country_code}: calculation failed ({type(exc).__name__})")
        self.stdout.write(f"ABC country runs complete: {succeeded} succeeded, {failed} failed.")
        if failed:
            raise CommandError(f"{failed} ABC country run(s) failed.")
