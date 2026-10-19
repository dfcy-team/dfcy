from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import MarketplaceProductAdapter
from apps.integrations.platform_product_ingestion import upsert_platform_product
from apps.integrations.readonly_clients import TikTokReadonlyClient
from apps.integrations.tiktok_product_fields import categories
from apps.listings.models import PlatformProductDetail


CHAIN = [
    {"id": "1", "parent_id": "0", "local_name": "Sports", "is_leaf": False},
    {"id": "2", "parent_id": "1", "local_name": "Fitness", "is_leaf": False},
    {"id": "3", "parent_id": "2", "local_name": "Weights", "is_leaf": True},
]


def test_real_parent_linked_chain_is_not_confused_with_leaf_id_or_array_order():
    assert categories({"category_id": "3", "category_chains": list(reversed(CHAIN))}) == {
        "category_l1": "Sports", "category_l2": "Fitness", "category_l3": "Weights"}


@pytest.mark.parametrize("value", [None, []])
def test_absent_chain_never_promotes_leaf_id_to_level_one(value):
    assert categories({"category_id": "3", "category_chains": value}) == {}


@pytest.mark.parametrize("chain", [{}, [None], CHAIN + [CHAIN[-1]],
    [{**CHAIN[0], "parent_id": "3"}, *CHAIN[1:]], [CHAIN[-1]],
    [{**CHAIN[0], "is_leaf": True}, *CHAIN[1:]],
    [*CHAIN[:-1], {**CHAIN[-1], "is_leaf": False}],
    [*CHAIN[:-1], {**CHAIN[-1], "local_name": "x" * 201}],
    [*CHAIN[:-1], {**CHAIN[-1], "parent_id": "1"}]])
def test_malformed_or_incomplete_chain_is_not_silently_mapped(chain):
    with pytest.raises(ValidationError):
        categories({"category_chains": chain})


def test_verified_shallower_path_can_clear_obsolete_lower_levels():
    assert categories({"category_chains": [{**CHAIN[0], "is_leaf": True}]}) == {
        "category_l1": "Sports", "category_l2": "", "category_l3": ""}


def test_missing_terminal_leaf_proof_cannot_clear_existing_lower_categories():
    chain = deepcopy(CHAIN)
    chain[-1].pop("is_leaf")
    with pytest.raises(ValidationError):
        categories({"category_chains": chain})
    with pytest.raises(ValidationError):
        categories({"category_chains": [{"id": "1", "parent_id": "0", "local_name": "Sports"}]})


def test_client_and_tk_adapter_keep_three_levels_and_missingness():
    config = SimpleNamespace(platform="tiktok", platform_config={})
    auth = SimpleNamespace(shop_cipher="synthetic", store=SimpleNamespace(id=1))
    client = TikTokReadonlyClient(config, auth, custody=object())
    client._runtime_path = lambda _key, fallback: fallback
    product = {"id": "P", "skus": [{"id": "V"}], "category_chains": CHAIN}
    client._request = Mock(side_effect=[{"data": {"products": [{"id": "P"}]}}, {"data": product}])
    row = client.fetch_products("", {"page_size": 100, "time_from": 1, "time_to": 20})["records"][0]
    adapter = MarketplaceProductAdapter(config)
    adapter.authorization = auth
    normalized = adapter.normalize_record(row)
    assert normalized["category_l1"] == "Sports" and normalized["category_l3"] == "Weights"
    for field in ("category_l1", "category_l2", "category_l3"):
        row.pop(field)
    assert not any(field.startswith("category_l") for field in adapter.normalize_record(row))


@pytest.mark.django_db
def test_api_to_database_categories_preserve_unknown_then_refresh_exact_values():
    from tests.test_shopee_tiktok_finance_ingestion import _finance_scope
    tenant, store, config, authorization, job, _ = _finance_scope("tiktok")
    job.resource_type = "platform_product"
    job.save(update_fields=["resource_type"])
    adapter = MarketplaceProductAdapter(config)
    adapter.authorization = authorization
    now = timezone.now()
    source = {"platform_product_id": "P", "platform_variant_id": "V", "title": "Synthetic",
        "platform_updated_at": now, **categories({"category_chains": CHAIN})}
    upsert_platform_product(job, adapter.normalize_record(source))
    row = PlatformProductDetail.objects.get(tenant=tenant, store=store)
    assert (row.category_l1, row.category_l2, row.category_l3) == ("Sports", "Fitness", "Weights")
    row.owner, row.leader, row.shop_abbr, row.sku_prefix = "manual-owner", "manual-leader", "manual-shop", "manual-prefix"
    row.variant = "known-variant"
    row.save(update_fields=["owner", "leader", "shop_abbr", "sku_prefix", "variant"])
    missing = {key: value for key, value in source.items() if not key.startswith("category_l")}
    missing.pop("title")
    missing["platform_updated_at"] = now + timedelta(seconds=1)
    upsert_platform_product(job, adapter.normalize_record(missing))
    row.refresh_from_db()
    assert row.category_l2 == "Fitness" and row.category_l3 == "Weights"
    assert row.title == "Synthetic" and row.variant == "known-variant"
    assert (row.owner, row.leader, row.shop_abbr, row.sku_prefix) == (
        "manual-owner", "manual-leader", "manual-shop", "manual-prefix")
    changed = {**missing, "platform_updated_at": now + timedelta(seconds=2),
        **categories({"category_chains": [{**CHAIN[0], "is_leaf": True}]})}
    upsert_platform_product(job, adapter.normalize_record(changed))
    row.refresh_from_db()
    assert row.category_l1 == "Sports" and row.category_l2 == row.category_l3 == ""
