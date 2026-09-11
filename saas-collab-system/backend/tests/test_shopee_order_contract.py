from types import SimpleNamespace

from apps.integrations.adapters import MarketplaceOrderAdapter


def test_order_normalization_preserves_platform_line_identity():
    config = SimpleNamespace(platform="shopee", platform_config={})
    adapter = MarketplaceOrderAdapter(config)
    adapter.authorization = SimpleNamespace(store=SimpleNamespace(id=1, currency="PHP"), region="PH")
    record = adapter.normalize_record({
        "order_sn": "SYNTHETIC-ORDER", "order_status": "COMPLETED",
        "create_time": 1788170400, "update_time": 1788174000, "total_amount": 20,
        "item_list": [{"item_id": 123, "model_id": 456, "model_sku": "SYNTHETIC-SKU",
            "model_quantity_purchased": 2, "model_discounted_price": 10}],
    })
    assert record["lines"][0]["platform_product_id"] == "123"
    assert record["lines"][0]["platform_variant_id"] == "456"
    assert record["lines"][0]["raw_line_status"] == "COMPLETED"
