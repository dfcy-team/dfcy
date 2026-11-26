import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from apps.tenants.models import Tenant
from django.contrib.auth import get_user_model
from apps.products.monthly_cost_imports import preview_monthly_cost_csv


class Command(BaseCommand):
    help = "Preview monthly product cost history CSV (use --apply to write)"

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true", help="Apply the validated import")

    def handle(self, *args, **options):
        path = Path(options["csv_path"])
        try:
            tenant = Tenant.objects.get(pk=options["tenant_id"])
            actor = get_user_model().objects.get(pk=options["actor_id"], tenant=tenant, is_active=True, is_staff=True)
            result = preview_monthly_cost_csv(content=path.read_bytes(), tenant=tenant, actor=actor, apply=options["apply"])
        except (OSError, Tenant.DoesNotExist, get_user_model().DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        if not result["valid"]:
            raise CommandError("CSV validation failed")
