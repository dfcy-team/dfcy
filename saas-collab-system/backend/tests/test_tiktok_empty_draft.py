"""No-SKU draft observations are audited, not canonical product snapshots."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations.adapters import MarketplaceProductAdapter
from apps.integrations.readonly_clients import TikTokReadonlyClient


def fetch(status="DRAFT", *, updated=100, detail_id="123"):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="SYNTHETIC")
    client._runtime_path = lambda name, default: default
    client._request = lambda path, **kw: ({"data": {"products": [{"id": "123", "status": "DRAFT"}], "next_page_token": ""}}
        if path.endswith("search") else {"data": {"id": detail_id, "status": status, "skus": [], "update_time": updated}})
    return client.fetch_products(None, {"page_size": 100, "product_full_sync": True})


def adapter():
    value = object.__new__(MarketplaceProductAdapter)
    value.resource_type = "platform_product"
    value.config = SimpleNamespace(platform="tiktok")
    value.authorization = SimpleNamespace(store=SimpleNamespace(id=23))
    value.source_run = SimpleNamespace(id=77)
    return value


def test_draft_has_explicit_observation_without_fabricated_sku():
    page = fetch()
    assert len(page["records"]) == 1 and len(page["raw_responses"]) == 2
    record = adapter().normalize_record(page["records"][0])
    assert record["draft_without_skus"] is True and not record["status_only"]
    assert record["platform_variant_id"] == "" and adapter().validate_record(record)


@pytest.mark.parametrize("status", ["ACTIVATE", "PENDING", "FAILED", "UNKNOWN"])
def test_non_draft_empty_detail_remains_blocked(status):
    with pytest.raises(ValidationError, match="no SKU list"):
        fetch(status)


def test_missing_timestamp_and_wrong_identity_remain_blocked():
    with pytest.raises(ValidationError, match="missing update_time"):
        fetch(updated=None)
    with pytest.raises(ValidationError, match="incomplete"):
        fetch(detail_id="999")


@pytest.mark.parametrize("invalid", ["not-a-time", False, True, 1.5, "1.5", -1, 0, 253402300800])
def test_invalid_draft_time_blocks_page_and_direct_normalization(invalid):
    with pytest.raises(ValidationError, match="invalid update_time"):
        fetch(updated=invalid)
    with pytest.raises(ValidationError, match="invalid update_time"):
        adapter().normalize_record({"draft_without_skus": True, "platform_updated_at": invalid})


@pytest.mark.parametrize("invalid", ["not-a-time", False, True, 1.5, "2026-10-08T01:00:00"])
def test_invalid_normalized_time_cannot_be_audited_or_skipped(invalid):
    value = adapter()
    record = value.normalize_record(fetch()["records"][0])
    record["platform_updated_at"] = invalid
    assert value.validate_record(record) is False
    with pytest.raises(ValidationError, match="Invalid no-SKU draft"):
        value.persist_record(SimpleNamespace(pk=2), record)


def test_observation_writes_audit_only_not_known_product_variants(monkeypatch):
    value = adapter()
    record = value.normalize_record(fetch()["records"][0])
    create = Mock()
    monkeypatch.setattr("apps.integrations.models.IntegrationAuditLog.objects.create", create)
    monkeypatch.setattr("apps.integrations.platform_product_ingestion.upsert_platform_product", Mock(side_effect=AssertionError("canonical mutation forbidden")))
    job = SimpleNamespace(pk=2, tenant_id=1, integration_config_id=7, store_authorization_id=1,
        integration_config=SimpleNamespace(created_by=SimpleNamespace(pk=9, tenant_id=1)))
    result = value.persist_record(job, record)
    assert result["action"] == "skipped" and result["result_code"] == "DRAFT_WITHOUT_SKUS"
    assert create.call_args.kwargs["masked_detail"]["canonical_variants_changed"] == 0
    assert create.call_args.kwargs["actor_id"] == 9 and create.call_args.kwargs["result"] == "success"


def test_invalid_observation_cannot_enter_audit_skip():
    value = adapter()
    record = value.normalize_record(fetch()["records"][0])
    record["sales_status"] = "ACTIVATE"
    with pytest.raises(ValidationError, match="Invalid no-SKU draft"):
        value.persist_record(SimpleNamespace(pk=2), record)


@pytest.mark.django_db
def test_draft_observation_has_valid_audit_foreign_keys(monkeypatch):
    from django.contrib.auth import get_user_model
    from apps.tenants.models import Tenant
    from apps.integrations.models import IntegrationAuditLog, PlatformIntegrationConfig, authorization_service_write

    tenant = Tenant.objects.create(code="draft-only-synthetic", name="Synthetic")
    actor = get_user_model().objects.create_user(username="draft-synthetic", tenant=tenant)
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, created_by=actor,
            platform="tiktok", account_alias="Synthetic draft", environment="pilot")
    value = adapter()
    record = value.normalize_record(fetch()["records"][0])
    monkeypatch.setattr("apps.integrations.platform_product_ingestion.upsert_platform_product",
        Mock(side_effect=AssertionError("canonical mutation forbidden")))
    job = SimpleNamespace(pk=2, tenant_id=tenant.pk, integration_config_id=config.pk,
        store_authorization_id=None, integration_config=config)
    assert value.persist_record(job, record)["action"] == "skipped"
    audit = IntegrationAuditLog.objects.get(tenant=tenant, integration_config=config)
    assert audit.actor_id == actor.pk and audit.result == "success"
    assert audit.masked_detail["canonical_variants_changed"] == 0
