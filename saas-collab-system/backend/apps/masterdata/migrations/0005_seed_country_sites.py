from django.db import migrations


COUNTRY_SITES = (
    {
        "code": "PH",
        "name": "Philippines",
        "country_code": "PH",
        "currency": "PHP",
        "timezone": "Asia/Manila",
    },
    {
        "code": "TH",
        "name": "Thailand",
        "country_code": "TH",
        "currency": "THB",
        "timezone": "Asia/Bangkok",
    },
    {
        "code": "MY",
        "name": "Malaysia",
        "country_code": "MY",
        "currency": "MYR",
        "timezone": "Asia/Kuala_Lumpur",
    },
)


def seed_existing_tenants(apps, schema_editor):
    tenant_model = apps.get_model("tenants", "Tenant")
    country_model = apps.get_model("masterdata", "CountrySiteMaster")
    for tenant in tenant_model.objects.all().iterator():
        for site in COUNTRY_SITES:
            country_model.objects.update_or_create(
                tenant=tenant,
                code=site["code"],
                defaults={**site, "platform": None, "status": "active"},
            )


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0004_country_information_fields")]
    operations = [migrations.RunPython(seed_existing_tenants, migrations.RunPython.noop)]
