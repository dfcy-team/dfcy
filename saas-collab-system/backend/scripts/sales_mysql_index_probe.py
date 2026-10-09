"""Apply and reverse the exact sales index migration on disposable MySQL only."""
import importlib
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django
django.setup()

from django.db import connection
from django.db.migrations.loader import MigrationLoader

assert os.environ.get("SYNTHETIC_SALES_TEST_ONLY") == "true"
assert connection.vendor == "mysql"
assert connection.settings_dict["HOST"] == "127.0.0.1"
assert connection.settings_dict["NAME"] == "test_synthetic_sales_reports"
migration = importlib.import_module("apps.commerce.migrations.0006_salesorder_currency_catalog_idx").Migration
assert len(migration.operations) == 1
operation = migration.operations[0]
assert operation.index.name == "idx_sales_order_currency"
loader = MigrationLoader(connection)
before = loader.project_state([("commerce", "0005_inventorysnapshot_tenant_recent_idx")])
after = before.clone()
operation.state_forwards("commerce", after)
model = after.apps.get_model("commerce", "SalesOrder")
table = model._meta.db_table

def constraint():
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, table).get(operation.index.name)

def row_count():
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM " + connection.ops.quote_name(table))
        return cursor.fetchone()[0]

rows_before = row_count()
assert constraint() is not None and constraint()["columns"] == ["tenant_id", "currency"]
with connection.schema_editor(atomic=False) as editor:
    operation.database_backwards("commerce", editor, after, before)
assert constraint() is None
with connection.schema_editor(atomic=False) as editor:
    operation.database_forwards("commerce", editor, before, after)
assert constraint() is not None and constraint()["columns"] == ["tenant_id", "currency"]
rows_after = row_count()
assert rows_after == rows_before
print(json.dumps({
    "status": "pass", "migration": "commerce.0006_salesorder_currency_catalog_idx",
    "index": operation.index.name, "columns": ["tenant_id", "currency"],
    "forward_and_reverse_checked": True, "rows_unchanged": True,
    "rows_before": rows_before, "rows_after": rows_after,
    "schema_mode": "synthetic current-model schema",
    "fresh_migration_chain_validated": False, "production_database_used": False,
}))
