from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0009_productsku_is_active")]

    operations = [
        migrations.AddField(
            model_name="productspu",
            name="brand",
            field=models.CharField(blank=True, db_index=True, max_length=120),
        ),
    ]
