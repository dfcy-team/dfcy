from django.db import migrations, models


def ensure_estimated_base_column(apps, schema_editor):
    model = apps.get_model("influencers", "AffiliateOrderSnapshot")
    table = model._meta.db_table
    name = "estimated_commission_base"
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, table)
        column = next((item for item in columns if item.name == name), None)
        if column is not None:
            # Adopt the schema-only VM34 hotfix, but never hide incompatible DDL.
            compatible = column.null_ok and (
                connection.introspection.get_field_type(column.type_code, column) == "DecimalField"
            )
            if connection.vendor == "mysql":
                cursor.execute(
                    "SELECT DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE, COLUMN_DEFAULT "
                    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME=%s AND COLUMN_NAME=%s",
                    [table, name],
                )
                compatible = cursor.fetchone() == ("decimal", 20, 4, "YES", None)
            if not compatible:
                raise RuntimeError("Existing estimated_commission_base column is incompatible.")
            return
    field = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    field.set_attributes_from_name(name)
    field.model = model
    schema_editor.add_field(model, field)


class Migration(migrations.Migration):
    dependencies = [("influencers", "0032_profile_reference_plain_text")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(ensure_estimated_base_column)],
            state_operations=[
                migrations.AddField(
                    model_name="affiliateordersnapshot",
                    name="estimated_commission_base",
                    field=models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True),
                ),
            ],
        ),
    ]
