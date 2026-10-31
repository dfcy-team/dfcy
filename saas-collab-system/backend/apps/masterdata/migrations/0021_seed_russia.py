from django.db import migrations


def seed_russia(apps, schema_editor):
    from apps.masterdata.country_seed import seed_country_sites
    countries = apps.get_model("masterdata", "CountrySiteMaster")
    tenants = apps.get_model("tenants", "Tenant")
    seed = ({"name": "俄罗斯", "country_code": "RU", "currency": "RUB", "timezone": "Europe/Moscow"},)
    for tenant in tenants.objects.all().iterator():
        seed_country_sites(tenant=tenant, model=countries, seeds=seed)


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0020_supplier_default_tax_rate")]
    operations = [migrations.RunPython(seed_russia, migrations.RunPython.noop)]
