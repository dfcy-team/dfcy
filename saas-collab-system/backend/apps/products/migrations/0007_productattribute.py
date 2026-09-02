from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node; ProductAttribute is provided by deployed migration 0006."""

    dependencies = [("products", "0006_productsku_color_code_productsku_spec_values_and_more")]
    operations = []
