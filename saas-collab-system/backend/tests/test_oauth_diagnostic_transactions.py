from urllib.parse import urlencode
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations import marketplace_oauth_service as service
from apps.integrations.manual_callback import validate_manual_callback
from apps.integrations.models import IntegrationAuditLog, MarketplaceStoreAuthorization, authorization_service_write
from apps.integrations.oauth_diagnostics import callback_url_key
from apps.integrations.oauth_state_service import create_oauth_state
from tests.test_marketplace_callback_acceptance import marketplace_callback, START, MANUAL
from tests.test_lazada_store_authorization import lazada_context

pytestmark = pytest.mark.django_db


def test_first_callback_persists_exact_provider_expiry(marketplace_callback, monkeypatch):
    from datetime import timedelta
    client, store, config, _, payload = marketplace_callback
    provider = service.resolve_oauth_provider(config.platform, config)
    original = provider.exchange_authorization_code
    expiry = timezone.now() + timedelta(hours=4)

    def exchange(data):
        return {**original(data), "expires_at": expiry}

    monkeypatch.setattr(provider, "exchange_authorization_code", exchange)
    monkeypatch.setattr(service, "resolve_oauth_provider", lambda *args: provider)
    assert client.post(MANUAL, payload, format="json").status_code == 200
    record = MarketplaceStoreAuthorization.objects.get(store=store)
    assert record.status == "active"
    assert record.expires_at == expiry


def new_callback(client, store, config):
    response = client.post(START, {
        "platform": config.platform, "integration_config_id": config.pk,
        "store_id": store.pk, "region": store.country_code, "redirect_uri": config.callback_url, "scopes": [],
    }, format="json")
    assert response.status_code == 201
    params = response.data["data"]["simulation_callback"]
    return {"store_id": store.pk, "integration_config_id": config.pk,
            "callback_url": config.callback_url + "?" + urlencode(params)}


@pytest.mark.parametrize("field", ["config_version", "credential_reference_version"])
def test_changed_versions_block_exchange(marketplace_callback, monkeypatch, field):
    client, store, config, _, payload = marketplace_callback
    setattr(config, field, getattr(config, field) + 1)
    with authorization_service_write():
        config.save()
    resolve = Mock()
    monkeypatch.setattr(service, "resolve_oauth_provider", resolve)
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 409
    assert response.data["data"]["reason_code"] == "OAUTH_CONFIGURATION_CHANGED"
    assert response.data["data"]["diagnostic"]["category"] == "configuration_changed"
    resolve.assert_not_called()
    assert not MarketplaceStoreAuthorization.objects.filter(store=store).exists()


def test_change_during_exchange_cannot_save_authorization(marketplace_callback, monkeypatch):
    client, store, config, _, payload = marketplace_callback
    provider = service.resolve_oauth_provider(config.platform, config)
    original = provider.exchange_authorization_code

    def change_after_exchange(data):
        result = original(data)
        config.config_version += 1
        config.save()
        return result

    monkeypatch.setattr(provider, "exchange_authorization_code", change_after_exchange)
    monkeypatch.setattr(service, "resolve_oauth_provider", lambda *args: provider)
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 409
    assert response.data["data"]["diagnostic"]["stage"] == "save_authorization"
    assert not MarketplaceStoreAuthorization.objects.filter(store=store).exists()


def test_failed_reauthorization_rolls_back_without_revoking_previous(marketplace_callback, monkeypatch, caplog):
    client, store, config, _, payload = marketplace_callback
    assert client.post(MANUAL, payload, format="json").status_code == 200
    existing = MarketplaceStoreAuthorization.objects.get(store=store)
    before = (existing.token_id, existing.credential_id, existing.status, existing.credential_reference_version)
    payload = new_callback(client, store, config)
    previous_revoker, new_revoker = Mock(), Mock()
    provider = Mock()
    provider.validate_callback.return_value = {}
    provider.exchange_authorization_code.return_value = {
        "credential_id": "cred_fake_new_reference", "token_id": "tok_fake_new_reference",
        "reference_kind": "custody", "expires_at": timezone.now(),
        "platform_subject": existing.merchant_subject_id, "authorized_scopes": [],
        "platform_store_records": [{"platform_store_id": existing.platform_store_id}],
        "previous_reference_revoker": previous_revoker, "new_reference_revoker": new_revoker,
    }
    monkeypatch.setattr(service, "resolve_oauth_provider", lambda *args: provider)
    audit = service._callback_audit

    def fail_success_audit(*args, **kwargs):
        if kwargs.get("authorization") is not None:
            raise RuntimeError("FAKE_SECRET_MUST_NOT_LEAK")
        return audit(*args, **kwargs)

    monkeypatch.setattr(service, "_callback_audit", fail_success_audit)
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 503
    existing.refresh_from_db()
    assert (existing.token_id, existing.credential_id, existing.status, existing.credential_reference_version) == before
    previous_revoker.assert_not_called()
    new_revoker.assert_called_once_with("cred_fake_new_reference", "tok_fake_new_reference")
    diagnostic = response.data["data"]["diagnostic"]
    assert diagnostic["stage"] == "save_authorization"
    assert diagnostic["category"] == "database_failure"
    assert IntegrationAuditLog.objects.filter(masked_detail__diagnostic__diagnostic_id=diagnostic["diagnostic_id"]).exists()
    assert "FAKE_SECRET_MUST_NOT_LEAK" not in str(response.data) + caplog.text
    assert client.post(MANUAL, payload, format="json").status_code == 409
    provider.exchange_authorization_code.assert_called_once()


@pytest.mark.parametrize("registered,actual,accepted", [
    ("https://example.test", "https://example.test/", True),
    ("https://example.test/", "https://example.test", True),
    ("https://example.test/callback", "https://example.test/callback/", False),
    ("https://example.test", "https://other.test/", False),
    ("https://example.test?binding=one", "https://example.test/?binding=two", False),
])
def test_only_root_path_equivalence(lazada_context, registered, actual, accepted):
    client, store, config = lazada_context
    actor = config.created_by
    state, session = create_oauth_state(tenant=config.tenant, platform=config.platform, actor=actor,
        integration_config=config, store=store, region=store.country_code, redirect_uri=registered, scopes=[])
    url = actual + ("&" if "?" in actual else "?") + urlencode({"state": state, "code": "FAKE_CODE"})
    if accepted:
        assert validate_manual_callback(actor=actor, callback_url=url, store_id=store.pk, integration_config_id=config.pk)[0] == config.platform
        assert callback_url_key(registered) == callback_url_key(actual)
    else:
        from rest_framework.exceptions import ValidationError
        with pytest.raises(ValidationError):
            validate_manual_callback(actor=actor, callback_url=url, store_id=store.pk, integration_config_id=config.pk)
    session.refresh_from_db()
    assert session.status == "pending"
