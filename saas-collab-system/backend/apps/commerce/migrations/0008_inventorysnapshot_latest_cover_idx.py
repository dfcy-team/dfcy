from django.db import migrations, models


OLD_FIELDS = ["tenant", "site_code", "warehouse", "source_sku", "-snapshot_at_utc", "-id"]
NEW_FIELDS = [*OLD_FIELDS, "source_run"]


def swap_index(apps, schema_editor, *, reverse=False):
    old_name, new_name = "idx_inv_latest_lookup", "idx_inv_latest_cover"
    old_fields, new_fields = OLD_FIELDS, NEW_FIELDS
    if reverse:
        old_name, new_name = new_name, old_name
        old_fields, new_fields = new_fields, old_fields
    if schema_editor.connection.vendor == "mysql":
        columns = (
            "`tenant_id`, `site_code`, `warehouse_id`, `source_sku`, "
            "`snapshot_at_utc` DESC, `id` DESC"
        )
        if not reverse:
            columns += ", `source_run_id`"
        # Online DDL still needs metadata locks. Bound only this migration's
        # session lock wait, and restore the connection setting afterwards.
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SELECT @@SESSION.lock_wait_timeout")
            previous_lock_wait = cursor.fetchone()[0]
            cursor.execute("SET SESSION lock_wait_timeout = %s", [15])
        try:
            schema_editor.execute(
                f"ALTER TABLE `inventory_snapshot` ADD INDEX `{new_name}` ({columns}), "
                f"DROP INDEX `{old_name}`, ALGORITHM=INPLACE, LOCK=NONE"
            )
        finally:
            with schema_editor.connection.cursor() as cursor:
                cursor.execute("SET SESSION lock_wait_timeout = %s", [previous_lock_wait])
    else:
        model = apps.get_model("commerce", "InventorySnapshot")
        schema_editor.add_index(model, models.Index(fields=new_fields, name=new_name))
        schema_editor.remove_index(model, models.Index(fields=old_fields, name=old_name))


def forwards(apps, schema_editor):
    swap_index(apps, schema_editor)


def backwards(apps, schema_editor):
    swap_index(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("commerce", "0007_inventorysnapshot_provided_quantity_fields")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(forwards, backwards)],
            state_operations=[
                migrations.RemoveIndex(model_name="inventorysnapshot", name="idx_inv_latest_lookup"),
                migrations.AddIndex(
                    model_name="inventorysnapshot",
                    index=models.Index(fields=NEW_FIELDS, name="idx_inv_latest_cover"),
                ),
            ],
        ),
    ]
