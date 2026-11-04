from django.db import migrations, models


INDEX_NAME = "idx_audit_tenant_action_result"
INDEX_FIELDS = ["tenant", "action", "result"]


def add_index(apps, schema_editor):
    model = apps.get_model("integrations", "IntegrationAuditLog")
    table = model._meta.db_table
    columns = [model._meta.get_field(field).column for field in INDEX_FIELDS]
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        existing = connection.introspection.get_constraints(cursor, table).get(INDEX_NAME)
        if existing is not None and connection.vendor == "mysql" and not connection.mysql_is_mariadb:
            cursor.execute(
                "SELECT COLUMN_NAME, COLLATION, SUB_PART, INDEX_TYPE, NON_UNIQUE, IS_VISIBLE "
                "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = %s AND INDEX_NAME = %s ORDER BY SEQ_IN_INDEX",
                [table, INDEX_NAME],
            )
            if list(cursor.fetchall()) != [(col, "A", None, "BTREE", 1, "YES") for col in columns]:
                raise RuntimeError(f"Unexpected existing definition for {INDEX_NAME}.")
    if existing is not None:
        if (
            not existing["index"]
            or existing["unique"]
            or existing["columns"] != columns
            or existing.get("orders", ["ASC"] * len(columns)) != ["ASC"] * len(columns)
            or existing.get("type", models.Index.suffix) != models.Index.suffix
        ):
            raise RuntimeError(f"Unexpected existing definition for {INDEX_NAME}.")
        return
    if schema_editor.connection.vendor == "mysql":
        quote = schema_editor.quote_name
        schema_editor.execute(
            f"ALTER TABLE {quote(table)} ADD INDEX {quote(INDEX_NAME)} "
            f"({', '.join(map(quote, columns))}), ALGORITHM=INPLACE, LOCK=NONE"
        )
    else:
        schema_editor.add_index(model, models.Index(fields=INDEX_FIELDS, name=INDEX_NAME))


def remove_index(apps, schema_editor):
    model = apps.get_model("integrations", "IntegrationAuditLog")
    if schema_editor.connection.vendor == "mysql":
        quote = schema_editor.quote_name
        schema_editor.execute(
            f"ALTER TABLE {quote(model._meta.db_table)} DROP INDEX {quote(INDEX_NAME)}, "
            "ALGORITHM=INPLACE, LOCK=NONE"
        )
    else:
        schema_editor.remove_index(model, models.Index(fields=INDEX_FIELDS, name=INDEX_NAME))


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("integrations", "0059_shopee_advertising_order_index")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_index, remove_index)],
            state_operations=[
                migrations.AddIndex(
                    model_name="integrationauditlog",
                    index=models.Index(fields=INDEX_FIELDS, name=INDEX_NAME),
                )
            ],
        ),
    ]
