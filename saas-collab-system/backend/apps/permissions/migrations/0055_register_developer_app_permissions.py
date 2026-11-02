from django.db import migrations

DEFINITIONS = (
    ("integrations.developer_app.view", "查看开发者应用", "developer_app.view", "查看本人开发者应用与接口目录。"),
    ("integrations.developer_app.manage", "管理开发者应用", "developer_app.manage", "提交和维护本人开发者应用。"),
)

def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in DEFINITIONS:
        Permission.objects.update_or_create(code=code, defaults={"name":name,"module":"integrations","action":action,"description":description})

class Migration(migrations.Migration):
    dependencies = [("permissions", "0054_role_permissions_customized")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
