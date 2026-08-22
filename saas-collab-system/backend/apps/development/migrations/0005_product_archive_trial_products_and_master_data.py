import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("development", "0004_development_product_archives"),
        ("masterdata", "0001_initial"),
        ("products", "0013_productsku_product_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="developmentproductarchive",
            name="platform_master",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="development_product_archives",
                to="masterdata.platformmaster",
            ),
        ),
        migrations.AddField(
            model_name="developmentproductarchive",
            name="store_master",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="development_product_archives",
                to="masterdata.storemaster",
            ),
        ),
        migrations.AddField(
            model_name="developmentproductarchive",
            name="trial_product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="development_trial_archives",
                to="products.productspu",
            ),
        ),
        migrations.AddField(
            model_name="developmentproductarchive",
            name="trial_sku",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="development_trial_archives",
                to="products.productsku",
            ),
        ),
        migrations.AddIndex(
            model_name="developmentproductarchive",
            index=models.Index(fields=["tenant", "platform_master"], name="idx_dev_archive_platform_ref"),
        ),
        migrations.AddIndex(
            model_name="developmentproductarchive",
            index=models.Index(fields=["tenant", "store_master"], name="idx_dev_archive_store_ref"),
        ),
    ]
