from django.db import migrations


def update_description(apps, schema_editor):
    # Update the existing capability without assigning roles or expanding scope.
    apps.get_model("permissions", "Permission").objects.filter(code="integrations.history.manage").update(
        description="创建、暂停、继续、调整范围和重试历史补采；须同时具备真实只读同步权限，且全部店铺均在授权数据范围内。",
    )


def restore_description(apps, schema_editor):
    apps.get_model("permissions", "Permission").objects.filter(code="integrations.history.manage").update(
        description="创建、暂停、继续和重试历史补采；须同时具备真实只读同步权限。",
    )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0050_register_history_sync_permissions")]
    operations = [migrations.RunPython(update_description, restore_description)]
