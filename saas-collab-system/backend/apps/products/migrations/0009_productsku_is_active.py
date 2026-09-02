from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; SKU activation is provided by deployed migration 0008."""

    dependencies = [("products", "0008_legacy_product_import")]
    operations = []
