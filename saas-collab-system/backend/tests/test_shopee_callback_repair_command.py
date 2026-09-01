from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.models import CustomUser
from apps.integrations.models import IntegrationAuditLog, PlatformIntegrationConfig
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db
CALLBACK = "https://xtsy.example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"


@override_settings(LIVE_SHOPEE_REDIRECT_URI=CALLBACK, LIVE_OAUTH_REDIRECT_ALLOWLIST=[CALLBACK])
def test_repair_shopee_callback_is_dry_run_by_default_and_exact_on_apply():
    tenant = Tenant.objects.create(name="Tenant", code="repair-shopee")
    actor = CustomUser.objects.create_user(username="architect", tenant=tenant, user_type="internal")
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="Shopee production",
        environment="production",
        status="verified",
        regions=["PH"],
        contract_version="v2",
        platform_config={"partner_id": "2038415"},
        created_by=actor,
    )
    output = StringIO()
    arguments = [
        "--tenant-code", tenant.code,
        "--config-id", str(config.id),
        "--actor-username", actor.username,
        "--callback-url", CALLBACK,
        "--expected-current", "",
    ]

    call_command("repair_shopee_callback", *arguments, stdout=output)
    config.refresh_from_db()
    assert config.callback_url == ""
    assert "DRY_RUN" in output.getvalue()

    call_command("repair_shopee_callback", *arguments, "--apply", stdout=output)
    config.refresh_from_db()
    assert config.callback_url == CALLBACK
    assert config.config_version == 2
    audit = IntegrationAuditLog.objects.get(action="repair_shopee_callback")
    assert audit.masked_detail["credentials_changed"] is False
    assert "credential" not in output.getvalue().lower() or "credentials and authorization rows were untouched" in output.getvalue()


@override_settings(LIVE_SHOPEE_REDIRECT_URI=CALLBACK, LIVE_OAUTH_REDIRECT_ALLOWLIST=[CALLBACK])
def test_repair_shopee_callback_rejects_stale_expected_value():
    tenant = Tenant.objects.create(name="Tenant 2", code="repair-shopee-stale")
    actor = CustomUser.objects.create_user(username="architect", tenant=tenant, user_type="internal")
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="Shopee production",
        environment="production",
        callback_url=CALLBACK,
        created_by=actor,
    )

    with pytest.raises(CommandError, match="current callback changed"):
        call_command(
            "repair_shopee_callback",
            "--tenant-code", tenant.code,
            "--config-id", str(config.id),
            "--actor-username", actor.username,
            "--callback-url", CALLBACK,
            "--expected-current", "",
            "--apply",
        )
