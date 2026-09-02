from django.db import migrations, models


class Migration(migrations.Migration):
    """Align package-volume precision with the current product models.

    This is a metadata-only precision widening (3 to 6 decimal places) for
    existing nullable decimal columns; it does not rename or drop data.
    """

    dependencies = [("products", "0013_productsku_product_name")]

    operations = [
        migrations.AlterField(
            model_name="productlegacyitem",
            name="package_volume",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=12,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="productsku",
            name="package_volume",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=12,
                null=True,
            ),
        ),
    ]
