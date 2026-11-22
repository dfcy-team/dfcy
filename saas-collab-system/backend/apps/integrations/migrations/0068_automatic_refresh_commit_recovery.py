from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0067_merge_order_events_gmv")]
    operations = [
        migrations.AddField(
            model_name="automaticrefreshattempt",
            name="commit_recovery",
            field=models.JSONField(default=dict, null=True, blank=True),
        ),
    ]
