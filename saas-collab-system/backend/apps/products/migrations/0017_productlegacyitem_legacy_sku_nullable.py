from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0016_merge_product_schema_branches")]

    operations = [
        migrations.AlterField(
            model_name="productlegacyitem",
            name="legacy_sku_code",
            field=models.CharField(blank=True, max_length=160, null=True),
        ),
    ]
