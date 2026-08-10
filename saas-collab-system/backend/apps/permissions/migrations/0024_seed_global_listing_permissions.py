from django.db import migrations


PERMISSIONS = (
    ("listings.workbench.view", "查看全球刊登工作台", "listings", "workbench.view"),
    ("listings.workbench.manage", "管理全球刊登工作台", "listings", "workbench.manage"),
    ("listings.mapping.view", "查看平台类目与属性映射", "listings", "mapping.view"),
    ("listings.mapping.manage", "维护平台类目与属性映射", "listings", "mapping.manage"),
    ("listings.task.view", "查看刊登任务与日志", "listings", "task.view"),
    ("listings.task.manage", "管理刊登任务", "listings", "task.manage"),
    ("listings.publish.production", "确认生产刊登", "listings", "publish.production"),
)


def seed_global_listing_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")

    permission_map = {}
    for code, name, module, action in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "action": action,
                "description": "Global listing phase-one tenant-scoped permission.",
            },
        )
        permission_map[code] = permission

    for role in Role.objects.filter(code__in=("administrator", "operations", "product_developer")):
        role.permissions.add(*permission_map.values())
        DataScope.objects.get_or_create(
            tenant=role.tenant,
            role=role,
            scope_type="all" if role.code in {"administrator", "product_developer"} else "own",
            defaults={"config": {}},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0023_create_tenant_administrator_role")]
    operations = [migrations.RunPython(seed_global_listing_permissions, migrations.RunPython.noop)]
