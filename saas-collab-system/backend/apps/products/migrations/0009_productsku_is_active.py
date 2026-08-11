from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0008_legacy_product_import")]

    operations = [
        migrations.AddField(
            model_name="productsku",
            name="is_active",
            field=models.BooleanField(db_index=True, default=True),
        ),
    ]
