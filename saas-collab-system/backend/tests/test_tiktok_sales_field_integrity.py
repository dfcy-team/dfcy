from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrder
from apps.integrations.adapters import MarketplaceOrderAdapter, MarketplaceRefundAdapter
from apps.integrations import tiktok_sales_fields
from apps.influencers.tiktok_shop_dataset import project_order, project_video, project_creator
from tests.test_formal_live_readonly_merge import _scope, _run
from tests.test_tiktok_dataset_checkpoint import make_client
from unittest.mock import Mock


NOW = int(datetime(2026, 10, 16, 17, tzinfo=UTC).timestamp())


def order_record():
    return {
        "id": "synthetic-order", "status": "DELIVERED", "create_time": NOW, "update_time": NOW + 10,
        "paid_time": NOW + 1, "delivery_time": NOW + 9,
        "payment": {"currency": "PHP", "total_amount": "272.18", "shipping_fee": "19.98",
                    "sub_total": "252.20", "seller_discount": "320", "platform_discount": "26.80", "tax": "0"},
        "line_items": [{"id": "synthetic-line", "sku_id": "synthetic-sku", "product_id": "synthetic-product",
                        "seller_sku": "SELLER", "product_name": "Synthetic product", "sku_name": "Blue",
                        "currency": "PHP", "original_price": "599", "sale_price": "279",
                        "seller_discount": "320", "platform_discount": "26.80", "display_status": "DELIVERED"}],
    }


def refund_record():
    amount = {"currency": "PHP", "refund_total": "115", "refund_subtotal": "110",
              "refund_shipping_fee": "4", "refund_tax": "1"}
    return {"return_id": "synthetic-return", "order_id": "synthetic-order", "return_type": "RETURN_AND_REFUND",
            "return_status": "RETURN_OR_REFUND_REQUEST_COMPLETE", "return_reason": "synthetic-reason",
            "create_time": NOW + 20, "update_time": NOW + 30, "refund_amount": amount,
            "return_line_items": [{"return_line_item_id": "synthetic-return-line", "order_line_item_id": "synthetic-line",
                                   "sku_id": "synthetic-sku", "seller_sku": "SELLER", "product_name": "Synthetic product",
                                   "refund_amount": deepcopy(amount)}]}


def adapter(cls=MarketplaceOrderAdapter, zone="Asia/Manila"):
    value = cls(SimpleNamespace(platform="tiktok", platform_config={}))
    value.authorization = SimpleNamespace(store=SimpleNamespace(id=1, currency="PHP", timezone=zone), region="PH")
    return value


def test_projection_preserves_distinct_prices_discounts_subtotal_and_original_status():
    value = adapter().normalize_record(order_record())
    assert value["gross_amount"] == "272.18" and value["subtotal_amount"] == "252.20"
    assert value["seller_discount_amount"] == "320" and value["platform_discount_amount"] == "26.80"
    assert value["discount_amount"] == "346.80"
    assert value["raw_status"] == "DELIVERED" and value["order_status"] == "fulfilled"
    assert value["business_date"] == "2026-10-17"
    assert value["delivered_at_utc"] == datetime.fromtimestamp(NOW + 9, UTC).isoformat()
    assert value["completed_at_utc"] is None
    line = value["lines"][0]
    assert line["original_unit_price"] == "599" and line["sale_unit_price"] == "279"
    assert line["discount_amount"] == "346.80" and line["variation_snapshot"] == "Blue"
    assert line["quantity"] == 1


@pytest.mark.parametrize("zone,day", [("Asia/Manila", "2026-10-17"), ("Asia/Bangkok", "2026-10-17"), ("UTC", "2026-10-16")])
def test_business_date_uses_store_timezone(zone, day):
    assert adapter(zone=zone).normalize_record(order_record())["business_date"] == day


@pytest.mark.parametrize("field", ["sub_total", "seller_discount", "platform_discount", "tax", "total_amount", "shipping_fee"])
@pytest.mark.parametrize("bad", [None, "", "bad", "NaN", "Infinity", "-1", True, 1.25])
def test_missing_or_invalid_money_is_not_fabricated_as_zero(field, bad):
    value = order_record()
    value["payment"][field] = bad
    with pytest.raises(ValidationError, match="TK_SALES_MONEY"):
        adapter().normalize_record(value)


def test_explicit_zero_is_preserved_without_falling_back_to_original_price():
    value = order_record()
    value["line_items"][0]["sale_price"] = "0"
    assert adapter().normalize_record(value)["lines"][0]["sale_unit_price"] == "0"


def test_line_currency_conflict_is_rejected():
    value = order_record()
    value["line_items"][0]["currency"] = "USD"
    with pytest.raises(ValidationError, match="CURRENCY"):
        adapter().normalize_record(value)


@pytest.mark.parametrize("status,expected", list(tiktok_sales_fields.REFUND_STATUSES.items()))
def test_exact_refund_status_mapping(status, expected):
    value = refund_record()
    value["return_status"] = status
    normalized = adapter(MarketplaceRefundAdapter).normalize_record(value)
    assert normalized["raw_status"] == status
    assert normalized["normalized_status"] == expected


def test_unknown_refund_status_does_not_become_completed():
    value = refund_record()
    value["return_status"] = "FUTURE_COMPLETE_STATUS"
    with pytest.raises(ValidationError, match="UNMAPPED"):
        adapter(MarketplaceRefundAdapter).normalize_record(value)


@pytest.mark.parametrize("bad", [None, {}, {"amount": "115", "currency": "PHP"}, {"refund_total": "115", "currency": "USD"}])
def test_refund_line_invalid_structure_is_not_zero(bad):
    value = refund_record()
    value["return_line_items"][0]["refund_amount"] = bad
    with pytest.raises(ValidationError):
        adapter(MarketplaceRefundAdapter).normalize_record(value)


@pytest.mark.django_db
def test_adapter_to_database_keeps_source_facts_and_replays_idempotently():
    tenant, user, store, _warehouse = _scope("tk-sales-fields", platform_type="tiktok")
    job, run = _run(tenant, user, "sales_order", "tiktok")
    orders = MarketplaceOrderAdapter(job.integration_config)
    orders.authorization = SimpleNamespace(store=store, region="PH")
    orders.bind_run(run)
    normalized = orders.normalize_record(order_record())
    assert orders.persist_record(job, normalized)["action"] == "created"
    assert orders.persist_records(job, [normalized])[0]["action"] == "skipped"
    saved = SalesOrder.objects.get(tenant=tenant, store=store)
    assert saved.raw_status == "DELIVERED" and saved.business_date.isoformat() == "2026-10-17"
    assert saved.subtotal_amount == Decimal("252.20") and saved.seller_discount_amount == 320
    assert saved.platform_discount_amount == Decimal("26.80")
    assert saved.completed_at_utc is None and saved.delivered_at_utc == datetime.fromtimestamp(NOW + 9, UTC)
    assert saved.items.get().original_unit_price == 599 and saved.items.get().sale_unit_price == 279
    assert saved.items.get().discount_amount == Decimal("346.80")
    assert saved.items.get().variation_snapshot == "Blue"
    refund_job, refund_run = _run(tenant, user, "refund_return", "tiktok")
    refunds = MarketplaceRefundAdapter(refund_job.integration_config)
    refunds.authorization = SimpleNamespace(store=store, region="PH")
    refunds.bind_run(refund_run)
    projected = refunds.normalize_record(refund_record())
    assert refunds.persist_record(refund_job, projected)["action"] == "created"
    assert refunds.persist_records(refund_job, [projected])[0]["action"] == "skipped"
    saved_refund = saved.refund_returns.get()
    assert saved_refund.normalized_status == "completed" and saved_refund.refund_amount == 115
    assert saved_refund.items.get().refund_amount == 115
    assert saved_refund.items.get().sales_order_item_id == saved.items.get().pk


def test_other_tiktok_projections_preserve_unknown_separately_from_explicit_zero():
    affiliate = project_order({"id": "synthetic-order", "create_time": NOW}, {
        "sku_id": "synthetic-sku", "product_id": "synthetic-product", "actual_paid_shop_ads_commission": {"amount": "0", "currency": "PHP"}})
    assert affiliate["actual_paid_shop_ads_commission"] == {"amount": "0", "currency": "PHP"}
    assert affiliate["estimated_commission_base"]["amount"] is None
    assert affiliate["actual_paid_commission"]["amount"] is None and affiliate["payment_amount"] is None
    video = project_video({"id": "synthetic-video", "total_performance": {"views": 0}}, "2026-10-17")
    assert video["metrics"]["views"] == 0 and video["metrics"]["likes"] is None
    assert video["metrics"]["gmv"]["amount"] is None
    creator = project_creator({"username": "synthetic"}, "123456789", None)
    assert creator["follower_count"] is None


@pytest.mark.parametrize("status", ["DELIVERED", "COMPLETED"])
def test_delivery_is_not_completion_evidence(status):
    value = order_record()
    value["status"] = status
    normalized = adapter().normalize_record(value)
    assert normalized["delivered_at_utc"] is not None and normalized["completed_at_utc"] is None


def test_nonzero_tax_is_carried_to_canonical_contract():
    value = order_record()
    value["payment"]["tax"] = "12.34"
    assert adapter().normalize_record(value)["tax_amount"] == "12.34"


@pytest.mark.parametrize("prices,expected", [(["2", "2"], "2"), (["2", "3"], None), (["2", "3", "2"], None)])
def test_affiliate_price_enrichment_accepts_distinct_unit_lines_without_guessing_conflicts(prices, expected):
    auth = SimpleNamespace(store_id=1, shop_cipher="synthetic", scopes=["seller.order.info"])
    lines = [{"id": f"line-{i}", "sku_id": "sku", "sale_price": price} for i, price in enumerate(prices)]
    client = make_client(auth, [{"orders": [{"id": "one", "payment": {"total_amount": "10", "currency": "PHP"}, "line_items": lines}]}])
    client.preflight = Mock()
    client._runtime_path = Mock(return_value=client.ORDER_DETAIL_PATH)
    rows = [project_order({"id": "one"}, {"sku_id": "sku", "product_id": "product"})]
    client.enrich_orders(rows)
    assert rows[0]["price"]["amount"] == expected
    assert rows[0]["payment_amount"] is None


def test_affiliate_enrichment_still_rejects_duplicate_line_id():
    auth = SimpleNamespace(store_id=1, shop_cipher="synthetic", scopes=["seller.order.info"])
    line = {"id": "same-line", "sku_id": "sku", "sale_price": "2"}
    client = make_client(auth, [{"orders": [{"id": "one", "payment": {"total_amount": "4", "currency": "PHP"}, "line_items": [line, line]}]}])
    client.preflight = Mock()
    client._runtime_path = Mock(return_value=client.ORDER_DETAIL_PATH)
    rows = [project_order({"id": "one"}, {"sku_id": "sku", "product_id": "product"})]
    from apps.influencers.tiktok_shop_dataset import DatasetError
    with pytest.raises(DatasetError, match="invalid_order_detail_identity"):
        client.enrich_orders(rows)
