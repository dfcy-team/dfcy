from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0072_finance_handoff")]

    operations = [
        migrations.AddField(
            model_name="automaticrefreshattempt",
            name="commit_recovery",
            field=models.JSONField(default=dict, null=True, blank=True),
        ),
    ]
