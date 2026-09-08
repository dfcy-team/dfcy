from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0014_nullable_affiliate_commissions")]

    operations = [
        migrations.AlterField(
            model_name="samplefulfillment",
            name="link_type",
            field=models.CharField(
                choices=[
                    ("DRJL", "BD建联"),
                    ("YYJL", "运营建联"),
                    ("PKDJ", "品库达人"),
                    ("ZBDR", "直播达人"),
                    ("TKOne", "TikTokOne建联"),
                    ("direct", "直接送样"),
                ],
                default="DRJL",
                max_length=20,
            ),
        ),
    ]
