from django.db import migrations


def normalize_sample_cost_metadata(apps, schema_editor):
    snapshot = apps.get_model("influencers", "BdSampleAttributionSnapshot")
    snapshot.objects.exclude(currency="CNY").update(currency="CNY")
    snapshot.objects.exclude(pricing_status="pending").update(pricing_status="pending")


class Migration(migrations.Migration):
    dependencies = [
        ("influencers", "0014_nullable_affiliate_commissions"),
    ]

    operations = [
        migrations.RunPython(normalize_sample_cost_metadata, migrations.RunPython.noop),
    ]
