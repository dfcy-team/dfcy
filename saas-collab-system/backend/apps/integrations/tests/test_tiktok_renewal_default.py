"""Default Shop token renewal requires durable exact OAuth binding evidence."""
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from apps.integrations import ads_binding_compat, automatic_refresh, tiktok_shop_binding
from apps.integrations.models import IntegrationAuditLog, MarketplaceStoreAuthorization, TikTokShopBindingSession
from apps.integrations.production_settings import SAFE_DEFAULTS, validate_runtime_config
from apps.integrations.tiktok_renewal_policy import has_verified_oauth_binding
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import MANUAL, marketplace_callback
from tests.test_tiktok_manual_callback_recovery import recovery

pytestmark = [pytest.mark.django_db(transaction=True),
              pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)]


@pytest.fixture
def oauth_bound_shop(recovery, monkeypatch):
    client, store, config, payload, _, _, _, provider = recovery
    store.external_store_id = ""
    store.save(update_fields=["external_store_id"])
    actor = client.handler._force_user
    params = dict(parse_qsl(urlsplit(payload["callback_url"]).query))
    params["state"] = payload["tiktok_pending_token"]
    provider.custody.revoke.return_value = {"status": "revoked"}
    provider.custody.lookup_reference_by_operation.return_value = {"found": False}
    monkeypatch.setattr(tiktok_shop_binding, "get_custody_backend", lambda: provider.custody)
    pending = tiktok_shop_binding.start_shop_binding(
        actor=actor, query_params=params, callback_state_verified=True,
    )
    record_id = tiktok_shop_binding.confirm_shop_binding(
        actor, pending["binding_id"], pending["candidates"][0]["platform_store_id"],
    )["authorization"]["id"]
    return MarketplaceStoreAuthorization.objects.get(pk=record_id)


def _identity(record):
    return {"tenant_id": record.tenant_id, "store_code": record.store.code,
            "region": record.region, "platform_store_id": record.platform_store_id}


def test_default_refresh_uses_exact_durable_oauth_binding_and_global_gate(oauth_bound_shop):
    record = oauth_bound_shop
    assert has_verified_oauth_binding(record)
    with patch.object(automatic_refresh, "get_runtime_platform_config", return_value={
        "auto_refresh_enabled": True, "auto_refresh_bindings": [], "auto_refresh_exclusions": [],
    }):
        assert automatic_refresh._refresh_enabled_for_record(record)
        assert automatic_refresh.credential_refresh_state(record)["enabled"]
    with patch.object(automatic_refresh, "get_runtime_platform_config", return_value={
        "auto_refresh_enabled": False, "auto_refresh_bindings": [], "auto_refresh_exclusions": [],
    }):
        assert not automatic_refresh._refresh_enabled_for_record(record)


def test_manual_import_audit_blocks_oauth_default(oauth_bound_shop):
    record = oauth_bound_shop
    binding = TikTokShopBindingSession.objects.get(authorization=record)
    IntegrationAuditLog.objects.create(
        tenant_id=record.tenant_id, integration_config_id=record.integration_config_id,
        store_authorization=None, actor_id=binding.initiated_by_id, action="oauth_callback",
        result=IntegrationAuditLog.Result.SUCCESS,
        masked_detail={"result_code": "MANUAL_IMPORT_REQUESTED", "store_id": str(record.store_id)},
    )
    assert not has_verified_oauth_binding(record)
    with patch.object(automatic_refresh, "get_runtime_platform_config", return_value={
        "auto_refresh_enabled": True, "auto_refresh_bindings": [], "auto_refresh_exclusions": [],
    }):
        assert not automatic_refresh._refresh_enabled_for_record(record)
        assert not automatic_refresh.credential_refresh_state(record)["enabled"]


def test_unverified_or_unbound_credentials_need_exact_allow_binding_and_respect_opt_out(recovery):
    client, store, _, payload, _, _, _, _ = recovery
    response = client.post(MANUAL, payload, format="json")
    assert response.status_code == 200, response.data
    record = MarketplaceStoreAuthorization.objects.get(store=store)
    assert not has_verified_oauth_binding(record)
    identity = _identity(record)
    with patch.object(automatic_refresh, "get_runtime_platform_config", return_value={
        "auto_refresh_enabled": True, "auto_refresh_bindings": [], "auto_refresh_exclusions": [],
    }):
        assert not automatic_refresh._refresh_enabled_for_record(record)
    with patch.object(automatic_refresh, "get_runtime_platform_config", return_value={
        "auto_refresh_enabled": False, "auto_refresh_bindings": [identity], "auto_refresh_exclusions": [],
    }):
        assert not automatic_refresh._refresh_enabled_for_record(record)
    with patch.object(automatic_refresh, "get_runtime_platform_config", return_value={
        "auto_refresh_enabled": True, "auto_refresh_bindings": [identity], "auto_refresh_exclusions": [],
    }):
        assert automatic_refresh._refresh_enabled_for_record(record)
    with patch.object(automatic_refresh, "get_runtime_platform_config", return_value={
        "auto_refresh_enabled": True, "auto_refresh_bindings": [identity], "auto_refresh_exclusions": [identity],
    }):
        assert not automatic_refresh._refresh_enabled_for_record(record)


def test_exact_exclusion_schema_and_ads_historical_digest_shape(monkeypatch, marketplace_callback):
    exclusion = {"tenant_id": 7, "store_code": "TIKTOK-7", "region": "ph",
                 "platform_store_id": "shop_7", "integration_config_id": 12}
    validated = validate_runtime_config({"platforms": {"tiktok": {"auto_refresh_exclusions": [exclusion]}}})
    assert validated["platforms"]["tiktok"]["auto_refresh_exclusions"][0]["region"] == "PH"
    with pytest.raises(ValidationError):
        validate_runtime_config({"platforms": {"tiktok": {"auto_refresh_exclusions": [{"store_code": "TIKTOK-7"}]}}})

    old = deepcopy(SAFE_DEFAULTS)
    old["platforms"]["tiktok"].pop("auto_refresh_exclusions")
    monkeypatch.setattr(ads_binding_compat, "_environment_config", lambda: deepcopy(SAFE_DEFAULTS))
    variants = ads_binding_compat._historical_platform(SimpleNamespace(value=old))
    assert any("auto_refresh_exclusions" not in item for item in variants)
    assert "auto_refresh_exclusions" in ads_binding_compat.UNRELATED_PLATFORM_FIELDS
