from django.db import migrations, models


BUILTIN_ROLE_METADATA = {
    "administrator": {
        "name": "租户管理员",
        "description": "租户内置管理员，拥有当前租户全部已登记权限并负责角色委派。",
    },
    "operations": {
        "name": "业务运营人员",
        "description": "负责已授权业务模块的日常运营协同。",
    },
    "product_developer": {
        "name": "产品开发人员",
        "description": "负责产品开发、商品档案及相关生命周期工作。",
    },
    "002": {
        "name": "达人运营管理员",
        "description": "负责达人档案、建联和送样履约等达人运营工作。",
    },
}


def normalize_builtin_roles(apps, schema_editor):
    Role = apps.get_model("permissions", "Role")
    for code, values in BUILTIN_ROLE_METADATA.items():
        Role.objects.filter(code=code).update(
            name=values["name"],
            description=values["description"],
            role_type="builtin",
            is_protected=True,
        )


def restore_builtin_role_names(apps, schema_editor):
    Role = apps.get_model("permissions", "Role")
    legacy_names = {
        "administrator": "管理员",
        "operations": "Operations",
        "product_developer": "Product Developer",
        "002": "Influencer manager",
    }
    for code, name in legacy_names.items():
        Role.objects.filter(code=code).update(name=name, description="", role_type="custom", is_protected=False)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0041_register_mapping_permissions")]

    operations = [
        migrations.AddField(
            model_name="role",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="role",
            name="is_protected",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="role",
            name="role_type",
            field=models.CharField(
                choices=[
                    ("builtin", "内置角色"),
                    ("template", "角色模板"),
                    ("custom", "自定义角色"),
                ],
                default="custom",
                max_length=20,
            ),
        ),
        migrations.RunPython(normalize_builtin_roles, restore_builtin_role_names),
    ]
