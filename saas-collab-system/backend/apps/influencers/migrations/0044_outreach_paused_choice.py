from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0043_video_native_click_ratio")]
    operations = [
        migrations.AlterField(
            model_name="outreachtask",
            name="status",
            field=models.CharField(
                max_length=20, default="pending",
                choices=[("pending", "Pending"), ("in_progress", "In progress"),
                         ("paused", "Paused"), ("completed", "Completed"),
                         ("cancelled", "Cancelled")],
            ),
        ),
    ]
