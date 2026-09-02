from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; purchase price is provided by deployed migration 0010."""

    dependencies = [("products", "0010_productspu_brand")]
    operations = []
