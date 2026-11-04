from types import SimpleNamespace

from apps.integrations.readonly_clients import ShopeeReadonlyClient


def collect(income):
    client = ShopeeReadonlyClient(SimpleNamespace(platform="shopee", platform_config={}), custody=object())
    client._runtime_path = lambda _key, fallback: fallback

    def request(path, _query):
        if path.endswith("get_escrow_list"):
            return {"response": {"escrow_list": [{"order_sn": "SUMMARY-1", "escrow_release_time": 10}], "more": False}}
        return {"response": {"order_sn": "SUMMARY-1", "order_income": {"currency": "PHP", **income}}}

    client._request = request
    return client.fetch_finance_transactions("", {"time_from": 1, "time_to": 20, "page_size": 100})


def test_summary_collects_discounts_shipping_rebates_and_adjustments_without_alias_loss():
    income = {"escrow_amount": "203", "order_original_price": "498", "original_price": "498",
              "seller_discount": "233", "shopee_shipping_rebate": "107", "actual_shipping_fee": "107",
              "commission_fee": "32", "service_fee": "24", "seller_transaction_fee": "6",
              "voucher_from_seller": "0", "total_adjustment_amount": "0", "escrow_amount_after_adjustment": "203"}
    page = collect(income)
    assert {row["fee_name"]: row["amount"] for row in page["records"]} == income
    assert len({row["source_key"] for row in page["records"]}) == len(income)
    assert all(row["currency"] == "PHP" and row["order_id"] == "SUMMARY-1" for row in page["records"])
    assert page["raw_responses"][-1]["payload"]["response"]["order_income"]["original_price"] == "498"


def test_summary_preserves_real_zero_negative_adjustments_and_missing_fields():
    page = collect({"seller_return_refund": 0, "total_adjustment_amount": "-659",
                    "escrow_amount_after_adjustment": "-201", "seller_discount": None,
                    "shopee_shipping_rebate": "", "buyer_user_name": "NOT-A-MONEY-FIELD"})
    assert {row["fee_name"]: row["amount"] for row in page["records"]} == {
        "seller_return_refund": 0, "total_adjustment_amount": "-659", "escrow_amount_after_adjustment": "-201"}
