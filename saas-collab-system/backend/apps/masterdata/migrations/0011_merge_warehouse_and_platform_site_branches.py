from django.db import migrations


class Migration(migrations.Migration):
    """Join the warehouse-service and platform-site master-data branches."""

    dependencies = [
        ("masterdata", "0009_warehouse_service_platform"),
        ("masterdata", "0010_platform_site_and_store_channel_fields"),
    ]

    operations = []
