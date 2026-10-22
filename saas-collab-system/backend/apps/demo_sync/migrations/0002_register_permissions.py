from django.db import migrations


def register(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    for action, label in (("view", "查看开发环境数据同步"), ("manage", "管理开发同步环境"),
                          ("run", "执行开发数据快照"), ("download", "下载开发数据快照")):
        permission.objects.update_or_create(code=f"system.demo_sync.{action}", defaults={
            "name": label, "module": "system", "action": f"demo_sync.{action}",
            "description": "开发数据快照专用授权；限当前租户和获准开发环境。",
        })


class Migration(migrations.Migration):
    dependencies = [("demo_sync", "0001_initial"), ("permissions", "0052_history_task_recovery_description")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
