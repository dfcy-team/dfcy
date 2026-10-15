from django.db import migrations


def update_description(apps, schema_editor):
    # Existing permissions only: do not add role grants or widen data scopes.
    apps.get_model("permissions", "Permission").objects.filter(code="integrations.history.manage").update(
        description="管理订单、退货退款、财务与广告补采：创建、暂停、继续、执行时段、失败诊断与重试、状态核对；须同时具备真实只读同步权限。单任务操作限定当前店铺；整批调整要求全部店铺均在授权数据范围内。",
    )


def restore_description(apps, schema_editor):
    apps.get_model("permissions", "Permission").objects.filter(code="integrations.history.manage").update(
        description="创建、暂停、继续、调整范围和重试历史补采；须同时具备真实只读同步权限，且全部店铺均在授权数据范围内。",
    )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0051_history_range_permission_description")]
    operations = [migrations.RunPython(update_description, restore_description)]
