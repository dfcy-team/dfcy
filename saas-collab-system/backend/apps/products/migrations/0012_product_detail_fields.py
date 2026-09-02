from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; detail fields are provided by deployed migration 0011."""

    dependencies = [("products", "0011_product_purchase_price")]
    operations = []
