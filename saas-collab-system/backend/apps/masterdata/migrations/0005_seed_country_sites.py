from django.db import migrations


def seed_existing_tenants(apps, schema_editor):
    from apps.masterdata.country_seed import seed_country_sites

    tenant_model = apps.get_model("tenants", "Tenant")
    country_model = apps.get_model("masterdata", "CountrySiteMaster")
    for tenant in tenant_model.objects.all().iterator():
        seed_country_sites(tenant=tenant, model=country_model)


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0004_country_information_fields")]
    operations = [migrations.RunPython(seed_existing_tenants, migrations.RunPython.noop)]

