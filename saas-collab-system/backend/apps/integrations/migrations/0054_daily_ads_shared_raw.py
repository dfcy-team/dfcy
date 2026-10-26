from django.db import migrations, models
import django.db.models.deletion


def prevent_shared_payload_loss(apps, schema_editor):
    SharedPayload = apps.get_model("integrations", "SharedAdvertisingRawPayload")
    if SharedPayload.objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError(
            "Cannot reverse 0054 while shared advertising RAW payloads exist; "
            "they are the only content source for referencing envelopes."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0053_syncrawenvelope_external_payload"),
        ("masterdata", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedAdvertisingRawPayload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(choices=[("bigseller", "BigSeller"), ("lazada", "Lazada"), ("shopee", "Shopee"), ("tiktok", "TikTok"), ("jifeng_wms", "Jifeng WMS"), ("mock", "Mock"), ("other", "Other")], max_length=30)),
                ("endpoint", models.CharField(max_length=255)),
                ("payload_hash", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="shared_advertising_raw_payloads", to="masterdata.storemaster")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="shared_advertising_raw_payloads", to="tenants.tenant")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("tenant", "store", "platform", "endpoint", "payload_hash"), name="uniq_shared_ads_raw_content")],
            },
        ),
        migrations.CreateModel(
            name="AdvertisingRawPayloadReference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("envelope", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="shared_payload_reference", to="integrations.syncrawenvelope")),
                ("payload", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="references", to="integrations.sharedadvertisingrawpayload")),
            ],
        ),
        # This is last so it executes first during reversal, before either table drops.
        migrations.RunPython(migrations.RunPython.noop, prevent_shared_payload_loss),
    ]
