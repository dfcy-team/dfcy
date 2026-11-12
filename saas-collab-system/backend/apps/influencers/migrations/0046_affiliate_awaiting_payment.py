from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0045_influencer_shopee_platform")]
    operations = [
        migrations.AlterField(
            model_name="affiliateordersnapshot",
            name="settlement_status",
            field=models.CharField(
                max_length=32, null=True, blank=True,
                choices=[
                    ("\u5df2\u7ed3\u7b97", "\u5df2\u7ed3\u7b97"),
                    ("\u4e0d\u7b26\u5408\u6761\u4ef6", "\u4e0d\u7b26\u5408\u6761\u4ef6"),
                    ("\u5f85\u7ed3\u7b97", "\u5f85\u7ed3\u7b97"),
                    ("\u5f85\u4ed8\u6b3e", "\u5f85\u4ed8\u6b3e"),
                ],
            ),
        ),
    ]
