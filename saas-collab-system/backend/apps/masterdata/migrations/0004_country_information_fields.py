from django.db import migrations, models


COUNTRY_DEFAULTS = {
    "PH": ("PHP", "Asia/Manila"),
    "TH": ("THB", "Asia/Bangkok"),
    "SG": ("SGD", "Asia/Singapore"),
    "MY": ("MYR", "Asia/Kuala_Lumpur"),
    "ID": ("IDR", "Asia/Jakarta"),
    "VN": ("VND", "Asia/Ho_Chi_Minh"),
    "US": ("USD", "America/New_York"),
    "GB": ("GBP", "Europe/London"),
}


def backfill_country_defaults(apps, schema_editor):
    country_model = apps.get_model("masterdata", "CountrySiteMaster")
    for row in country_model.objects.all().iterator():
        currency, timezone = COUNTRY_DEFAULTS.get((row.country_code or "").upper(), ("", "UTC"))
        updates = {}
        if not row.currency:
            updates["currency"] = currency
        if not row.timezone or row.timezone == "UTC":
            updates["timezone"] = timezone
        if updates:
            country_model.objects.filter(pk=row.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0003_countrysitemaster")]

    operations = [
        migrations.AlterField(
            model_name="countrysitemaster",
            name="platform",
            field=models.CharField(blank=True, default=None, max_length=60, null=True),
        ),
        migrations.AddField(
            model_name="countrysitemaster",
            name="currency",
            field=models.CharField(blank=True, default="", max_length=8),
        ),
        migrations.AddField(
            model_name="countrysitemaster",
            name="timezone",
            field=models.CharField(blank=True, default="UTC", max_length=60),
        ),
        migrations.RunPython(backfill_country_defaults, migrations.RunPython.noop),
    ]
