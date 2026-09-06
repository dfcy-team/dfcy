from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import ShopeeReadonlyClient, TikTokReadonlyClient, default_sync_scope
from apps.integrations.workspace_service import _matches


def _config(platform):
    return SimpleNamespace(platform=platform, platform_config={})


class _FixtureCustody:
    def retrieve_secret(self, _reference):
        return "fixture-secret"

    def retrieve_access_token(self, _reference):
        return "fixture-token"


def test_shopee_product_hydration_batches_all_item_ids_and_does_not_invent_old_sku():
    client = ShopeeReadonlyClient(_config("shopee"), custody=_FixtureCustody())
    item_ids = [str(index) for index in range(60)]
    calls = []

    def request(path, query):
        calls.append((path, query))
        if path == client.PRODUCT_LIST_PATH:
            assert query["item_status"] == ["NORMAL"]
            return {"response": {"item": [{"item_id": item_id} for item_id in item_ids], "has_next_page": False}}
        assert path == client.PRODUCT_BASE_INFO_PATH
        return {
            "response": {
                "item_list": [
                    {
                        "item_id": item_id,
                        "item_name": f"Product {item_id}",
                        "item_sku": f"SELLER-{item_id}",
                        "has_model": False,
                    }
                    for item_id in query["item_id_list"]
                ]
            }
        }

    client._request = request
    page = client.fetch_products("", {"page_size": 100, "time_from": 1, "time_to": 2})

    base_calls = [query for path, query in calls if path == client.PRODUCT_BASE_INFO_PATH]
    assert [len(query["item_id_list"]) for query in base_calls] == [50, 10]
    assert len(page["records"]) == 60
    assert page["records"][0]["platform_sku"] == "SELLER-0"
    assert page["records"][0]["source_old_sku_code"] == ""


def test_shopee_product_status_filter_rejects_unverified_values():
    client = ShopeeReadonlyClient(_config("shopee"), custody=_FixtureCustody())
    client._request = lambda _path, _query: {"response": {"item": []}}
    with pytest.raises(ValidationError, match="not enabled"):
        client.fetch_products(
            "",
            {"page_size": 50, "time_from": 1, "time_to": 2, "statuses": ["DELETED"]},
        )


def test_shopee_product_invalid_identity_fails_before_checkpoint_can_advance():
    client = ShopeeReadonlyClient(_config("shopee"), custody=_FixtureCustody())
    client._request = lambda _path, _query: {"response": {"item": [{"item_id": "ok"}, {}]}}
    with pytest.raises(ValidationError, match="invalid item identity"):
        client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})


def test_tiktok_product_search_hydrates_detail_and_keeps_seller_sku_out_of_old_sku():
    client = TikTokReadonlyClient(
        _config("tiktok"),
        authorization=SimpleNamespace(shop_cipher="fixture-shop"),
        custody=_FixtureCustody(),
    )
    calls = []

    def request(path, *, query=None, body=None, method="GET"):
        calls.append((path, query, body, method))
        if path == client.PRODUCT_SEARCH_PATH:
            assert method == "POST"
            assert body == {"status": "ALL"}
            return {"code": 0, "data": {"products": [{"id": "p-1"}], "next_page_token": "next"}}
        assert path == "/product/202309/products/p-1"
        return {
            "code": 0,
            "data": {
                "product_id": "p-1",
                "title": "A product",
                "skus": [{"id": "v-1", "seller_sku": "SELLER-1", "sales_attributes": []}],
            },
        }

    client._request = request
    page = client.fetch_products("", {"page_size": 100, "time_from": 1, "time_to": 2})
    assert page["next_cursor"] == "next"
    assert page["records"] == [
        {
            "platform_product_id": "p-1",
            "platform_variant_id": "v-1",
            "platform_sku": "SELLER-1",
            "source_old_sku_code": "",
            "title": "A product",
            "variant": "",
            "sales_status": "",
            "platform_created_at": None,
            "platform_updated_at": None,
            "category_l1": "",
        }
    ]


def test_tiktok_incremental_product_window_and_status_are_sent_in_search_body():
    client = TikTokReadonlyClient(
        _config("tiktok"),
        authorization=SimpleNamespace(shop_cipher="fixture-shop"),
        custody=_FixtureCustody(),
    )
    calls = []

    def request(path, *, query=None, body=None, method="GET"):
        calls.append((path, query, body, method))
        if path == client.PRODUCT_SEARCH_PATH:
            assert body == {
                "status": "ACTIVATE",
                "update_time_ge": 100,
                "update_time_le": 200,
            }
            return {"code": 0, "data": {"products": [], "next_page_token": ""}}
        raise AssertionError("incremental product search must not hydrate an empty page")

    client._request = request
    page = client.fetch_products(
        "",
        {
            "page_size": 50,
            "time_from": 100,
            "time_to": 200,
            "product_full_sync": False,
            "statuses": ["ACTIVATE"],
        },
    )
    assert page["records"] == []
    assert calls == [(client.PRODUCT_SEARCH_PATH, {"shop_cipher": "fixture-shop", "page_size": 50}, {"status": "ACTIVATE", "update_time_ge": 100, "update_time_le": 200}, "POST")]


def test_tiktok_product_detail_is_required_instead_of_list_summary_fallback():
    client = TikTokReadonlyClient(
        _config("tiktok"),
        authorization=SimpleNamespace(shop_cipher="fixture-shop"),
        custody=_FixtureCustody(),
    )

    def request(path, *, query=None, body=None, method="GET"):
        if path == client.PRODUCT_SEARCH_PATH:
            return {"code": 0, "data": {"products": [{"id": "p-1"}]}}
        return {"code": 0, "data": {"product_id": "p-1"}}

    client._request = request
    with pytest.raises(ValidationError, match="incomplete"):
        client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})


def test_tiktok_freeze_or_deleted_product_emits_status_only_and_advances_cursor():
    client = TikTokReadonlyClient(
        _config("tiktok"),
        authorization=SimpleNamespace(shop_cipher="fixture-shop"),
        custody=_FixtureCustody(),
    )
    calls = []

    def request(path, *, query=None, body=None, method="GET"):
        calls.append(path)
        assert path == client.PRODUCT_SEARCH_PATH
        return {
            "code": 0,
            "data": {
                "products": [
                    {
                        "id": "p-deleted",
                        "status": "DELETED",
                        "update_time": 1700000000,
                        "skus": [{"id": "v-deleted", "seller_sku": "SELLER-DELETED"}],
                    }
                ],
                "next_page_token": "next",
            },
        }

    client._request = request
    page = client.fetch_products("cursor-before", {"page_size": 50, "time_from": 1, "time_to": 2})
    assert calls == [client.PRODUCT_SEARCH_PATH]
    assert page["next_cursor"] == "next"
    assert page["records"] == [
        {
            "platform_product_id": "p-deleted",
            "platform_variant_id": "v-deleted",
            "platform_sku": "SELLER-DELETED",
            "source_old_sku_code": "",
            "title": "",
            "variant": "",
            "sales_status": "DELETED",
            "platform_created_at": None,
            "platform_updated_at": 1700000000,
            "category_l1": "",
            "status_only": True,
            "partial_snapshot": True,
            "snapshot_kind": "status_only",
        }
    ]


def test_tiktok_status_only_product_without_skus_is_not_fabricated():
    client = TikTokReadonlyClient(
        _config("tiktok"),
        authorization=SimpleNamespace(shop_cipher="fixture-shop"),
        custody=_FixtureCustody(),
    )
    client._request = lambda path, **kwargs: {
        "code": 0,
        "data": {
            "products": [{"id": "p-freeze", "status": "FREEZE", "update_time": 1700000001}],
            "next_page_token": "",
        },
    }
    page = client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})
    assert page["records"][0]["platform_variant_id"] == ""
    assert page["records"][0]["platform_sku"] == ""
    assert page["records"][0]["status_only"] is True


def test_default_sync_scope_preserves_job_status_filter_for_provider_mapping():
    config = SimpleNamespace(platform_config={"sync_scope": {}})
    scope = default_sync_scope(config, {"query": {"statuses": ["ACTIVATE"]}})
    assert scope["statuses"] == ["ACTIVATE"]


def test_product_preflight_requires_independent_runtime_contract_gate(monkeypatch):
    config = SimpleNamespace(
        platform="shopee",
        environment="production",
        status="active",
        network_enabled=True,
        sync_read_enabled=True,
        sync_write_enabled=False,
        platform_config={"contract_approved": True},
    )
    client = ShopeeReadonlyClient(config, custody=_FixtureCustody())
    client.resource_type = "platform_product"
    monkeypatch.setattr("apps.integrations.readonly_clients.is_module_enabled", lambda _name: True)
    monkeypatch.setattr("apps.integrations.readonly_clients.require_live_mode", lambda _name: None)
    monkeypatch.setattr(
        "apps.integrations.readonly_clients.get_runtime_setting",
        lambda *path, default=None: True if path == ("network", "readonly_sync_enabled") else default,
    )
    monkeypatch.setattr(
        "apps.integrations.readonly_clients.get_runtime_platform_config",
        lambda _platform: {"contract_approved": True, "product_contract_approved": False},
    )
    with pytest.raises(ValidationError, match="product readonly contract"):
        client.preflight()


def test_workspace_store_filter_is_exact_not_subject_substring():
    row = {"store_id": 12, "subject_code": "store-12", "subject_name": "Main shop"}
    assert _matches(row, {"store_id": "12"}, "sync-jobs") is True
    assert _matches(row, {"store_id": "1"}, "sync-jobs") is False
