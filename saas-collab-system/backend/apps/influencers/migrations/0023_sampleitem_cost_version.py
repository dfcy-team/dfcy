from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0023_productcostversion"),
        ("influencers", "0022_affiliate_order_updated_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="sampleitem",
            name="cost_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sample_items",
                to="products.productcostversion",
            ),
        ),
    ]
