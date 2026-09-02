from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0011_product_detail_fields")]

    operations = [
        migrations.AlterField(model_name="productsku", name="package_volume", field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
        migrations.AlterField(model_name="productlegacyitem", name="package_volume", field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
    ]
