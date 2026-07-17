from django.db import migrations


PERMISSIONS = (
    ("products.research.view", "View product research", "products", "research.view", "View tenant and data-scope filtered product research records."),
    ("products.research.manage", "Manage product research", "products", "research.manage", "Create and update authorized product research records."),
    ("products.master.view", "View product master data", "products", "master.view", "View tenant and data-scope filtered SPU and SKU records."),
    ("products.master.manage", "Manage product master data", "products", "master.manage", "Create and update authorized SPU and SKU records."),
    ("products.master.freeze", "Freeze product codes", "products", "master.freeze", "Freeze authorized SPU and SKU codes without changing lifecycle state."),
    ("purchasing.orders.view", "View purchase orders", "purchasing", "orders.view", "View tenant and data-scope filtered purchase orders."),
    ("purchasing.orders.manage", "Manage purchase orders", "purchasing", "orders.manage", "Create and update authorized purchase order drafts; no automatic procurement."),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0011_seed_ui_p4_workflow_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
