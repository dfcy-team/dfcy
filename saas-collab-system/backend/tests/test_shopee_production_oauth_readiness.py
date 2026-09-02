from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings

from apps.integrations.live_providers import build_live_provider, integration_config_oauth_blockers


CALLBACK = "https://xtsy.example.test/api/internal/integrations/store-authorizations/oauth/callback/shopee/"


def _config(**overrides):
    values = {
        "platform": "shopee",
        "environment": "production",
        "network_enabled": True,
        "sync_read_enabled": True,
        "sync_write_enabled": False,
        "status": "verified",
        "credential_status": "configured",
        "credential_id": "cred_reference_only",
        "contract_version": "v2",
        "callback_url": CALLBACK,
        "platform_config": {"partner_id": "2038415"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_CUSTODY_BACKEND="http",
    LIVE_CUSTODY_SERVICE_URL="https://custody.example.test",
    LIVE_CUSTODY_SERVICE_HOST="custody.example.test",
    LIVE_CUSTODY_SERVICE_TOKEN="placeholder-service-token",
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI=CALLBACK,
    LIVE_OAUTH_REDIRECT_ALLOWLIST=[CALLBACK],
)
def test_production_shopee_oauth_is_ready_with_read_sync_enabled():
    assert integration_config_oauth_blockers("shopee", _config()) == []


@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["partner.shopeemobile.com"],
    LIVE_CUSTODY_BACKEND="http",
    LIVE_CUSTODY_SERVICE_URL="https://custody.example.test",
    LIVE_CUSTODY_SERVICE_HOST="custody.example.test",
    LIVE_CUSTODY_SERVICE_TOKEN="placeholder-service-token",
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI=CALLBACK,
    LIVE_OAUTH_REDIRECT_ALLOWLIST=[CALLBACK],
    LIVE_SHOPEE_AUTH_URL="https://partner.shopeemobile.com/api/v2/shop/auth_partner",
)
def test_production_shopee_oauth_can_build_signed_authorization_url_without_external_request():
    with patch("apps.integrations.live_providers.get_custody_backend", return_value=SimpleNamespace()):
        provider = build_live_provider(
            "shopee",
            integration_config=_config(),
            secret_resolver=lambda _platform: {"app_secret": "placeholder-partner-key"},
        )

    payload = provider.build_authorization_url({"state": "opaque-state", "redirect_uri": CALLBACK})

    assert payload["url"].startswith("https://partner.shopeemobile.com/api/v2/shop/auth_partner?")
    assert "partner_id=2038415" in payload["url"]
    assert "opaque-state" in payload["url"]


@override_settings(
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_SHOPEE_CONTRACT_APPROVED=True,
    LIVE_SHOPEE_REDIRECT_URI=CALLBACK,
    LIVE_OAUTH_REDIRECT_ALLOWLIST=[CALLBACK],
)
def test_production_shopee_oauth_remains_fail_closed_for_each_security_gate():
    cases = [
        ({"status": "pending_review"}, "config_not_approved"),
        ({"credential_status": "unconfigured"}, "credential_not_configured"),
        ({"credential_id": ""}, "credential_reference_missing"),
        ({"callback_url": ""}, "callback_missing"),
        ({"callback_url": "https://other.example.test/callback"}, "callback_mismatch"),
        ({"sync_write_enabled": True}, "write_sync_enabled"),
        ({"network_enabled": False}, "network_not_approved"),
        ({"contract_version": "v1"}, "contract_not_approved"),
        ({"platform_config": {}}, "public_app_id_missing"),
    ]
    for overrides, expected in cases:
        assert expected in integration_config_oauth_blockers("shopee", _config(**overrides))
