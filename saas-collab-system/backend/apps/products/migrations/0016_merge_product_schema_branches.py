from django.db import migrations


class Migration(migrations.Migration):
    """Join the independently shipped product schema branches.

    This migration deliberately has no database operations.  The dependencies
    preserve both the legacy product-detail path and the newer category and
    research paths so fresh databases and installations upgraded from either
    branch converge on one migration graph.
    """

    dependencies = [
        ("products", "0012_product_volume_precision"),
        ("products", "0012_product_detail_fields"),
        ("products", "0014_productcategory_row_background_color"),
        ("products", "0015_productresearch_category_sites"),
    ]

    operations = []
