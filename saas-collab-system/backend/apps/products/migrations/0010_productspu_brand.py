from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; SPU brand is provided by deployed migration 0009."""

    dependencies = [("products", "0009_productsku_is_active")]
    operations = []
