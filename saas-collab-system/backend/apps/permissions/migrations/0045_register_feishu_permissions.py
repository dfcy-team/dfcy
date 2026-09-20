from django.db import migrations


DEFINITIONS = (
    ("feishu.view", "查看飞书协同", "feishu", "view", "查看当前租户的飞书协同配置与运行记录。"),
    ("feishu.connection.manage", "管理飞书连接", "feishu", "connection.manage", "维护飞书应用连接及托管凭据引用。"),
    ("feishu.identity.manage", "管理飞书身份", "feishu", "identity.manage", "维护系统用户与飞书身份映射。"),
    ("feishu.notification.manage", "管理飞书通知", "feishu", "notification.manage", "维护飞书通知规则。"),
    ("feishu.report.manage", "管理飞书报表", "feishu", "report.manage", "维护飞书报表推送规则。"),
    ("feishu.approval.manage", "管理飞书审批", "feishu", "approval.manage", "维护本地审批与飞书审批映射。"),
    ("feishu.operations.view", "查看飞书运行记录", "feishu", "operations.view", "查看飞书脱敏运行与事件记录。"),
    ("feishu.operations.retry", "重试飞书失败任务", "feishu", "operations.retry", "授权重试可补偿的飞书失败任务。"),
)


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")
    records = []
    for code, name, module, action, description in DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )
        records.append(permission)
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*records)
        DataScope.objects.update_or_create(
            tenant=role.tenant, role=role, scope_type="all", defaults={"config": {}},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0044_tenant_business_scope_boundary")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
