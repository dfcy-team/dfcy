from django.db import migrations


DEFINITIONS = (
    ("feishu.view", "查看飞书协同", "view", "查看当前租户的飞书协同配置与运行记录。"),
    ("feishu.connection.manage", "管理飞书连接", "connection.manage", "维护飞书应用连接及托管凭据引用。"),
    ("feishu.identity.manage", "管理飞书身份", "identity.manage", "维护系统用户与飞书身份映射。"),
    ("feishu.notification.manage", "管理飞书通知", "notification.manage", "维护飞书通知规则。"),
    ("feishu.report.manage", "管理飞书报表", "report.manage", "维护飞书报表推送规则。"),
    ("feishu.approval.manage", "管理飞书审批", "approval.manage", "维护本地审批与飞书审批映射。"),
    ("feishu.operations.view", "查看飞书运行记录", "operations.view", "查看飞书脱敏运行与事件记录。"),
    ("feishu.operations.retry", "重试飞书失败任务", "operations.retry", "授权重试可补偿的飞书失败任务。"),
)


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    records = []
    for code, name, action, description in DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "feishu",
                "action": action,
                "description": description,
                "permission_type": "action",
                "metadata": {},
            },
        )
        records.append(permission)
    # Follow the current runtime catalog contract: tenant administrators gain
    # every registered action, while their existing data-scope rows remain
    # authoritative.  The generated menu registry and sync_permissions add
    # the corresponding menu grant without broadening a CUSTOM scope.
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*records)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0044_tenant_business_scope_boundary")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
