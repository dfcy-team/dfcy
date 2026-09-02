from django.db import migrations


class Migration(migrations.Migration):
    """Join the category-node and archive-code development branches."""

    dependencies = [
        ("development", "0005_category_nodes"),
        ("development", "0006_development_product_archive_codes"),
    ]

    operations = []
