from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0009_productspu_brand")]

    operations = [
        migrations.AddField(
            model_name="productsku",
            name="purchase_price",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="productlegacyitem",
            name="purchase_price",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True),
        ),
    ]
