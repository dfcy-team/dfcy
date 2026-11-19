from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("supply_chain", "0078_freight_channel_load_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="replenishmentstrategy",
            name="sku_policies",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
