from django.db import migrations, models


MENU_PERMISSION_DEFINITIONS = (
    (
        "menu.system.tenants.view",
        "查看租户管理",
        "tenants.view",
        "查看平台租户目录并进入目标租户的权限配置。",
        {"path": "/system/tenants", "resource": "tenants"},
    ),
    (
        "menu.system.organization.view",
        "查看组织架构菜单",
        "organization.view",
        "显示系统管理中的组织架构入口。",
        {"path": "/system/departments", "resource": "departments"},
    ),
    (
        "menu.system.users.view",
        "查看用户目录菜单",
        "users.view",
        "显示系统管理中的用户目录入口。",
        {"path": "/system/users", "resource": "users"},
    ),
    (
        "menu.system.roles.view",
        "查看角色权限菜单",
        "roles.view",
        "显示系统管理中的角色权限入口。",
        {"path": "/system/roles", "resource": "roles"},
    ),
    (
        "menu.system.security_operations.view",
        "查看安全运维菜单",
        "security_operations.view",
        "显示系统管理中的安全运维入口。",
        {"path": "/system/security-operations", "resource": "security_operations"},
    ),
)

FIELD_PERMISSION_DEFINITIONS = (
    (
        "field.system.users.full_name.view",
        "查看用户姓名字段",
        "users.full_name.view",
        "显示用户目录中的姓名字段；不影响敏感字段脱敏。",
        {"resource": "users", "field": "full_name", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.users.department.view",
        "查看用户部门字段",
        "users.department.view",
        "显示用户目录中的部门字段。",
        {"resource": "users", "field": "department_name", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.users.roles.view",
        "查看用户角色字段",
        "users.roles.view",
        "显示用户目录中的角色绑定字段。",
        {"resource": "users", "field": "roles", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.users.status.view",
        "查看用户状态字段",
        "users.status.view",
        "显示用户目录中的启用状态字段。",
        {"resource": "users", "field": "is_active", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.tenants.name.view",
        "查看租户名称字段",
        "tenants.name.view",
        "显示租户管理中的租户名称。",
        {"resource": "tenants", "field": "name", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.tenants.code.view",
        "查看租户编码字段",
        "tenants.code.view",
        "显示租户管理中的租户编码。",
        {"resource": "tenants", "field": "code", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.tenants.status.view",
        "查看租户状态字段",
        "tenants.status.view",
        "显示租户管理中的状态。",
        {"resource": "tenants", "field": "status", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.roles.name.view",
        "查看角色名称字段",
        "roles.name.view",
        "显示角色管理中的角色名称。",
        {"resource": "roles", "field": "name", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.roles.code.view",
        "查看角色编码字段",
        "roles.code.view",
        "显示角色管理中的角色编码。",
        {"resource": "roles", "field": "code", "operation": "view", "sensitive": False},
    ),
    (
        "field.system.roles.status.view",
        "查看角色状态字段",
        "roles.status.view",
        "显示角色管理中的角色状态。",
        {"resource": "roles", "field": "status", "operation": "view", "sensitive": False},
    ),
)

# Existing system-view action grants already represented the ability to enter
# these pages before the split.  Backfill only the corresponding trusted
# surface grants so an upgraded role keeps its visible menu and non-sensitive
# system columns; unrelated resources remain on the legacy compatibility path.
LEGACY_MENU_ACTION_MAP = {
    "system.organization.view": "menu.system.organization.view",
    "system.users.view": "menu.system.users.view",
    "system.roles.view": "menu.system.roles.view",
    "security.operations.view": "menu.system.security_operations.view",
}
LEGACY_FIELD_ACTION_MAP = {
    "system.users.view": (
        "field.system.users.full_name.view",
        "field.system.users.department.view",
        "field.system.users.roles.view",
        "field.system.users.status.view",
    ),
    "system.roles.view": (
        "field.system.roles.name.view",
        "field.system.roles.code.view",
        "field.system.roles.status.view",
    ),
}


def seed_split_permission_surfaces(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")

    for code, name, action, description, metadata in MENU_PERMISSION_DEFINITIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "system",
                "action": action,
                "description": description,
                "permission_type": "menu",
                "metadata": metadata,
            },
        )
    for code, name, action, description, metadata in FIELD_PERMISSION_DEFINITIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "system",
                "action": action,
                "description": description,
                "permission_type": "field",
                "metadata": metadata,
            },
        )

    surface_permissions = {
        permission.code: permission
        for permission in Permission.objects.filter(
            code__in=set(LEGACY_MENU_ACTION_MAP.values())
            | {code for codes in LEGACY_FIELD_ACTION_MAP.values() for code in codes}
        )
    }
    for role in Role.objects.all():
        legacy_codes = set(role.permissions.values_list("code", flat=True))
        backfill_codes = {
            menu_code
            for action_code, menu_code in LEGACY_MENU_ACTION_MAP.items()
            if action_code in legacy_codes
        }
        for action_code, field_codes in LEGACY_FIELD_ACTION_MAP.items():
            if action_code in legacy_codes:
                backfill_codes.update(field_codes)
        if backfill_codes:
            role.permissions.add(*(surface_permissions[code] for code in backfill_codes if code in surface_permissions))

    # The built-in role is catalog managed and must receive every new surface
    # just as it receives every legacy action permission.
    all_permissions = Permission.objects.all()
    for role in Role.objects.filter(code="administrator"):
        role.permissions.set(all_permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0037_seed_pilot_execution_permissions")]

    operations = [
        migrations.AddField(
            model_name="permission",
            name="permission_type",
            field=models.CharField(
                choices=[("menu", "Menu"), ("action", "Action"), ("field", "Field")],
                default="action",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="permission",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterModelOptions(
            name="permission",
            options={"ordering": ["permission_type", "module", "action", "code"]},
        ),
        migrations.RunPython(seed_split_permission_surfaces, migrations.RunPython.noop),
    ]
