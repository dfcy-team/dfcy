from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility node for the duplicate main-line archive migration."""

    dependencies = [
        ("development", "0006_development_product_archive_codes"),
        ("development", "0003_developmentrequirementcompetitorlink"),
    ]
    operations = []
