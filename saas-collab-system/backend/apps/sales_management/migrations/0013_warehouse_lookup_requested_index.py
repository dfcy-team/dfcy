"""Add the lookup ordering index; retain additive indexes on state rollback.

An existing operational index is never owned by this migration. Database reverse
is intentionally a no-op, so application rollback cannot remove that index.
"""
from django.db import migrations, models

INDEX_NAME = "idx_wh_lookup_requested"
COLUMNS = ["requested_at", "id"]


def validate_existing(connection, table, existing):
    if existing.get("columns") != COLUMNS or not existing.get("index") or existing.get("unique"):
        raise RuntimeError("Existing warehouse lookup index definition conflicts with release")
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        if connection.vendor == "mysql":
            cursor.execute("SHOW INDEX FROM " + quote(table) + " WHERE Key_name = %s", [INDEX_NAME])
            names = [column[0] for column in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
            rows.sort(key=lambda row: row["Seq_in_index"])
            if len(rows) != 2:
                raise RuntimeError("Unexpected warehouse lookup index width")
            for position, row in enumerate(rows, 1):
                visible = (str(row.get("Visible", "")).upper() == "YES" or
                           (getattr(connection, "mysql_is_mariadb", False) and str(row.get("Ignored", "NO")).upper() == "NO"))
                if not (row["Column_name"] == COLUMNS[position - 1] and row["Seq_in_index"] == position
                        and row["Non_unique"] == 1 and row.get("Sub_part") is None
                        and row.get("Collation") == "A" and str(row["Index_type"]).upper() == "BTREE" and visible):
                    raise RuntimeError("Conflicting warehouse lookup index properties")
        elif connection.vendor == "sqlite":
            cursor.execute("PRAGMA index_xinfo(" + quote(INDEX_NAME) + ")")
            keys = [row for row in cursor.fetchall() if row[5]]
            if len(keys) != 2 or [row[2] for row in keys] != COLUMNS or any(row[3] for row in keys):
                raise RuntimeError("Conflicting warehouse lookup index order")
            cursor.execute("PRAGMA index_list(" + quote(table) + ")")
            info = next(row for row in cursor.fetchall() if row[1] == INDEX_NAME)
            if info[2] or info[4]:
                raise RuntimeError("Conflicting unique or partial warehouse lookup index")
        else:
            raise RuntimeError("Warehouse lookup index introspection is unsupported on this database")


def ensure_requested_index(apps, schema_editor):
    model = apps.get_model("sales_management", "OrderWarehouseLookup")
    with schema_editor.connection.cursor() as cursor:
        indexes = schema_editor.connection.introspection.get_constraints(cursor, model._meta.db_table)
    existing = indexes.get(INDEX_NAME)
    if existing is not None:
        validate_existing(schema_editor.connection, model._meta.db_table, existing)
        return
    schema_editor.add_index(model, models.Index(fields=COLUMNS, name=INDEX_NAME))
    with schema_editor.connection.cursor() as cursor:
        created = schema_editor.connection.introspection.get_constraints(cursor, model._meta.db_table)[INDEX_NAME]
    validate_existing(schema_editor.connection, model._meta.db_table, created)


class Migration(migrations.Migration):
    dependencies = [("sales_management", "0012_warehouse_outbound_line")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(ensure_requested_index, migrations.RunPython.noop)],
        state_operations=[migrations.AddIndex(
            model_name="orderwarehouselookup", index=models.Index(fields=COLUMNS, name=INDEX_NAME),
        )],
    )]
