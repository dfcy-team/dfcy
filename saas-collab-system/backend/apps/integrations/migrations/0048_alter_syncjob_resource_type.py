from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0047_merge_tiktok_main_integration")]

    operations = [
        migrations.AlterField(
            model_name="syncjob",
            name="resource_type",
            field=models.CharField(max_length=40, choices=[
                ("advertising_report", "Advertising report"),
                ("platform_product", "Platform product"),
                ("sales_order", "Sales order"),
                ("affiliate_order", "Affiliate order"),
                ("refund_return", "Refund or return"),
                ("inventory_snapshot", "Inventory snapshot"),
                ("inbound", "Inbound"),
                ("shipment", "Shipment"),
                ("settlement_bill", "Settlement bill"),
                ("withdrawal", "Withdrawal"),
                ("mock_record", "Mock record"),
            ]),
        ),
    ]
