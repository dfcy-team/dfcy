from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("configcenter", "0003_product_readonly_endpoint_defaults")]
    operations = [
        migrations.AlterField(
            model_name="configchangelog",
            name="action",
            field=models.CharField(
                choices=[
                    ("create_version", "Create version"),
                    ("approve", "Approve"),
                    ("activate", "Activate"),
                    ("rollback", "Rollback"),
                ],
                max_length=30,
            ),
        ),
    ]
