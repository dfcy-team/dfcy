from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0042_shopee_advertising_records")]
    operations = [migrations.AlterField(
        model_name="shopeeadvertisingrecord", name="kind",
        field=models.CharField(max_length=24, choices=[
            ("shop_daily", "Shop daily"), ("campaign_daily", "Campaign daily"),
            ("campaign", "Campaign settings"), ("balance", "Balance snapshot"),
            ("campaign_hourly", "Campaign hourly"), ("gms_campaign", "GMS campaign period"),
            ("gms_item", "GMS item period"), ("shop_toggle", "Shop toggle snapshot"),
            ("recommended_item", "Recommended item snapshot"),
        ]),
    )]
