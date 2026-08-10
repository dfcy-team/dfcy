from django.db import migrations


PERMISSIONS = (
    (
        "supply.purchase_order.view",
        "View supply purchase orders",
        "purchase_order.view",
        "View tenant and data-scope filtered supply purchase order headers, lines, and progress.",
    ),
    (
        "supply.purchase_order.create",
        "Create supply purchase orders",
        "purchase_order.create",
        "Create local MySQL supply purchase order headers and lines for authorized suppliers.",
    ),
    (
        "supply.purchase_order.accept",
        "Accept supply purchase orders",
        "purchase_order.accept",
        "Accept an authorized pending supply purchase order through the audited action service.",
    ),
    (
        "supply.production.start",
        "Start supply production",
        "production.start",
        "Move an authorized accepted supply purchase order into production.",
    ),
    (
        "supply.production.update",
        "Update supply production progress",
        "production.update",
        "Record monotonic production progress for an authorized supply purchase order.",
    ),
    (
        "supply.production.complete",
        "Complete supply production",
        "production.complete",
        "Complete production when the reported quantity equals the purchase order total.",
    ),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "supply",
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0014_seed_ui_p8_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
