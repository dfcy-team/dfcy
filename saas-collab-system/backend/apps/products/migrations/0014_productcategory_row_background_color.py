from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0013_productsku_product_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="productcategory",
            name="row_background_color",
            field=models.CharField(blank=True, default="", max_length=7),
        ),
    ]
