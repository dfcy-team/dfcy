from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.models import PlatformIntegrationConfig
from apps.integrations.platform_schema_service import get_platform_schema
from apps.tenants.models import Tenant


SUPPORTED_PLATFORMS = ("lazada", "shopee", "tiktok")


class Command(BaseCommand):
    help = "Dry-run or repair invalid marketplace contract versions for one tenant."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--config-id", type=int)
        parser.add_argument("--platform", choices=SUPPORTED_PLATFORMS)
        parser.add_argument("--apply", action="store_true", help="Persist the proposed changes.")

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        if not Tenant.objects.filter(id=tenant_id).exists():
            raise CommandError(f"Tenant {tenant_id} does not exist.")

        queryset = PlatformIntegrationConfig.objects.filter(
            tenant_id=tenant_id,
            platform__in=SUPPORTED_PLATFORMS,
        ).order_by("id")
        if options.get("config_id"):
            queryset = queryset.filter(id=options["config_id"])
        if options.get("platform"):
            queryset = queryset.filter(platform=options["platform"])

        proposals = []
        for config in queryset:
            allowed = get_platform_schema(config.platform, environment=config.environment)["contract_versions"]
            expected = allowed[0]
            if config.contract_version not in allowed:
                proposals.append((config.id, config.platform, config.contract_version, expected))

        mode = "APPLY" if options["apply"] else "DRY-RUN"
        self.stdout.write(f"mode={mode} tenant_id={tenant_id} proposals={len(proposals)}")
        for config_id, platform, current, expected in proposals:
            self.stdout.write(
                f"config_id={config_id} platform={platform} current={current or '<blank>'} proposed={expected}"
            )

        if not options["apply"] or not proposals:
            return

        with transaction.atomic():
            for config_id, platform, _current, expected in proposals:
                config = PlatformIntegrationConfig.objects.select_for_update().get(
                    id=config_id,
                    tenant_id=tenant_id,
                    platform=platform,
                )
                allowed = get_platform_schema(config.platform, environment=config.environment)["contract_versions"]
                if config.contract_version in allowed:
                    continue
                config.contract_version = expected
                config.config_version += 1
                config.save(update_fields=["contract_version", "config_version", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"updated={len(proposals)}"))
