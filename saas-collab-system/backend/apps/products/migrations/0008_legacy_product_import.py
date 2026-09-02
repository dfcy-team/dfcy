from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; legacy import schema is provided by deployed migration 0007."""

    dependencies = [("products", "0007_productattribute")]
    operations = []
