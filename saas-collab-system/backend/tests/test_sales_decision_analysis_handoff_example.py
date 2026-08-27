import json
from decimal import Decimal
from pathlib import Path


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "03_api"
    / "examples"
    / "sales_decision_analysis_handoff.example.json"
)
FORBIDDEN_KEYS = {
    "app_secret",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "secret_key",
    "sign",
    "cookie",
}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).lower()
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def test_sales_decision_analysis_example_is_linked_and_internally_consistent():
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    sales = payload["sales_management"]
    decision = payload["business_decision"]
    analysis = payload["business_analysis"]

    assert payload["schema_version"] == "operations-data-handoff.v1"
    assert payload["synthetic"] is True
    assert FORBIDDEN_KEYS.isdisjoint(_walk_keys(payload))

    store_rows = sales["store_sales"]
    assert sum(Decimal(row["gross_sales"]) for row in store_rows) == Decimal(sales["summary"]["gross_sales"])
    assert sum(Decimal(row["refund_amount"]) for row in store_rows) == Decimal(sales["summary"]["refund_amount"])
    assert sum(Decimal(row["net_sales"]) for row in store_rows) == Decimal(sales["summary"]["net_sales"])
    assert sum(row["order_count"] for row in store_rows) == sales["summary"]["order_count"]
    assert sum(row["units_sold"] for row in store_rows) == sales["summary"]["units_sold"]

    warehouse_codes = set(payload["source_links"]["warehouses"])
    alert_ids = {row["alert_id"] for row in decision["inventory_alerts"]}
    assert {row["warehouse_code"] for row in decision["inventory_alerts"]} <= warehouse_codes
    assert {row["warehouse_code"] for row in decision["replenishment_recommendations"]} <= warehouse_codes
    assert {row["source_alert_id"] for row in decision["replenishment_recommendations"]} <= alert_ids
    assert {row["warehouse_code"] for row in analysis["inventory_items"]} <= warehouse_codes

    metrics = analysis["overview"]["summary_metrics"]
    assert Decimal(metrics["gross_sales"]) == Decimal(sales["summary"]["gross_sales"])
    assert Decimal(metrics["refund_amount"]) == Decimal(sales["summary"]["refund_amount"])
    assert Decimal(metrics["net_sales"]) == Decimal(sales["summary"]["net_sales"])
    assert metrics["available_qty"] == sum(row["available_qty"] for row in analysis["inventory_items"])
    assert metrics["inventory_risk_count"] == len(decision["inventory_alerts"])
