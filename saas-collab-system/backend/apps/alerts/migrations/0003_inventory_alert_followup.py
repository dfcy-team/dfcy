from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("alerts", "0002_businessalertrule_businessalert_and_more")]

    operations = [
        migrations.AddField(
            model_name="inventoryalert",
            name="action_plan",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="inventoryalert",
            name="due_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="inventoryalert",
            name="resolution",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="inventoryalert",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="inventoryalertevent",
            name="event_type",
            field=models.CharField(
                choices=[("triggered", "Triggered"), ("deduplicated", "Deduplicated"),
                         ("assigned", "Assigned"), ("follow_up_updated", "Follow-up updated"),
                         ("silenced", "Silenced"), ("closed", "Closed")],
                max_length=30,
            ),
        ),
    ]
