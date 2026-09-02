from django.db import migrations


def reconcile_metadata(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    # The catalog is the source of truth for the administration UI.  Older
    # migrations seeded a mixture of English and interim Chinese metadata;
    # reconcile every definition so existing installations and fresh test
    # databases share the same permission contract.
    from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults

    for definition in PERMISSION_DEFINITIONS:
        code = definition["code"]
        Permission.objects.update_or_create(
            code=code,
            defaults=permission_defaults(definition),
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0033_seed_masterdata_settings_permissions")]

    operations = [migrations.RunPython(reconcile_metadata, migrations.RunPython.noop)]
