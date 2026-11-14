from django.db import migrations, models


def reserve(apps, schema_editor):
    intent = apps.get_model("flash_sales", "Intent")
    for row in intent.objects.all().iterator():
        if row.slot_id.isdecimal() and not row.absence_evidence.get("absent") and row.status != "failed":
            row.reservation_key = f"{row.tenant_id}:{row.store_id}:{row.slot_id}"
            row.save(update_fields=["reservation_key"])


class Migration(migrations.Migration):
    dependencies = [("flash_sales", "0003_dispatch_watermark")]
    operations = [
        migrations.AddField(model_name="intent", name="reservation_key", field=models.CharField(max_length=180, unique=True, null=True, blank=True)),
        migrations.RunPython(reserve, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="intent", name="flash_slot_occupation"),
    ]
