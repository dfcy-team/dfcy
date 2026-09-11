import json

import pytest
from django.test import override_settings

from apps.integrations.custody import get_custody_backend, reset_custody_backend_cache
from apps.integrations.models import PlatformIntegrationConfig
from apps.integrations.workspace_service import _config_rows
from apps.tenants.models import Tenant
from tests.test_integration_credential_maintenance import _client_with_permissions


CALLBACK = "https://app.example.test/callback/tiktok/"


@pytest.fixture
def callback_config(tmp_path):
    tenant = Tenant.objects.create(name="Callback test", code="tiktok-callback-test")
    user, client = _client_with_permissions(tenant)
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="tiktok", account_alias="Synthetic TikTok Shop",
        environment="production", created_by=user, network_enabled=False,
        platform_config={"api_type": "marketplace", "app_key": "fake-app", "service_id": "fake-service"},
    )
    with override_settings(
        DEBUG=True, LIVE_CUSTODY_BACKEND="file",
        CREDENTIAL_CUSTODY_PATH=str(tmp_path / "custody"),
        LIVE_TIKTOK_REDIRECT_URI=CALLBACK, LIVE_OAUTH_REDIRECT_ALLOWLIST=[CALLBACK],
    ):
        reset_custody_backend_cache()
        try:
            yield config, client
        finally:
            reset_custody_backend_cache()


def rotate(config, client, credentials, key):
    return client.post(
        f"/api/internal/integrations/configs/{config.id}/credentials/rotate/",
        {"version": config.config_version, "reason": "Synthetic callback test", "credentials": credentials},
        format="json", HTTP_IDEMPOTENCY_KEY=f"tiktok-callback-{key}",
    )


@pytest.mark.django_db
def test_tiktok_callback_is_saved_and_returned_without_secrets(callback_config):
    config, client = callback_config
    response = rotate(config, client, {"app_secret": "fake-test-secret", "redirect_uri": CALLBACK}, "initial")
    assert response.status_code == 200, response.json()
    assert "fake-test-secret" not in json.dumps(response.json())
    config.refresh_from_db()
    assert config.callback_url == CALLBACK
    config.reference_count = 0
    assert _config_rows([config], {})[0]["callback_url"] == CALLBACK
    assert config.network_enabled is False
    assert config.sync_write_enabled is False

    # A callback-only edit retains the previously stored secret.
    response = rotate(config, client, {"redirect_uri": CALLBACK}, "callback-only")
    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert get_custody_backend().retrieve_secret(config.credential_id) == "fake-test-secret"

    # The form omits blank fields; omission must not clear the saved address.
    response = rotate(config, client, {"app_secret": "fake-replacement-secret"}, "blank")
    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.callback_url == CALLBACK


@pytest.mark.django_db
@pytest.mark.parametrize("callback", [
    "http://app.example.test/callback/tiktok/",
    "https://unregistered.example.test/callback/",
    CALLBACK + "?code=fake-code&state=fake-state",
])
def test_tiktok_rejects_invalid_callback_without_saving(callback_config, callback):
    config, client = callback_config
    response = rotate(config, client, {"app_secret": "fake-test-secret", "redirect_uri": callback}, "invalid")
    assert response.status_code == 400
    config.refresh_from_db()
    assert config.callback_url == ""
    assert config.credential_id == ""


@pytest.mark.django_db
def test_tiktok_callback_requires_live_allowlist(callback_config):
    config, client = callback_config
    with override_settings(LIVE_OAUTH_REDIRECT_ALLOWLIST=[]):
        response = rotate(config, client, {"app_secret": "fake-test-secret", "redirect_uri": CALLBACK}, "no-approval")
    assert response.status_code == 400
    config.refresh_from_db()
    assert config.credential_id == ""


@pytest.mark.django_db
def test_legacy_tiktok_secret_maintenance_does_not_require_new_callback(callback_config):
    config, client = callback_config
    response = rotate(config, client, {"app_secret": "fake-test-secret"}, "legacy")
    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.callback_url == ""
