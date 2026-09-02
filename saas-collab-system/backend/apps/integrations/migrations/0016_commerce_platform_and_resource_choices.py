from django.db import migrations, models


PLATFORM_CHOICES = [
    ("bigseller", "BigSeller"),
    ("shopee", "Shopee"),
    ("tiktok", "TikTok"),
    ("jifeng_wms", "Jifeng WMS"),
    ("mock", "Mock"),
    ("other", "Other"),
]


class Migration(migrations.Migration):
    dependencies = [("integrations", "0015_file_credential_custody_metadata")]

    operations = [
        migrations.AlterField(
            model_name="apiintegrationconfig",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name="apisynctask",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name="platformintegrationconfig",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name="marketplaceproductmapping",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name="marketplacestoreauthorization",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name="marketplacestoremapping",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name="oauthstatesession",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
        migrations.AlterField(
            model_name="syncjob",
            name="resource_type",
            field=models.CharField(
                choices=[
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
            model_name="webhookevent",
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        ),
    ]
