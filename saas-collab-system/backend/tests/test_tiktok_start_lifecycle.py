"""Start/abandon/failure lifecycle with synthetic providers and no token exchange."""
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core import signing
from rest_framework.exceptions import ValidationError

from apps.integrations import marketplace_oauth_service as service
from apps.integrations.models import IntegrationAuditLog, MarketplaceStoreAuthorization, OAuthStateSession
from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_PROVIDER_UNAVAILABLE
from apps.integrations.tiktok_direct_callback import SALT
from apps.masterdata.models import StoreMaster
from tests.test_lazada_store_authorization import lazada_context

pytestmark = pytest.mark.django_db(transaction=True)
CALLBACK = "https://example.test/integrations/tiktok/shop-callback"
VERIFIER = "synthetic_browser_verifier_0123456789_ABCDEFGHIJKLMN"


@pytest.fixture
def context(lazada_context, monkeypatch, settings):
    _, store, config = lazada_context
    store.platform.platform_type = "tiktok"
    store.platform.save()
    config.platform = "tiktok"
    config.callback_url = CALLBACK
    config.regions = ["MY", "TH"]
    config.save()
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = CALLBACK
    monkeypatch.setattr("apps.integrations.capability.live_network_mode_enabled", lambda: True)
    provider = Mock()
    provider.validate_start_configuration.return_value = None
    provider.build_authorization_url.side_effect = lambda data: {
        "url": "https://services.tiktokshop.com/open/authorize?service_id=SYNTHETIC&state=" + data["state"]}
    provider.exchange_authorization_code.side_effect = AssertionError("No exchange during start")
    monkeypatch.setattr(service, "resolve_oauth_provider", lambda *a: provider)
    return config.created_by, store, config, provider


def start(context, *, store=None, verifier=VERIFIER):
    actor, first, config, _ = context
    selected = store or first
    return service.start_marketplace_oauth(actor=actor, platform="tiktok", integration_config=config,
        store=selected, region=selected.country_code, redirect_uri=CALLBACK, scopes=[],
        tiktok_browser_verifier=verifier)


@pytest.mark.parametrize("failure", ["missing_callback", "wrong_callback", "verifier", "url_build"])
def test_failed_start_does_not_leave_pending_or_partial_context(context, settings, failure):
    if failure == "missing_callback":
        settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = ""
    elif failure == "wrong_callback":
        settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = CALLBACK.replace("example.test", "other.example.test")
    elif failure == "url_build":
        context[3].build_authorization_url.side_effect = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Synthetic refusal")
    with pytest.raises((ValidationError, OAuthFlowError)):
        start(context, verifier="too-short" if failure == "verifier" else VERIFIER)
    assert OAuthStateSession.objects.count() == 0
    assert MarketplaceStoreAuthorization.objects.count() == 0
    context[3].exchange_authorization_code.assert_not_called()
    if failure == "url_build":
        audit = IntegrationAuditLog.objects.get(action="oauth_start")
        assert audit.result == "blocked"
        assert audit.masked_detail["result_code"] == OAUTH_PROVIDER_UNAVAILABLE
        assert "oauth_session_id" not in audit.masked_detail.get("diagnostic", {})
        assert "Synthetic refusal" not in str(audit.masked_detail)


def test_abandoned_first_store_does_not_block_or_rebind_second_store(context):
    actor, first, config, provider = context
    first_result = start(context)
    before = OAuthStateSession.objects.values().get()
    second = StoreMaster.objects.create(tenant=first.tenant, platform=first.platform, code="TK-SECOND",
        name="Synthetic second store", country_code="TH", currency="THB", timezone="Asia/Bangkok")
    second_result = start(context, store=second)
    first_claims = signing.loads(first_result["direct_callback"]["browser_token"], salt=SALT)
    second_claims = signing.loads(second_result["direct_callback"]["browser_token"], salt=SALT)
    assert first_claims["store_id"] == first.pk and second_claims["store_id"] == second.pk
    assert first_claims["session_id"] != second_claims["session_id"]
    assert OAuthStateSession.objects.values().get(pk=before["id"]) == before
    assert OAuthStateSession.objects.filter(status="pending").count() == 2
    assert second_claims["platform_store_id"] == ""
    assert parse_qs(urlsplit(second_result["authorization_url"]).query)["state"] == [second_claims["state"]]
    assert MarketplaceStoreAuthorization.objects.count() == 0
    provider.exchange_authorization_code.assert_not_called()


def test_failed_second_start_preserves_first_pending_session(context):
    start(context)
    before = list(OAuthStateSession.objects.values())
    with pytest.raises(ValidationError):
        start(context, verifier="too-short")
    assert list(OAuthStateSession.objects.values()) == before
    context[3].exchange_authorization_code.assert_not_called()


def test_missing_config_preserves_provider_error_without_fabricating_audit(context, monkeypatch):
    actor, store, _, _ = context
    rejected = Mock(side_effect=OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "Synthetic early refusal"))
    monkeypatch.setattr(service, "resolve_oauth_provider", rejected)
    with pytest.raises(OAuthFlowError) as caught:
        service.start_marketplace_oauth(actor=actor, platform="tiktok", integration_config=None,
            store=store, region=store.country_code, redirect_uri=CALLBACK, scopes=[])
    assert caught.value.controlled_code == OAUTH_PROVIDER_UNAVAILABLE
    assert OAuthStateSession.objects.count() == 0
    assert IntegrationAuditLog.objects.count() == 0
