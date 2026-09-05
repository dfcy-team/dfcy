from django.db import migrations


PERMISSION_DEFINITIONS = (
    (
        "integrations.warehouse.view",
        "查看仓库 API 授权",
        "integrations",
        "warehouse.view",
        "查看当前租户仓库与库存 API 接入配置的脱敏授权关系；不读取或导出凭据。",
    ),
    (
        "integrations.warehouse.authorize",
        "绑定仓库 API 配置",
        "integrations",
        "warehouse.authorize",
        "将当前租户已托管且通过校验的库存 API 配置绑定到仓库；不接收或回显原始凭据。",
    ),
    (
        "integrations.warehouse.revoke",
        "解除仓库 API 绑定",
        "integrations",
        "warehouse.revoke",
        "撤销当前租户仓库的库存 API 授权绑定并记录审计；不删除接入配置或凭据。",
    ),
)

# Store subject pages expose authorization metadata and use the same
# administrator role.  Keep these registrations here so a tenant upgraded
# from the warehouse closure receives a complete API-access role in one
# idempotent migration, even when an older installation has stale metadata.
STORE_PERMISSION_DEFINITIONS = (
    (
        "integrations.store.view",
        "View marketplace store authorizations",
        "integrations",
        "store.view",
        "View tenant-scoped store authorization metadata.",
    ),
    (
        "integrations.store.authorize",
        "Authorize marketplace stores",
        "integrations",
        "store.authorize",
        "Create a controlled marketplace store authorization.",
    ),
    (
        "integrations.store.revoke",
        "Revoke marketplace store authorizations",
        "integrations",
        "store.revoke",
        "Revoke a store authorization with an audit record.",
    ),
)
STORE_PERMISSION_CODES = tuple(item[0] for item in STORE_PERMISSION_DEFINITIONS)


def register_warehouse_api_permissions(apps, schema_editor):
    DataScope = apps.get_model("permissions", "DataScope")
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, module, action, description in (*PERMISSION_DEFINITIONS, *STORE_PERMISSION_DEFINITIONS):
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "action": action,
                "description": description,
            },
        )
        permissions.append(permission)
    # Migration 0032 seeded the readonly permission after migration 0027 had
    # synchronized administrator roles.  Pick the existing dependencies up
    # here when present, but never create a permission outside the catalog.
    dependency_permissions = Permission.objects.filter(
        code__in={
            "integrations.view",
            "integrations.manage",
            "integrations.run_live_readonly",
            "integrations.credential.rotate",
        }
    )
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions, *dependency_permissions)
        DataScope.objects.update_or_create(
            tenant=role.tenant,
            role=role,
            scope_type="all",
            defaults={"config": {}},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0039_register_warehouse_connector_role_permissions")]

    operations = [
        migrations.RunPython(register_warehouse_api_permissions, migrations.RunPython.noop),
    ]
