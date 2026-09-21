from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0029_automaticrefreshattempt")]

    operations = [
        migrations.AddField(
            model_name="syncrun",
            name="enqueued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="syncrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("success", "Success"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                default="running",
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name="syncrun",
            options={"ordering": ["-enqueued_at", "-started_at", "-id"]},
        ),
    ]
