from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0035_seed_bd_exchange_rates")]

    operations = [
        migrations.AddField(
            model_name="affiliateordersnapshot",
            name="actual_paid_shop_ads_commission",
            field=models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True),
        ),
    ]
