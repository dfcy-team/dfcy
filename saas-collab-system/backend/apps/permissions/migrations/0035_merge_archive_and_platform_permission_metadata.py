from django.db import migrations


def reconcile_metadata(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults

    for definition in PERMISSION_DEFINITIONS:
        Permission.objects.update_or_create(
            code=definition["code"],
            defaults=permission_defaults(definition),
        )


class Migration(migrations.Migration):
    """Join the archive-permission and platform-permission metadata branches."""

    dependencies = [
        ("permissions", "0029_seed_development_product_archive_permissions"),
        ("permissions", "0034_reconcile_platform_product_detail_permission_metadata"),
    ]

    # Both parent branches seed overlapping rows.  Re-apply the canonical
    # catalog after the graph is joined so migration order cannot leave stale
    # names, actions, or descriptions behind.
    operations = [migrations.RunPython(reconcile_metadata, migrations.RunPython.noop)]
