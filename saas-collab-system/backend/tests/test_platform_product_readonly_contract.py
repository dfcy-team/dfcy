from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import MarketplaceProductAdapter
from apps.integrations.readonly_clients import (
    ShopeeReadonlyClient,
    TikTokReadonlyClient,
    _first_http_image_url,
    default_sync_scope,
)
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
                        "image": {"image_url_list": [f"https://img.example.com/{item_id}.jpg"]},
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
    assert page["records"][0]["image_url"] == "https://img.example.com/0.jpg"


def test_shopee_model_image_takes_precedence_over_item_image():
    client = ShopeeReadonlyClient(_config("shopee"), custody=_FixtureCustody())

    def request(path, query):
        if path == client.PRODUCT_LIST_PATH:
            return {"response": {"item": [{"item_id": 7}], "has_next_page": False}}
        if path == client.PRODUCT_BASE_INFO_PATH:
            return {"response": {"item_list": [{"item_id": 7, "item_name": "Product",
                "has_model": True, "image_info": {"image_url_list": ["https://img.example.com/product.jpg"]}}]}}
        assert path == client.PRODUCT_MODEL_LIST_PATH
        return {"response": {"model": [{"model_id": 71, "model_sku": "SELLER-71",
            "image_info": {"image_url": "https://img.example.com/variant.jpg"}}]}}

    client._request = request
    page = client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})
    assert page["records"][0]["image_url"] == "https://img.example.com/variant.jpg"


def test_shopee_malformed_image_url_is_omitted_without_failing_product_sync():
    client = ShopeeReadonlyClient(_config("shopee"), custody=_FixtureCustody())

    def request(path, query):
        if path == client.PRODUCT_LIST_PATH:
            return {"response": {"item": [{"item_id": 8}], "has_next_page": False}}
        return {"response": {"item_list": [{"item_id": 8, "item_name": "Product",
            "has_model": False, "image": {"image_url_list": ["http://[bad"]}}]}}

    client._request = request
    page = client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})
    assert "image_url" not in page["records"][0]


def test_readonly_image_url_skips_invalid_candidates_and_rejects_unsafe_urls():
    invalid = (
        "http://user:secret@example.test/image.jpg",
        "http:///image.jpg",
        "http://example.test:bad/image.jpg",
        "http://example.test/image\n.jpg",
        "http://example.test/image\u0085.jpg",
        "http://example.test\\image.jpg",
    )
    for value in invalid:
        assert _first_http_image_url([value]) == ""
    assert _first_http_image_url([invalid[2], "https://cdn.example.test/good.jpg"]) == (
        "https://cdn.example.test/good.jpg"
    )
    assert _first_http_image_url("http://localhost:8000/image.jpg") == (
        "http://localhost:8000/image.jpg"
    )


def test_shopee_explicit_empty_image_list_emits_empty_url():
    client = ShopeeReadonlyClient(_config("shopee"), custody=_FixtureCustody())

    def request(path, query):
        if path == client.PRODUCT_LIST_PATH:
            return {"response": {"item": [{"item_id": 9}], "has_next_page": False}}
        return {"response": {"item_list": [{"item_id": 9, "item_name": "Product",
            "has_model": False, "image": {"image_url_list": []}}]}}

    client._request = request
    page = client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})
    assert page["records"][0]["image_url"] == ""


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
                "main_images": [{"urls": ["https://img.example.com/product.jpg"]}],
                "skus": [{"id": "v-1", "seller_sku": "SELLER-1", "sales_attributes": [
                    {"name": "Color", "sku_img": {"urls": ["https://img.example.com/variant.jpg"]}},
                ]}],
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
            "image_url": "https://img.example.com/variant.jpg",
        }
    ]


def test_tiktok_product_image_falls_back_to_main_image_and_rejects_uri_only_images():
    client = TikTokReadonlyClient(
        _config("tiktok"),
        authorization=SimpleNamespace(shop_cipher="fixture-shop"),
        custody=_FixtureCustody(),
    )
    client._request = lambda path, **kwargs: (
        {"code": 0, "data": {"products": [{"id": "p-2"}]}}
        if path == client.PRODUCT_SEARCH_PATH
        else {"code": 0, "data": {"product_id": "p-2", "main_images": [
            {"uri": "tos-image-uri", "urls": ["https://img.example.com/main.jpg"]}],
            "skus": [{"id": "v-2", "sales_attributes": [{"sku_img": {"uri": "variant-uri"}}]}]}}
    )
    page = client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})
    assert page["records"][0]["image_url"] == "https://img.example.com/main.jpg"


def test_tiktok_explicit_empty_main_images_emits_empty_url():
    client = TikTokReadonlyClient(
        _config("tiktok"),
        authorization=SimpleNamespace(shop_cipher="fixture-shop"),
        custody=_FixtureCustody(),
    )
    client._request = lambda path, **kwargs: (
        {"code": 0, "data": {"products": [{"id": "p-3"}]}}
        if path == client.PRODUCT_SEARCH_PATH
        else {"code": 0, "data": {"product_id": "p-3", "main_images": [],
            "skus": [{"id": "v-3", "sales_attributes": []}]}}
    )
    page = client.fetch_products("", {"page_size": 50, "time_from": 1, "time_to": 2})
    assert page["records"][0]["image_url"] == ""


def test_product_adapter_preserves_explicit_empty_and_omits_missing_or_invalid_image():
    adapter = object.__new__(MarketplaceProductAdapter)
    adapter.config = _config("shopee")
    adapter.authorization = SimpleNamespace(store=SimpleNamespace(id=42))
    adapter.resource_type = "platform_product"
    base = {"platform_product_id": "p", "platform_variant_id": "v"}

    assert "image_url" not in adapter.normalize_record(base)
    assert adapter.normalize_record({**base, "image_url": ""})["image_url"] == ""
    assert adapter.normalize_record({**base, "image_url": "https://img.example.com/p.jpg"})[
        "image_url"
    ] == "https://img.example.com/p.jpg"
    for value in (
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://[bad",
        "https://" + "a" * 2048,
        "http://user:secret@example.test/image.jpg",
        "http:///image.jpg",
        "http://example.test:bad/image.jpg",
        "http://example.test/image\n.jpg",
        "http://example.test/image\u0085.jpg",
        "http://example.test\\image.jpg",
    ):
        assert "image_url" not in adapter.normalize_record({**base, "image_url": value})


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
