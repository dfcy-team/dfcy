from datetime import timedelta
from unittest.mock import patch

import pytest

from apps.commerce.models import InventorySnapshot
from apps.listings.warehouse_sku_views import _latest_facts
from apps.integrations.models import IntegrationAuditLog
from apps.permissions.models import DataScope
from tests.test_inventory_auto_sku_links import inventory_link
from tests.test_sales_management import NOW, client_for, grant, user_for

pytestmark = pytest.mark.django_db
URL = "/api/internal/listings/warehouse-skus/"


def viewer(tenant, confirm=True, scope=None):
    user = user_for(tenant, f"warehouse-viewer-{tenant.id}-{confirm}-{bool(scope)}")
    for code in ["view"] + (["confirm"] if confirm else []):
        grant(
            user,
            "integrations.product_mapping." + code,
            DataScope.ScopeType.CUSTOM if scope else DataScope.ScopeType.ALL,
            scope,
        )
    return client_for(user)


def test_list_is_readonly_and_latest_per_warehouse(inventory_link):
    tenant, warehouse, _, sku, ingest, history = inventory_link
    history("OLD-SKU", at=NOW - timedelta(days=1))
    row = ingest()
    client = viewer(tenant)
    before = IntegrationAuditLog.objects.count()
    data = client.get(URL).json()["data"]
    assert data["count"] == 1
    assert data["results"][0]["id"] == row.id
    assert data["results"][0]["warehouse_name"] == warehouse.name
    assert client.get(URL, {"status": "unmapped"}).json()["data"]["count"] == 0
    info = client.get(f"{URL}{row.id}/mapping/").json()["data"]
    assert info["suggested_sku_id"] == sku.id
    assert IntegrationAuditLog.objects.count() == before


def test_list_keeps_case_distinct_source_skus(inventory_link):
    tenant, _, _, _, _, history = inventory_link
    upper = history("Case-SKU", target=None, at=NOW - timedelta(minutes=1))
    lower = history("case-sku", target=None, at=NOW)
    data = viewer(tenant).get(URL).json()["data"]
    assert data["count"] == 2
    assert {row["id"] for row in data["results"]} == {upper.id, lower.id}


def test_latest_rows_use_one_window_scan_not_a_correlated_subquery(inventory_link):
    tenant, _, _, _, _, history = inventory_link
    history("SKU-A", target=None, at=NOW - timedelta(minutes=2))
    newest = history("SKU-A", target=None, at=NOW)
    query = _latest_facts(InventorySnapshot.objects.filter(tenant=tenant))
    sql = str(query.query).upper()
    assert "ROW_NUMBER() OVER" in sql
    assert "OUTERREF" not in sql
    assert list(query.values_list("id", flat=True)) == [newest.id]


def test_confirm_updates_links_only_and_future_sync_inherits(inventory_link):
    tenant, _, _, sku, ingest, history = inventory_link
    old = history("ALIAS", target=None)
    row = ingest("ALIAS")
    client = viewer(tenant)
    url = f"{URL}{row.id}/mapping/"
    payload = {"sku_id": sku.id, "expected_sku_ids": [], "confirmed": True}
    result = client.patch(url, payload, format="json")
    assert result.status_code == 200, result.data
    assert result.data["data"]["updated_count"] == 2
    old.refresh_from_db()
    row.refresh_from_db()
    assert old.internal_sku_id == row.internal_sku_id == sku.id
    assert (row.on_hand_qty, row.available_qty, row.reserved_qty) == (10, 8, 2)
    assert IntegrationAuditLog.objects.filter(action="inventory_manual_sku_link").count() == 1
    # A replay with stale expectations is rejected, not applied again.
    assert client.patch(url, payload, format="json").status_code == 400
    payload["expected_sku_ids"] = [sku.id]
    assert client.patch(url, payload, format="json").data["data"]["updated_count"] == 0
    future = ingest("ALIAS", seller_sku="DIFFERENT", snapshot_at_utc=NOW + timedelta(days=1))
    assert future.internal_sku_id == sku.id


def test_permissions_tenant_scope_and_confirmation(inventory_link):
    from tests.test_sales_management import create_scope

    tenant, warehouse, _, sku, ingest, _ = inventory_link
    row = ingest("UNKNOWN")
    url = f"{URL}{row.id}/mapping/"
    payload = {"sku_id": sku.id, "expected_sku_ids": [], "confirmed": True}
    assert viewer(tenant, confirm=False).patch(url, payload, format="json").status_code == 403
    other, _, _, _ = create_scope("other-warehouse-tenant")
    other_client = viewer(other)
    assert other_client.get(URL).data["data"]["count"] == 0
    assert other_client.get(url).status_code == 404
    assert other_client.patch(url, payload, format="json").status_code == 404
    scoped = viewer(tenant, scope={"warehouse_ids": [warehouse.id + 100]})
    assert scoped.get(URL).data["data"]["count"] == 0
    assert scoped.patch(url, payload, format="json").status_code == 404
    client = viewer(tenant)
    assert client.patch(url, {**payload, "confirmed": "true"}, format="json").status_code == 400
    assert client.patch(url, {**payload, "sku_id": sku.id + 100}, format="json").status_code == 404


def test_audit_failure_rolls_back_manual_link(inventory_link):
    tenant, _, _, sku, ingest, _ = inventory_link
    row = ingest("UNKNOWN")
    client = viewer(tenant)
    with patch(
        "apps.listings.warehouse_sku_views.IntegrationAuditLog.objects.create",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            client.patch(
                f"{URL}{row.id}/mapping/",
                {"sku_id": sku.id, "expected_sku_ids": [], "confirmed": True},
                format="json",
            )
    row.refresh_from_db()
    assert row.internal_sku_id is None
