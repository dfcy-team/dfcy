from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("rpa", "0005_mysql_compatible_account_lock")]

    operations = [
        migrations.AlterField(
            model_name="rpaagent",
            name="execution_mode",
            field=models.CharField(
                choices=[
                    ("mock", "Mock"),
                    ("dry_run", "Dry run"),
                    ("production", "Production"),
                    ("production_disabled", "Production disabled"),
                ],
                default="dry_run",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="execution_mode",
            field=models.CharField(
                choices=[("mock", "Mock"), ("dry_run", "Dry run"), ("production", "Production")],
                default="dry_run",
                max_length=20,
            ),
        ),
    ]
