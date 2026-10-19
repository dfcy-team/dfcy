from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0037_bd_exchange_rates_direct_save")]
    operations = [
        migrations.AlterField(
            model_name="tiktokshopvideo",
            name="video_type",
            field=models.CharField(
                choices=[("self_operated", "Self operated"), ("creator", "Creator"), ("unknown", "Unknown")],
                default="creator", max_length=30,
            ),
        ),
    ]
