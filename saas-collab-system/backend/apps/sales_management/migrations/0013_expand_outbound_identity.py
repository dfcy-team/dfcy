"""Expand only; legacy writers must be stopped before the following data phase."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales_management", "0012_warehouse_outbound_line")]
    operations = [
        migrations.AddField("warehouseoutboundline", "site_code", models.CharField(max_length=8, null=True)),
        migrations.AddField("warehouseoutboundline", "document_key", models.CharField(max_length=64, null=True)),
        migrations.AddField("warehouseoutboundline", "identity_key", models.CharField(max_length=64, null=True)),
    ]
