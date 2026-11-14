from django.db import migrations


def add_best(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Platform = apps.get_model("masterdata", "PlatformMaster")
    for tenant_id in Tenant.objects.values_list("pk", flat=True).iterator():
        Platform.objects.get_or_create(tenant_id=tenant_id, code="BEST", defaults={
            "name": "百世", "platform_type": "warehouse_third_party", "status": "active"})


class Migration(migrations.Migration):
    dependencies = [("integrations", "0060_best_ecapi_platform"), ("masterdata", "0022_merge_local_fx_vm370")]
    operations = [migrations.RunPython(add_best, migrations.RunPython.noop)]
