from django.db import migrations


DEFINITIONS = (
    ("integrations.internal_api_client.view", "查看内部 API 调用方", "view", "查看当前租户的内部只读 API 调用方脱敏配置。"),
    ("integrations.internal_api_client.manage", "管理内部 API 调用方", "manage", "创建、更新和启停当前租户的调用方。"),
    ("integrations.internal_api_client.rotate", "轮换内部 API 密钥", "rotate", "轮换调用方密钥，明文仅在当次返回。"),
    ("integrations.internal_api_client.audit.view", "查看内部 API 审计", "audit.view", "查看当前租户的不可变配置审计记录。"),
)


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")
    records = []
    for code, name, action, description in DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": "integrations", "action": f"internal_api_client.{action}", "description": description},
        )
        records.append(permission)
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*records)
        DataScope.objects.update_or_create(tenant=role.tenant, role=role, scope_type="all", defaults={"config": {}})


class Migration(migrations.Migration):
    dependencies = [("permissions", "0045_register_feishu_permissions")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
