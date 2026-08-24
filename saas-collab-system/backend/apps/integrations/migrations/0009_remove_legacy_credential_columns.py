from django.db import migrations


LEGACY_FIELDS = (
    ("APIIntegrationConfig", "api_key_encrypted"),
    ("APIIntegrationConfig", "api_secret_encrypted"),
    ("PlatformIntegrationConfig", "credential_ciphertext"),
)


def _column_names(schema_editor, model):
    with schema_editor.connection.cursor() as cursor:
        return {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor,
                model._meta.db_table,
            )
        }


def remove_legacy_columns(apps, schema_editor):
    for model_name, field_name in LEGACY_FIELDS:
        model = apps.get_model("integrations", model_name)
        if field_name in _column_names(schema_editor, model):
            schema_editor.remove_field(model, model._meta.get_field(field_name))


def restore_legacy_columns(apps, schema_editor):
    for model_name, field_name in LEGACY_FIELDS:
        model = apps.get_model("integrations", model_name)
        if field_name not in _column_names(schema_editor, model):
            schema_editor.add_field(model, model._meta.get_field(field_name))


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0008_migrate_legacy_credential_references"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(remove_legacy_columns, restore_legacy_columns),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="apiintegrationconfig",
                    name="api_key_encrypted",
                ),
                migrations.RemoveField(
                    model_name="apiintegrationconfig",
                    name="api_secret_encrypted",
                ),
                migrations.RemoveField(
                    model_name="platformintegrationconfig",
                    name="credential_ciphertext",
                ),
            ],
        ),
    ]

