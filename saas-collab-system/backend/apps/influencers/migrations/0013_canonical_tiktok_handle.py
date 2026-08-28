from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0012_sample_fulfillment_status_baseline")]

    operations = [
        migrations.AlterField(
            model_name="influencer",
            name="handle",
            field=models.CharField(
                blank=True,
                db_comment="TikTok用户名",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="bdsampleattributionsnapshot",
            name="creator_username",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
