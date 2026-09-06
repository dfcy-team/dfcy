from django.db import migrations, models


class Migration(migrations.Migration):
    """Register the platform-product read resource and trusted API mapping source."""

    dependencies = [("integrations", "0023_warehouse_external_identity")]

    operations = [
        migrations.AlterField(
            model_name="syncjob",
            name="resource_type",
            field=models.CharField(
                choices=[
                    ("platform_product", "Platform product"),
                    ("sales_order", "Sales order"),
                    ("refund_return", "Refund or return"),
                    ("inventory_snapshot", "Inventory snapshot"),
                    ("inbound", "Inbound"),
                    ("shipment", "Shipment"),
                    ("settlement_bill", "Settlement bill"),
                    ("withdrawal", "Withdrawal"),
                    ("mock_record", "Mock record"),
                ],
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="marketplaceproductmapping",
            name="mapping_source",
            field=models.CharField(
                choices=[
                    ("synthetic_discovery", "Synthetic discovery"),
                    ("manual", "Manual"),
                    ("suggested", "Suggested"),
                    ("api_exact_match", "Trusted API exact match"),
                ],
                max_length=30,
            ),
        ),
    ]
