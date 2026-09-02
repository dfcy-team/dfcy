from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("integrations", "0019_sync_runtime_control_plane")]

    operations = [
        migrations.CreateModel(
            name="ConnectionCapability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("capability_code", models.CharField(choices=[("PRODUCT", "Product"), ("CATEGORY", "Category"), ("LISTING", "Listing"), ("PRICE", "Price"), ("ORDER", "Order"), ("INVENTORY", "Inventory"), ("FULFILLMENT", "Fulfillment"), ("WAREHOUSE", "Warehouse"), ("RETURN_REFUND", "Return and refund"), ("SETTLEMENT", "Settlement"), ("PAYMENT", "Payment"), ("ADVERTISING", "Advertising"), ("AFFILIATE", "Affiliate"), ("REVIEW", "Review"), ("REPORT", "Report"), ("WEBHOOK", "Webhook")], max_length=30)),
                ("read_enabled", models.BooleanField(default=False)),
                ("write_enabled", models.BooleanField(default=False)),
                ("sync_mode", models.CharField(choices=[("scheduled", "Scheduled"), ("realtime", "Realtime"), ("webhook", "Webhook"), ("manual", "Manual")], default="manual", max_length=20)),
                ("sync_cursor", models.CharField(blank=True, default="", max_length=500)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_failure_at", models.DateTimeField(blank=True, null=True)),
                ("source_priority", models.PositiveSmallIntegerField(default=100)),
                ("status", models.CharField(choices=[("disabled", "Disabled"), ("configured", "Configured"), ("active", "Active"), ("error", "Error")], default="disabled", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("authorization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="connection_capabilities", to="integrations.marketplacestoreauthorization")),
            ],
            options={
                "ordering": ["authorization_id", "source_priority", "capability_code"],
                "constraints": [models.UniqueConstraint(fields=("authorization", "capability_code"), name="uniq_connection_capability")],
            },
        )
    ]
