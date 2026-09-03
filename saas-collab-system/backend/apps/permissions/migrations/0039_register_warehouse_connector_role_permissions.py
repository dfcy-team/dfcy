"""Register the WMS/API connector permission contract after the split.

V2.44.61 production installations already have
``0037_seed_pilot_execution_permissions``.  The permission-surface split is
therefore ``0038`` and this repair/seed must remain ``0039`` so the migration
graph is linear and an existing installation never tries to apply a second
``0037`` with a different meaning.
"""

from django.db import migrations


PERMISSION_DEFINITIONS = (
    {
        "code": "masterdata.view",
        "name": "查看基础档案与连接器识别",
        "module": "masterdata",
        "action": "view",
        "description": "查看当前租户的平台、站点、店铺、仓库和供应商基础档案，以及仓储业务分类、服务商名称和连接器识别结果；不包含实际连接器配置或凭据内容。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "masterdata.manage",
        "name": "维护基础档案与服务商标识",
        "module": "masterdata",
        "action": "manage",
        "description": "创建、更新、启停当前租户的平台、站点、店铺、仓库和供应商基础档案，并维护仓储业务分类与服务商识别信息；不授予实际连接器配置或凭据轮换操作，分别需要 integrations.config.* 和 integrations.credential.rotate。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.config.view",
        "name": "查看 API/WMS 连接配置",
        "module": "integrations",
        "action": "config.view",
        "description": "查看当前租户的实际连接器配置元数据和脱敏状态；不读取或导出凭据，也不代表拥有创建、更新、验证或停用权限。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.config.create",
        "name": "创建 API/WMS 连接配置",
        "module": "integrations",
        "action": "config.create",
        "description": "为当前租户创建实际连接器配置草稿并登记服务商连接信息；不授予更新、验证、停用或凭据轮换权限。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.config.update",
        "name": "更新 API/WMS 连接配置",
        "module": "integrations",
        "action": "config.update",
        "description": "更新当前租户已授权的实际连接器非敏感配置；不改变仓储业务分类，不读取凭据，也不授予验证、停用或凭据轮换权限。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.config.verify",
        "name": "验证 API/WMS 连接配置",
        "module": "integrations",
        "action": "config.verify",
        "description": "对当前租户的实际连接器配置执行受控连接验证并记录结果；不授予修改配置、停用连接或轮换凭据权限。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.config.disable",
        "name": "停用 API/WMS 连接配置",
        "module": "integrations",
        "action": "config.disable",
        "description": "停用当前租户的实际连接器配置并阻止后续接入任务使用；不删除平台档案、不清理凭据，也不授予凭据轮换权限。",
        "permission_type": "action",
        "metadata": {},
    },
    {
        "code": "integrations.credential.rotate",
        "name": "轮换 API/WMS 凭据",
        "module": "integrations",
        "action": "credential.rotate",
        "description": "只轮换 API/WMS 连接器的受控凭据引用或密钥版本，不读取、导出原始凭据；不授予连接配置创建、更新、验证或停用权限。",
        "permission_type": "action",
        "metadata": {},
    },
)
PERMISSION_CODES = tuple(definition["code"] for definition in PERMISSION_DEFINITIONS)


def register_warehouse_connector_permissions(apps, schema_editor):
    """Repair connector metadata and grant it only to active administrators."""

    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for definition in PERMISSION_DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=definition["code"],
            defaults={key: value for key, value in definition.items() if key != "code"},
        )
        permissions.append(permission)

    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0038_split_permission_surfaces")]

    operations = [
        migrations.RunPython(register_warehouse_connector_permissions, migrations.RunPython.noop),
    ]
