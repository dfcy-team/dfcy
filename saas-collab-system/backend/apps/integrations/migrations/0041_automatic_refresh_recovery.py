from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0040_history_sync_batches")]

    operations = [
        migrations.AddField("automaticrefreshattempt", "attempt_count", models.PositiveSmallIntegerField(default=1)),
        migrations.AddField("automaticrefreshattempt", "failure_category", models.CharField(blank=True, default="", max_length=40)),
        migrations.AddField("automaticrefreshattempt", "next_retry_at", models.DateTimeField(blank=True, null=True)),
    ]
