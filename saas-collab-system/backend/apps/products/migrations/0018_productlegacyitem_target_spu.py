from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("products", "0017_productlegacyitem_legacy_sku_nullable")]

    operations = [
        migrations.AddField(
            model_name="productlegacyitem",
            name="target_spu",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pending_import_skus",
                to="products.productspu",
            ),
        ),
    ]
