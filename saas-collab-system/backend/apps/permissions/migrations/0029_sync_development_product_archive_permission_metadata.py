from django.db import migrations


PERMISSION_CODES = (
    "development.product_archive.view",
    "development.product_archive.manage",
    "development.product_archive.confirm",
)


def sync_product_archive_permission_metadata(apps, schema_editor):
    """Align archive permission rows with the canonical application catalog.

    Migration 0028 seeded these rows before the catalog descriptions were
    finalized.  Keep this repair idempotent and scoped to the three archive
    codes; no role assignments are changed here.
    """
    Permission = apps.get_model("permissions", "Permission")
    from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults

    definitions = {
        definition["code"]: definition
        for definition in PERMISSION_DEFINITIONS
        if definition["code"] in PERMISSION_CODES
    }
    fields = ("name", "module", "action", "description")
    for code in PERMISSION_CODES:
        definition = definitions.get(code)
        if definition is None:
            continue
        defaults = permission_defaults(definition)
        metadata = {field: defaults[field] for field in fields}
        permission, _ = Permission.objects.get_or_create(code=code, defaults=metadata)
        changed_fields = [
            field for field, value in metadata.items() if getattr(permission, field) != value
        ]
        if changed_fields:
            for field in changed_fields:
                setattr(permission, field, metadata[field])
            permission.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0028_seed_development_product_archive_permissions")]

    operations = [
        migrations.RunPython(sync_product_archive_permission_metadata, migrations.RunPython.noop),
    ]
