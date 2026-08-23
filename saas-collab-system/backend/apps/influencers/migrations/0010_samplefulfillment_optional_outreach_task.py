from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("influencers", "0009_samplefulfillment_lifecycle_fields")]

    operations = [
        migrations.AlterField(
            model_name="samplefulfillment",
            name="outreach_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sample_fulfillments",
                to="influencers.outreachtask",
            ),
        ),
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
                ],
                default="DRJL",
                max_length=20,
            ),
        ),
    ]
