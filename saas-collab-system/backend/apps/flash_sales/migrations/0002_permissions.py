from django.db import migrations


def register(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    for action, label in (("view", "查看"), ("configure", "配置"), ("execute", "执行"),
                          ("delete", "删除"), ("plans", "管理计划"), ("notifications", "管理全局通知")):
        permission.objects.get_or_create(code=f"marketing.flash_sales.{action}", defaults={
            "name": f"{label}店内闪购", "module": "marketing", "action": f"flash_sales.{action}",
            "description": "仅当前租户授权店铺；查看不授予平台写入权限。", "permission_type": "action", "metadata": {},
        })
    # No role or account is automatically granted platform-write permissions.


class Migration(migrations.Migration):
    dependencies = [("flash_sales", "0001_initial"), ("permissions", "0056_merge_20261103_0536")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
