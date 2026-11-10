from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0060_shipment_inbound_counted_at")]

    operations = [migrations.CreateModel(name="SupplyPaymentRequestAttachment", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("file_name", models.CharField(max_length=200)), ("media_type", models.CharField(max_length=32)),
        ("byte_size", models.PositiveIntegerField()), ("sha256", models.CharField(max_length=64)),
        ("idempotency_key", models.CharField(max_length=128)), ("content", models.BinaryField()),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("updated_at", models.DateTimeField(auto_now=True)), ("version", models.PositiveIntegerField(default=1)),
        ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
        ("request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attachments", to="supply_chain.supplypaymentrequest")),
    ], options={"constraints": [models.UniqueConstraint(fields=("tenant", "request", "idempotency_key"), name="sc2_payreq_attachment_idem")]})]
