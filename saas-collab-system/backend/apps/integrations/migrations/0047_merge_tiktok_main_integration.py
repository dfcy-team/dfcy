from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0046_history_task_controls_detail_state"),
        ("integrations", "0046_syncjob_ads_mapping"),
    ]

    operations = [
        migrations.AlterField(
            model_name="syncjob", name="resource_type",
            field=models.CharField(max_length=40, choices=[
                ("advertising_report", "Advertising report"),
                ("platform_product", "Platform product"), ("sales_order", "Sales order"),
                ("affiliate_order", "Affiliate order"), ("refund_return", "Refund or return"),
                ("inventory_snapshot", "Inventory snapshot"), ("inbound", "Inbound"),
                ("shipment", "Shipment"), ("settlement_bill", "Settlement bill"),
                ("withdrawal", "Withdrawal"), ("mock_record", "Mock record"),
            ]),
        ),
        # Historical 0046 is retained exactly for already migrated TK hosts.
        # Shopee advertising uses a store authorization, not a TK Ads mapping.
        migrations.RemoveConstraint(model_name="syncjob", name="chk_sync_job_ads_subject"),
        migrations.AddConstraint(
            model_name="syncjob",
            constraint=models.CheckConstraint(
                condition=models.Q(ads_mapping__isnull=True) | models.Q(
                    ads_mapping__isnull=False, resource_type="advertising_report",
                    store_authorization__isnull=True, warehouse_authorization__isnull=True,
                ),
                name="chk_sync_job_ads_subject",
            ),
        ),
    ]
