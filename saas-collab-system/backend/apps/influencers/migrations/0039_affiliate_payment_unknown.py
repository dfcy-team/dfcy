from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0038_tiktok_video_unknown_type")]

    operations = [
        migrations.AlterField(
            model_name="affiliateordersnapshot", name="payment_amount",
            field=models.DecimalField(max_digits=20, decimal_places=4, default=0, null=True, blank=True),
        ),
    ]
