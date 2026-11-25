"""Focused regressions for the 534/536 release fixes; all platform replies are mocked."""
import importlib
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.db import connection
from rest_framework.exceptions import ValidationError

from apps.integrations.best_glink import BestGlinkClient
from apps.sales_management import warehouse_unified
from apps.flash_sales.provider import _manual_credential_recovery_required

index_migration = importlib.import_module("apps.sales_management.migrations.0013_warehouse_lookup_requested_index")


def _client(rows):
    client = BestGlinkClient(
        SimpleNamespace(platform_config={"customer_code": "C"}),
        SimpleNamespace(external_warehouse_code="W"), http_client=Mock(), custody=Mock(),
    )
    client.query = Mock(return_value={"inventoryVOList": [
        {"sku": sku, "customerCode": "C", "warehouseCode": "W", "skuStatus": "GOOD",
         "totalQty": total, "salableQty": normal} for sku, total, normal in rows
    ]})
    return client


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None, True, 1.5, [], "bad"])
def test_inventory_rejects_bad_quantity_without_dropping_sku(bad):
    client = _client([("bad", bad, 1), ("ok", 4, 2)])
    with pytest.raises(ValidationError):
        client.fetch_inventory(None, {"sku_codes": ["bad", "ok"]})


def test_inventory_filters_only_valid_negative_and_requires_full_coverage():
    client = _client([("negative", -1, 0), ("kept", 3, 2)])
    assert [r["itemSkuCode"] for r in client.fetch_inventory(None, {"sku_codes": ["negative", "kept"]})["records"]] == ["kept"]
    client = _client([("negative", -1, 0)])
    with pytest.raises(ValidationError):
        client.fetch_inventory(None, {"sku_codes": ["negative", "missing"]})


@pytest.mark.django_db(transaction=True)
def test_index_existing_metadata_and_reverse_preserve_index_sqlite():
    table = "vm537_index_probe"
    # SQLite index names are database-global; this migration's real index may
    # already exist on the migrated model table in the isolated test database.
    with connection.cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=%s", [index_migration.INDEX_NAME])
        original_sql = cursor.fetchone()
        if original_sql:
            cursor.execute(f'DROP INDEX "{index_migration.INDEX_NAME}"')
    with connection.cursor() as cursor:
        cursor.execute(f'DROP TABLE IF EXISTS "{table}"')
        cursor.execute(f'CREATE TABLE "{table}" (id integer, requested_at text, other text)')
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE INDEX "{index_migration.INDEX_NAME}" ON "{table}" (requested_at, id)')
        existing = {"columns": ["requested_at", "id"], "index": True, "unique": False}
        index_migration.validate_existing(connection, table, existing)
        with pytest.raises(RuntimeError):
            index_migration.validate_existing(connection, table, {**existing, "columns": ["id", "requested_at"]})
        with connection.cursor() as cursor:
            cursor.execute(f'DROP INDEX "{index_migration.INDEX_NAME}"')
            cursor.execute(f'CREATE INDEX "{index_migration.INDEX_NAME}" ON "{table}" (requested_at DESC, id)')
        with pytest.raises(RuntimeError):
            index_migration.validate_existing(connection, table, existing)
        with connection.cursor() as cursor:
            cursor.execute(f'DROP INDEX "{index_migration.INDEX_NAME}"')
            cursor.execute(f'CREATE INDEX "{index_migration.INDEX_NAME}" ON "{table}" (requested_at, id) WHERE id > 0')
        with pytest.raises(RuntimeError):
            index_migration.validate_existing(connection, table, existing)
        with connection.cursor() as cursor:
            cursor.execute(f'DROP INDEX "{index_migration.INDEX_NAME}"')
            cursor.execute(f'CREATE INDEX "{index_migration.INDEX_NAME}" ON "{table}" (requested_at, id)')
        # Run the migration's actual database reverse operation against SQLite.
        from django.db.migrations.state import ProjectState
        with connection.schema_editor() as schema_editor:
            index_migration.Migration.operations[0].database_operations[0].database_backwards(
                "sales_management", schema_editor, ProjectState(), ProjectState())
        assert connection.introspection.get_constraints(connection.cursor(), table)[index_migration.INDEX_NAME]["index"]
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}"')
            if original_sql:
                cursor.execute(original_sql[0])


def test_cancelled_sync_result_is_not_reported_as_queried():
    eligible = Mock()
    eligible.select_for_update.return_value.order_by.return_value.values_list.return_value.first.return_value = 55
    row = SimpleNamespace(pk=55, revision=3, status="pending")
    scoped = Mock()
    scoped.filter.return_value = eligible
    job = SimpleNamespace(resource_type="warehouse_order_lookup", tenant_id=7,
                          warehouse_authorization=SimpleNamespace(tenant_id=7, warehouse=SimpleNamespace(tenant_id=7, country_code="MY")))
    with patch.object(warehouse_unified.OrderWarehouseLookup.objects, "filter", return_value=scoped), \
         patch.object(warehouse_unified.OrderWarehouseLookup.objects, "select_related") as select_related, \
         patch.object(warehouse_unified.transaction, "atomic", return_value=nullcontext()), \
         patch("apps.sales_management.warehouse_orders.synchronize", return_value="cancelled"):
        select_related.return_value.defer.return_value.get.return_value = row
        result = warehouse_unified.process_next_lookup(job)
    assert result == {"lookup_id": 55, "status": "cancelled", "queried": False}


def test_disabled_refresh_without_manual_flag_still_requires_recovery():
    with patch("apps.flash_sales.provider.credential_refresh_state", return_value={"state": "disabled", "requires_manual_recovery": False}):
        assert _manual_credential_recovery_required(object()) is True
