from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; schema is provided by 0005_product_coding_and_bundles."""

    dependencies = [("products", "0005_productspu_development_project_and_more")]
    operations = []
