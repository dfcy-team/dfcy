import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("development", "0005_product_archive_trial_products_and_master_data"),
        ("products", "0013_productsku_product_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="developmentproductarchive",
            name="development_spu_code",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="developmentproductarchive",
            name="season_code",
            field=models.CharField(blank=True, default="0", max_length=1),
        ),
        migrations.AddField(
            model_name="developmentproductarchive",
            name="formal_sku",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="formalized_development_archives",
                to="products.productsku",
            ),
        ),
        migrations.AddConstraint(
            model_name="developmentproductarchive",
            constraint=models.UniqueConstraint(
                condition=~models.Q(development_spu_code=""),
                fields=("tenant", "development_spu_code"),
                name="uniq_dev_archive_dev_spu_code",
            ),
        ),
    ]
