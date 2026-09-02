from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; category fields are in 0004_development_product_archives."""

    dependencies = [
        ("development", "0004_developmentproductarchive_and_more"),
    ]
    operations = []
