import hashlib
import json

import pytest

from apps.demo_sync.pipeline import RESOURCES, SnapshotError, build_snapshot


def dataset():
    return {
        "platforms": [{"id": 1, "code": "shop", "name": "Store Brand", "platform_type": "bigseller", "private_key": "discard"}],
        "country_sites": [{"id": 2, "code": "gb", "name": "UK Retail", "country_code": "GB", "platform_id": 1, "currency": "GBP", "timezone": "Europe/London"}],
        "stores": [
            {"id": 10, "code": "london", "name": "Named Shop", "external_store_id": "real-store-identity", "platform_id": 1, "country_site_id": 2, "country_code": "GB", "currency": "GBP"},
            {"id": 11, "code": "other", "name": "Out of scope", "platform_id": 1, "country_code": "GB", "currency": "GBP"},
        ],
        "warehouses": [{"id": 20, "code": "wh", "name": "Named Warehouse", "country_code": "GB", "warehouse_type": "owned", "service_platform_id": 1}],
        "product_categories": [], "products": [], "product_details": [],
        "sales_orders": [
            {"id": 30, "platform_id": 1, "store_id": 10, "external_order_id": "REAL-ORDER-123", "raw_status": "paid", "normalized_status": "pending", "created_at_utc": "2026-01-02T00:00:00Z", "updated_at_utc": "2026-01-02T00:00:00Z", "business_date": "2026-01-02", "currency": "GBP", "order_total_amount": "1.2300", "buyer_email": "private@example.test"},
            {"id": 31, "platform_id": 1, "store_id": 11, "external_order_id": "OUT-OF-SCOPE", "raw_status": "paid"},
        ],
        "sales_order_items": [],
        "inventory_snapshots": [{"id": 40, "warehouse_id": 20, "source_sku": "REAL-SKU", "snapshot_at_utc": "2026-01-02T00:00:00Z", "on_hand_qty": 4}],
    }


class FakeClient:
    masking_key = b"a sufficiently long synthetic masking secret key"

    def __init__(self, data):
        self.data = data
        self.calls = []

    def fetch(self, resource, params):
        self.calls.append((resource, params))
        return {"items": self.data[resource], "has_more": False, "next_cursor": None}


def test_snapshot_scopes_masks_and_hashes_all_required_files(tmp_path):
    client = FakeClient(dataset())
    manifest = build_snapshot(
        client=client, resources=["sales_orders", "inventory_snapshots"], store_ids=[10], warehouse_ids=[20],
        date_from="2026-01-01", date_to="2026-01-31", output_dir=tmp_path / "batch",
        scope_key="tenant-scope",
    )

    assert manifest["schema_version"] == "demo-snapshot.v1"
    assert manifest["consistent"] is False and manifest["deidentified"] is True
    assert {entry["resource"] for entry in manifest["files"]} == set(RESOURCES)
    assert {name for name, _ in client.calls} == {
        "platforms", "country_sites", "stores", "warehouses", "product_categories", "products",
        "product_details", "sales_orders", "sales_order_items", "inventory_snapshots",
    }
    for name, params in client.calls:
        assert params["limit"] == 1000
        assert "scope_key" not in params and "store_ids" not in params and "warehouse_ids" not in params
        if name in {"sales_orders", "sales_order_items"}:
            assert params["store_id"] == "10" and params["date_from"] == "2026-01-01"
        elif name == "inventory_snapshots":
            assert params["warehouse_id"] == "20" and params["date_to"] == "2026-01-31"
        else:
            assert "date_from" not in params and "date_to" not in params

    order_file = tmp_path / "batch" / "sales_orders.jsonl"
    order_bytes = order_file.read_bytes()
    order = json.loads(order_bytes)
    entry = next(item for item in manifest["files"] if item["resource"] == "sales_orders")
    assert entry["count"] == 1
    assert hashlib.sha256(order_bytes).hexdigest() == entry["sha256"]
    assert order["external_order_id"] != "REAL-ORDER-123"
    assert "buyer_email" not in order and "private@example.test" not in order_bytes.decode()
    assert json.loads((tmp_path / "batch" / "stores.jsonl").read_text())["name"] != "Named Shop"


def test_snapshot_requires_injected_secret_and_rejects_missing_relations(tmp_path):
    client = FakeClient(dataset())
    client.masking_key = b"short"
    with pytest.raises(SnapshotError, match="masking_key"):
        build_snapshot(client=client, resources=["sales_orders"], store_ids=[10], warehouse_ids=[20],
                       date_from="2026-01-01", date_to="2026-01-31", output_dir=tmp_path / "bad",
                       scope_key="scope")

    broken = dataset()
    broken["sales_orders"][0]["platform_id"] = 999
    with pytest.raises(SnapshotError, match="relationships"):
        build_snapshot(client=FakeClient(broken), resources=["sales_orders"], store_ids=[10], warehouse_ids=[20],
                       date_from="2026-01-01", date_to="2026-01-31", output_dir=tmp_path / "bad",
                       scope_key="scope")


def test_snapshot_rejects_category_parent_cycles(tmp_path):
    data = dataset()
    data["product_categories"] = [
        {"id": 50, "parent_id": 51, "level": 2, "code": "01", "name": "Child"},
        {"id": 51, "parent_id": 50, "level": 1, "code": "1", "name": "Parent"},
    ]
    with pytest.raises(SnapshotError, match="parent cycle"):
        build_snapshot(client=FakeClient(data), resources=["product_categories"], store_ids=[10], warehouse_ids=[20],
                       date_from="2026-01-01", date_to="2026-01-31", output_dir=tmp_path / "cycle",
                       scope_key="scope")
