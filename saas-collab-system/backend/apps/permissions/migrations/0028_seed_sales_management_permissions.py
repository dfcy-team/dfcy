from django.db import migrations


PERMISSIONS = (
    ("sales_management.view", "View sales overview", "view", "View tenant and data-scope filtered sales metrics and anomalies."),
    ("sales_management.orders.view", "View sales orders", "orders.view", "View masked tenant and data-scope filtered sales orders."),
    ("sales_management.returns.view", "View sales returns", "returns.view", "View tenant and data-scope filtered refunds and returns."),
    ("sales_management.stores.view", "View store sales", "stores.view", "View tenant and data-scope filtered store sales facts."),
    ("sales_management.skus.view", "View SKU sales", "skus.view", "View tenant and data-scope filtered SKU sales facts."),
    ("sales_management.export", "Export sales details", "export", "Request audited masked sales exports within the active scope."),
    ("sales_management.data_quality.view", "View sales data quality", "data_quality.view", "View tenant and data-scope filtered sales data quality issues."),
    ("sales_management.sync.view", "View sales sync state", "sync.view", "View safe sync references and request audited idempotent reruns."),
)


def seed_sales_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, action, description in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": "sales_management", "action": action, "description": description},
        )
        permissions.append(permission)
    for role in Role.objects.filter(code="administrator"):
        role.permissions.add(*permissions)


def unseed_sales_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Permission.objects.filter(code__in=[item[0] for item in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("permissions", "0027_sync_tenant_administrator_permissions")]

    operations = [migrations.RunPython(seed_sales_permissions, unseed_sales_permissions)]
