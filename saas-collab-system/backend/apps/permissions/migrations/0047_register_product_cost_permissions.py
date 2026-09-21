from django.db import migrations


DEFINITIONS = (
    ("products.cost.view", "查看商品成本", "cost.view", "查看当前租户 SKU 的历史和时点成本。"),
    ("products.cost.manage", "维护商品成本", "cost.manage", "追加当前租户 SKU 的商品成本版本。"),
    ("products.cost.backfill", "生成商品成本回填预览", "cost.backfill", "预览系统计算的待核对商品成本，不直接写入。"),
    ("products.cost.approve", "确认商品成本", "cost.approve", "确认商品成本版本并使其进入时态计算。"),
)


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")
    records = []
    for code, name, action, description in DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": "products", "action": action, "description": description},
        )
        records.append(permission)
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*records)
        DataScope.objects.update_or_create(
            tenant=role.tenant, role=role, scope_type="all", defaults={"config": {}}
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0046_register_internal_api_client_permissions")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
