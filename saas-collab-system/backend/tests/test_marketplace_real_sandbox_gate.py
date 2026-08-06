"""Real Sandbox preparation gate tests: evidence registry, real adapters, network egress.

Everything here stays fail closed: without registered contract values and the double
network gate, no real adapter path can reach the network. Synthetic fencing/state
semantics are untouched by this work and covered by the existing test suites.
"""

import socket

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.integrations.evidence_registry import (
    current_oauth_evidence,
    evidence_readiness_summary,
    real_sandbox_evidence_ready,
    register_oauth_evidence,
)
from apps.integrations.models import MarketplaceOAuthEvidence, oauth_evidence_write
from apps.integrations.oauth_adapters import (
    OAuthAdapterError,
    RealCustodyGateway,
    ShopeeAdapter,
    TikTokShopAdapter,
    assert_network_egress,
)


REAL_CONTRACT = {
    "shopee": {
        "authorization_entry": "https://auth.console-sandbox.example/oauth/authorize",
        "callback_url": "https://callback.internal.example/api/platform/oauth/shopee/callback/",
        "minimum_read_scopes": ["shop.read"],
        "app_reference": "shp_app_****0000",
    },
    "tiktok": {
        "authorization_entry": "https://auth.console-sandbox.example/oauth/authorize",
        "callback_url": "https://callback.internal.example/api/platform/oauth/tiktok/callback/",
        "minimum_read_scopes": ["shop.read"],
        "app_reference": "tt_app_****0000",
    },
    "custody": {"host": "custody.internal.example"},
}


@pytest.mark.django_db
def test_baseline_evidence_migration_registers_six_items_as_pending():
    # 3 per-platform keys x 2 platforms + 3 shared keys
    assert MarketplaceOAuthEvidence.objects.count() == 9
    assert real_sandbox_evidence_ready() is False
    summary = {(row["evidence_key"], row["platform"]): row for row in evidence_readiness_summary()}
    assert summary[("a2_00_security_confirmation", "shared")]["readiness"] == "ready"
    assert summary[("a2_00_app_identity", "shopee")]["readiness"] == "pending"
    assert summary[("a2_00_endpoint_contract", "tiktok")]["readiness"] == "pending"
    assert summary[("a2_00_network_egress", "shared")]["readiness"] == "pending"


@pytest.mark.django_db
def test_evidence_registration_supersedes_and_never_exposes_credential_keys():
    first = register_oauth_evidence(
        evidence_key=MarketplaceOAuthEvidence.EvidenceKey.CALLBACK_URL,
        platform="shopee",
        readiness=MarketplaceOAuthEvidence.Readiness.READY,
        masked_value={"callback_url": "https://cb.example/oauth/"},
        source="console registration",
        confirmed_by="开发A",
        contract_version="a2-sandbox-v1",
    )
    second = register_oauth_evidence(
        evidence_key=MarketplaceOAuthEvidence.EvidenceKey.CALLBACK_URL,
        platform="shopee",
        readiness=MarketplaceOAuthEvidence.Readiness.READY,
        masked_value={"callback_url": "https://cb2.example/oauth/"},
        source="console registration v2",
        confirmed_by="开发A",
        contract_version="a2-sandbox-v1",
    )
    first.refresh_from_db()
    assert first.is_current is False and first.superseded_at is not None
    current = current_oauth_evidence(MarketplaceOAuthEvidence.EvidenceKey.CALLBACK_URL, "shopee")
    assert current.pk == second.pk

    with pytest.raises(ValidationError):
        register_oauth_evidence(
            evidence_key=MarketplaceOAuthEvidence.EvidenceKey.APP_IDENTITY,
            platform="tiktok",
            readiness=MarketplaceOAuthEvidence.Readiness.READY,
            masked_value={"app": {"partner_key": "must-be-rejected"}},
            source="console",
            confirmed_by="开发A",
            contract_version="a2-sandbox-v1",
        )
    with pytest.raises(ValidationError):
        register_oauth_evidence(
            evidence_key=MarketplaceOAuthEvidence.EvidenceKey.CUSTODY_CONTRACT,
            platform="shopee",  # shared keys require platform="shared"
            readiness=MarketplaceOAuthEvidence.Readiness.READY,
            masked_value={},
            source="console",
            confirmed_by="开发A",
            contract_version="a2-sandbox-v1",
        )


@pytest.mark.django_db
def test_evidence_rows_are_append_only_and_service_gated():
    evidence = current_oauth_evidence(MarketplaceOAuthEvidence.EvidenceKey.NETWORK_EGRESS, "shared")
    with pytest.raises(ValidationError):
        evidence.masked_value = {}
        evidence.save()
    with pytest.raises(ValidationError):
        MarketplaceOAuthEvidence(
            evidence_key=MarketplaceOAuthEvidence.EvidenceKey.APP_IDENTITY,
            platform="shopee",
        ).save()
    with pytest.raises(ValidationError):
        MarketplaceOAuthEvidence.objects.filter(pk=evidence.pk).update(readiness="ready")
    with pytest.raises(ValidationError):
        MarketplaceOAuthEvidence.objects.all().delete()
    with oauth_evidence_write():
        MarketplaceOAuthEvidence.objects.filter(pk=evidence.pk).update(is_current=True)


@pytest.mark.django_db
def test_real_sandbox_ready_requires_all_nine_items():
    keys_platforms = [
        (MarketplaceOAuthEvidence.EvidenceKey.APP_IDENTITY, "shopee"),
        (MarketplaceOAuthEvidence.EvidenceKey.APP_IDENTITY, "tiktok"),
        (MarketplaceOAuthEvidence.EvidenceKey.ENDPOINT_CONTRACT, "shopee"),
        (MarketplaceOAuthEvidence.EvidenceKey.ENDPOINT_CONTRACT, "tiktok"),
        (MarketplaceOAuthEvidence.EvidenceKey.CALLBACK_URL, "shopee"),
        (MarketplaceOAuthEvidence.EvidenceKey.CALLBACK_URL, "tiktok"),
        (MarketplaceOAuthEvidence.EvidenceKey.CUSTODY_CONTRACT, "shared"),
        (MarketplaceOAuthEvidence.EvidenceKey.NETWORK_EGRESS, "shared"),
    ]
    for key, platform in keys_platforms[:-1]:
        register_oauth_evidence(
            evidence_key=key,
            platform=platform,
            readiness=MarketplaceOAuthEvidence.Readiness.READY,
            masked_value={"status": "registered"},
            source="console",
            confirmed_by="开发A",
            contract_version="a2-sandbox-v1",
        )
    assert real_sandbox_evidence_ready() is False
    register_oauth_evidence(
        evidence_key=keys_platforms[-1][0],
        platform=keys_platforms[-1][1],
        readiness=MarketplaceOAuthEvidence.Readiness.READY,
        masked_value={"status": "registered"},
        source="console",
        confirmed_by="开发A",
        contract_version="a2-sandbox-v1",
    )
    assert real_sandbox_evidence_ready() is True


@pytest.mark.parametrize("adapter_class", (ShopeeAdapter, TikTokShopAdapter))
def test_real_adapter_authorization_url_fails_closed_without_contract(adapter_class):
    adapter = adapter_class()
    with pytest.raises(OAuthAdapterError) as exc_info:
        adapter.build_authorization_url(platform=adapter.platform, state="state-1", attempt_id=1)
    assert exc_info.value.error_code == "OAUTH_CONTRACT_PENDING"


@override_settings(MARKETPLACE_OAUTH_REAL_CONTRACT=REAL_CONTRACT)
def test_shopee_adapter_builds_url_from_frozen_contract_only():
    adapter = ShopeeAdapter()
    url = adapter.build_authorization_url(platform="shopee", state="state-xyz", attempt_id=7)
    assert url.startswith("https://auth.console-sandbox.example/oauth/authorize?")
    assert "state=state-xyz" in url
    assert "scope=shop.read" in url
    assert "client_reference=shp_app_%2A%2A%2A%2A0000" in url
    partial = {"shopee": {**REAL_CONTRACT["shopee"], "minimum_read_scopes": []}}
    with override_settings(MARKETPLACE_OAUTH_REAL_CONTRACT=partial):
        with pytest.raises(OAuthAdapterError) as exc_info:
            adapter.build_authorization_url(platform="shopee", state="s", attempt_id=1)
        assert exc_info.value.error_code == "OAUTH_CONTRACT_PENDING"


@override_settings(MARKETPLACE_OAUTH_REAL_CONTRACT=REAL_CONTRACT)
def test_real_callback_validation_is_whitelist_state_and_identity_checked():
    shopee = ShopeeAdapter()
    callback = shopee.validate_callback(
        platform="shopee",
        query={"state": "state-1", "code": "real-code", "shop_id": "shop-123"},
        expected_state="state-1",
    )
    assert callback.code == "real-code"
    assert callback.platform_store_id == "shop-123"
    shopee.verify_exchange_identity(callback_platform_store_id="shop-123", exchange_platform_store_id="shop-123")
    with pytest.raises(OAuthAdapterError) as exc_info:
        shopee.verify_exchange_identity(callback_platform_store_id="shop-123", exchange_platform_store_id="shop-999")
    assert exc_info.value.error_code == "OAUTH_IDENTITY_MISMATCH"
    for bad_query in (
        {"state": "state-1", "code": "c", "signature": "forged"},  # real callbacks carry no signature
        {"state": "other", "code": "c"},
        {"state": "state-1"},
    ):
        with pytest.raises(OAuthAdapterError):
            shopee.validate_callback(platform="shopee", query=bad_query, expected_state="state-1")
    tiktok = TikTokShopAdapter()
    callback = tiktok.validate_callback(
        platform="tiktok", query={"state": "state-1", "code": "real-code"}, expected_state="state-1"
    )
    assert callback.platform_store_id == ""  # identity comes from the custody shops lookup
    with pytest.raises(OAuthAdapterError):
        tiktok.validate_callback(
            platform="tiktok", query={"state": "state-1", "code": "c", "shop_id": "x"}, expected_state="state-1"
        )


def test_network_egress_double_gate_and_dns_guard(monkeypatch):
    with override_settings(MARKETPLACE_OAUTH_NETWORK_ENABLED=False):
        with pytest.raises(OAuthAdapterError) as exc_info:
            assert_network_egress("custody.internal.example")
        assert exc_info.value.error_code == "OAUTH_NETWORK_DISABLED"

    enabled = {"MARKETPLACE_OAUTH_NETWORK_ENABLED": True, "MARKETPLACE_OAUTH_NETWORK_ALLOWLIST": ("allowed.example",)}
    with override_settings(**enabled):
        with pytest.raises(OAuthAdapterError) as exc_info:
            assert_network_egress("blocked.example")
        assert exc_info.value.error_code == "OAUTH_NETWORK_HOST_NOT_ALLOWED"

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port, proto=0: [(2, 1, 6, "", ("127.0.0.1", 443))],
        )
        with pytest.raises(OAuthAdapterError) as exc_info:
            assert_network_egress("allowed.example")
        assert exc_info.value.error_code == "OAUTH_NETWORK_PRIVATE_ADDRESS"

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port, proto=0: [(2, 1, 6, "", ("8.8.4.4", 443))],
        )
        assert_network_egress("allowed.example")  # global address passes the guard


def test_real_custody_gateway_fails_closed_without_contract():
    gateway = RealCustodyGateway()
    calls = (
        lambda: gateway.exchange_and_store(platform="shopee", code="c", operation_id=1, attempt_id=1),
        lambda: gateway.refresh_and_store(authorization=None, operation_id=1),
        lambda: gateway.revoke(authorization=None, operation_id=1),
        lambda: gateway.fetch_shop_info(platform="tiktok", credential_reference="ref-1"),
    )
    for call in calls:
        with pytest.raises(OAuthAdapterError) as exc_info:
            call()
        assert exc_info.value.error_code == "OAUTH_CONTRACT_PENDING"


@override_settings(
    MARKETPLACE_OAUTH_REAL_CONTRACT=REAL_CONTRACT,
    MARKETPLACE_OAUTH_NETWORK_ENABLED=True,
    MARKETPLACE_OAUTH_NETWORK_ALLOWLIST=("custody.internal.example",),
)
def test_real_custody_gateway_transport_stays_pending_after_gate(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, proto=0: [(2, 1, 6, "", ("8.8.4.4", 443))],
    )
    gateway = RealCustodyGateway()
    with pytest.raises(OAuthAdapterError) as exc_info:
        gateway.exchange_and_store(platform="shopee", code="c", operation_id=1, attempt_id=1)
    assert exc_info.value.error_code == "OAUTH_NETWORK_CLIENT_PENDING"
