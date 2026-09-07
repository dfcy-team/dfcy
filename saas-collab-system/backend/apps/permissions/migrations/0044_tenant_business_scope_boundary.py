from django.db import migrations, models


class Migration(migrations.Migration):
    """Label the new scope contract without rewriting historical records.

    Existing ``department``, ``department_tree`` and ``own`` rows remain
    untouched and therefore continue to be readable by the compatibility
    filters.  The write API rejects those values after this migration; an
    administrator must explicitly choose ``all`` or ``custom`` before a role
    can be saved again.
    """

    dependencies = [
        ("permissions", "0043_datascope_department_tree"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datascope",
            name="scope_type",
            field=models.CharField(
                choices=[
                    ("all", "租户内全部数据"),
                    ("department", "历史组织范围（本部门）"),
                    ("department_tree", "历史组织范围（部门及下级）"),
                    ("own", "历史组织范围（本人）"),
                    ("custom", "按业务范围限制"),
                ],
                help_text="新配置只能使用租户内全部数据或按业务范围限制；历史组织范围仅兼容读取。",
                max_length=20,
            ),
        ),
    ]
