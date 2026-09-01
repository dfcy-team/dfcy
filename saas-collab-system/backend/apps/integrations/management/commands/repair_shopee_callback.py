from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import CustomUser
from apps.integrations.models import IntegrationAuditLog, PlatformIntegrationConfig
from apps.integrations.serializers import validate_marketplace_callback_url


class Command(BaseCommand):
    help = "Dry-run or repair one exact production Shopee callback URL without touching credentials."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-code", required=True)
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--config-id", type=int)
        selector.add_argument("--account-alias")
        parser.add_argument("--actor-username", required=True)
        parser.add_argument("--callback-url", required=True)
        parser.add_argument("--expected-current", default=None)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        callback_url = validate_marketplace_callback_url(
            options["callback_url"],
            environment=PlatformIntegrationConfig.Environment.PRODUCTION,
            platform="shopee",
        )
        filters = {
            "tenant__code": options["tenant_code"],
            "platform": "shopee",
            "environment": PlatformIntegrationConfig.Environment.PRODUCTION,
        }
        if options.get("config_id") is not None:
            filters["id"] = options["config_id"]
        else:
            filters["account_alias"] = options["account_alias"]
        matches = PlatformIntegrationConfig.objects.filter(**filters)
        if matches.count() != 1:
            raise CommandError("The exact selector must resolve to one active production Shopee configuration.")
        config = matches.get()
        actor = CustomUser.objects.filter(
            tenant_id=config.tenant_id,
            username=options["actor_username"],
            is_active=True,
        ).first()
        if actor is None:
            raise CommandError("The audit actor must be an active user in the selected tenant.")
        expected_current = options.get("expected_current")
        if expected_current is not None and config.callback_url != expected_current:
            raise CommandError("The current callback changed; refresh the dry-run before applying.")

        self.stdout.write(
            f"config_id={config.id} tenant={config.tenant.code} alias={config.account_alias} "
            f"current={config.callback_url or '<blank>'} proposed={callback_url}"
        )
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("DRY_RUN: no database rows were changed."))
            return

        with transaction.atomic():
            locked = PlatformIntegrationConfig.objects.select_for_update().get(
                pk=config.pk,
                tenant_id=config.tenant_id,
            )
            if expected_current is not None and locked.callback_url != expected_current:
                raise CommandError("The current callback changed while applying; no rows were changed.")
            previous_callback = locked.callback_url
            if previous_callback != callback_url:
                locked.callback_url = callback_url
                locked.config_version += 1
                locked.save(update_fields=["callback_url", "config_version", "updated_at"])
                IntegrationAuditLog.objects.create(
                    tenant=locked.tenant,
                    integration_config=locked,
                    action="repair_shopee_callback",
                    actor=actor,
                    result=IntegrationAuditLog.Result.SUCCESS,
                    masked_detail={
                        "callback_changed": True,
                        "previous_callback_configured": bool(previous_callback),
                        "config_version": locked.config_version,
                        "credentials_changed": False,
                    },
                )
        self.stdout.write(self.style.SUCCESS("APPLIED: callback updated; credentials and authorization rows were untouched."))
