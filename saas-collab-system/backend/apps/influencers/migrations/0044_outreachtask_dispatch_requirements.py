from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0043_video_native_click_ratio")]
    operations = [
        migrations.AddField(
            model_name="outreachtask",
            name="dispatch_requirements",
            field=models.CharField(blank=True, default="", db_default="", max_length=1000),
        ),
    ]
