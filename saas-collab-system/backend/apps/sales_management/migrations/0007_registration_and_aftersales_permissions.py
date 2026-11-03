from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    registered = []
    definitions = (
        ("sales_management.exchange", "换货登记", "sales_pre_shipment_adjustments", "/sales/pre-shipment-adjustments", "销售管理"),
        ("sales_management.promotion", "订单推广登记", "sales_special_order_registrations", "/sales/special-order-registrations", "销售管理"),
        ("finance.gcash", "GCash退款登记", "finance_gcash_refunds", "/finance/gcash-refunds", "财务中心"),
    )
    for prefix, title, resource, path, parent in definitions:
        module, short = prefix.split(".")
        actions = [("view", "查看"), ("create", "新建"), ("edit", "修改"), ("import", "导入"), ("export", "导出")]
        actions += [("sensitive", "查看敏感信息")] if short == "gcash" else [("submit", "提交审批"), ("approve", "审批")]
        for action, label in actions:
            permission, _ = Permission.objects.using(schema_editor.connection.alias).update_or_create(
                code=f"{prefix}.{action}",
                defaults={
                    "name": f"{label}{title}",
                    "module": module,
                    "action": f"{short}.{action}",
                    "permission_type": "action",
                    "description": "仅限当前租户和店铺范围的内部登记，不触发平台、仓库或付款操作。",
                    "metadata": {},
                },
            )
            registered.append(permission)
        menu, _ = Permission.objects.using(schema_editor.connection.alias).update_or_create(
            code=f"menu.{module}.{resource}.view",
            defaults={
                "name": title,
                "module": module,
                "action": f"{resource}.view",
                "description": f"显示{title}入口",
                "permission_type": "menu",
                "metadata": {
                    "path": path,
                    "route": path,
                    "resource": resource,
                    "parent": parent,
                    "action_codes": [f"{prefix}.view"],
                    "source": "frontend/src/router/menu.js",
                    "status": "active",
                },
            },
        )
        registered.append(menu)

    for role in Role.objects.using(schema_editor.connection.alias).filter(code="administrator", status="active"):
        role.permissions.add(*registered)

    Permission.objects.using(schema_editor.connection.alias).update_or_create(
        code="sales_management.aftersales.manage",
        defaults={
            "name": "管理订单售后回仓",
            "module": "sales_management",
            "action": "aftersales.manage",
            "description": "配置本地回仓同步、导入仓库实收记录及人工匹配；不执行平台退款、仓库写单或库存调整。",
            "permission_type": "action",
            "metadata": {},
        },
    )
    Permission.objects.using(schema_editor.connection.alias).filter(
        code="sales_management.returns.view"
    ).update(name="查看订单售后")
    Permission.objects.using(schema_editor.connection.alias).filter(
        code="menu.sales_management.sales_management_returns.view"
    ).update(name="订单售后")


class Migration(migrations.Migration):
    dependencies = [
        ("sales_management", "0006_registration_and_aftersales"),
        ("permissions", "0052_history_task_recovery_description"),
    ]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
