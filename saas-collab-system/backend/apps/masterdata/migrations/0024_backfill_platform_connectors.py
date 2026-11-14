from django.db import migrations


WAREHOUSE_TYPES = {"warehouse_owned", "warehouse_third_party", "warehouse_platform"}
SUPPORTED = {"jifeng_wms", "best_ecapi"}
UNREVOKED = {"pending", "active", "expired", "error"}


def backfill(apps, schema_editor):
    Platform = apps.get_model("masterdata", "PlatformMaster")
    Warehouse = apps.get_model("masterdata", "WarehouseMaster")
    Authorization = apps.get_model("integrations", "WarehouseAuthorization")

    for platform in Platform.objects.all().iterator():
        if platform.platform_type not in WAREHOUSE_TYPES:
            Platform.objects.filter(pk=platform.pk).update(
                warehouse_connector_state=None,
                warehouse_connector_key="",
            )
            continue
        if platform.warehouse_connector_state in {"selected", "none"}:
            continue
        Platform.objects.filter(pk=platform.pk).update(
            warehouse_connector_state="pending",
            warehouse_connector_key="",
        )
        warehouse_ids = Warehouse.objects.filter(service_platform_id=platform.pk).values_list("pk", flat=True)
        rows = Authorization.objects.filter(
            warehouse_id__in=warehouse_ids,
            status__in=UNREVOKED,
        ).values_list("provider", "integration_config__platform")
        providers = set()
        conflict = False
        for provider, config_platform in rows:
            provider = str(provider or "").strip().lower()
            config_platform = str(config_platform or "").strip().lower()
            if provider not in SUPPORTED or provider != config_platform:
                conflict = True
                break
            providers.add(provider)
        if not conflict and len(providers) == 1:
            connector_key = providers.pop()
            Platform.objects.filter(
                pk=platform.pk,
                warehouse_connector_state="pending",
            ).update(
                warehouse_connector_state="selected",
                warehouse_connector_key=connector_key,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0023_platform_connector_fields"),
        ("integrations", "0061_best_platform_master"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
