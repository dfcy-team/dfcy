from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("permissions", "0042_role_metadata_and_display_names"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datascope",
            name="scope_type",
            field=models.CharField(
                choices=[
                    ("all", "All"),
                    ("department", "Department"),
                    ("department_tree", "Department and descendants"),
                    ("own", "Own"),
                    ("custom", "Custom"),
                ],
                max_length=20,
            ),
        ),
    ]
