from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0043_internal_api_tiktok_token_store")]
    operations = [migrations.AlterField(
        model_name="syncjob", name="resource_type",
        field=models.CharField(max_length=40, choices=[
            ("platform_product", "Platform product"), ("sales_order", "Sales order"),
            ("affiliate_order", "Affiliate order"), ("refund_return", "Refund or return"),
            ("inventory_snapshot", "Inventory snapshot"), ("inbound", "Inbound"),
            ("shipment", "Shipment"), ("settlement_bill", "Settlement bill"),
            ("withdrawal", "Withdrawal"), ("mock_record", "Mock record"),
        ]),
    )]
