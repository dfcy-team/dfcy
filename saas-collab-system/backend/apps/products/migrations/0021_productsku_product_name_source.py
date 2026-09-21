from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0020_product_detail_read_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="productsku",
            name="product_name_source",
            field=models.CharField(
                choices=[("auto", "Auto"), ("manual", "Manual")],
                default="auto",
                max_length=10,
            ),
        ),
    ]
