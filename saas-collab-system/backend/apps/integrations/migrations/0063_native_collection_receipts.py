from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("integrations", "0061_creator_video_capability_choices")]
    operations = [
        migrations.AlterField(
            model_name="syncjob", name="resource_type",
            field=models.CharField(max_length=40, choices=[
                ("advertising_report", "Advertising report"), ("platform_product", "Platform product"),
                ("sales_order", "Sales order"), ("affiliate_order", "Affiliate order"),
                ("creator_profile", "TikTok creator profile"), ("video_metrics", "TikTok video metrics"),
                ("refund_return", "Refund or return"), ("inventory_snapshot", "Inventory snapshot"),
                ("inbound", "Inbound"), ("shipment", "Shipment"),
                ("settlement_bill", "Settlement bill"), ("withdrawal", "Withdrawal"),
                ("mock_record", "Mock record")]),
        ),
        migrations.CreateModel(name="CollectionUnitReceipt", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("unit_key", models.CharField(max_length=80)),
            ("result", models.JSONField(default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("sync_run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                related_name="collection_receipts", to="integrations.syncrun")),
        ], options={"constraints": [models.UniqueConstraint(
            fields=("sync_run", "unit_key"), name="uniq_collection_run_unit")]}),
    ]
