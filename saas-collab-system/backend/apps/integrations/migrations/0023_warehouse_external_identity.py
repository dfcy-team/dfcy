import hashlib
from collections import defaultdict

from django.db import migrations, models


def _legacy_warehouse_identity(auth):
    config = auth.integration_config
    values = config.platform_config if isinstance(config.platform_config, dict) else {}
    code = str(values.get("warehouse_code") or "").strip()
    region = str(values.get("site_code") or getattr(auth.warehouse, "country_code", "") or "").strip().upper()
    return code, region


def fail_on_legacy_warehouse_identity_duplicates(apps, schema_editor):
    """Preflight legacy config-level warehouse codes before adding keys.

    Older rows stored the Jifeng code on the shared integration config.  The
    binding-level column introduced by this migration must not silently pick a
    local warehouse when that legacy value is claimed by two active rows.
    """

    WarehouseAuthorization = apps.get_model("integrations", "WarehouseAuthorization")
    groups = defaultdict(list)
    queryset = WarehouseAuthorization.objects.filter(status="active").select_related(
        "integration_config", "warehouse"
    )
    for auth in queryset.iterator():
        code, region = _legacy_warehouse_identity(auth)
        if not code:
            continue
        key = (auth.tenant_id, auth.provider, region, code)
        groups[key].append((auth.id, auth.warehouse_id))
    duplicates = [(key, rows) for key, rows in groups.items() if len(rows) > 1]
    if duplicates:
        summary = "; ".join(
            f"tenant={key[0]},provider={key[1]},region={key[2] or '<blank>'},rows={[row[0] for row in rows[:5]]}"
            for key, rows in duplicates[:10]
        )
        raise RuntimeError(
            "Warehouse external identity preflight failed: "
            f"{len(duplicates)} active duplicate group(s) require manual resolution before migration. "
            f"Sample (non-secret row ids only): {summary}"
        )


def backfill_legacy_warehouse_identity(apps, schema_editor):
    WarehouseAuthorization = apps.get_model("integrations", "WarehouseAuthorization")
    for auth in WarehouseAuthorization.objects.select_related("integration_config", "warehouse").all().iterator():
        code, region = _legacy_warehouse_identity(auth)
        key = None
        if auth.status == "active" and code:
            canonical = f"{auth.provider}:{region}:{code}"
            key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        auth.external_warehouse_code = code
        auth.external_warehouse_region = region
        auth.external_warehouse_identity_key = key
        auth.save(update_fields=[
            "external_warehouse_code",
            "external_warehouse_region",
            "external_warehouse_identity_key",
        ])


class Migration(migrations.Migration):
    dependencies = [("integrations", "0022_product_mapping_platform_detail")]

    operations = [
        migrations.RunPython(fail_on_legacy_warehouse_identity_duplicates, migrations.RunPython.noop),
        migrations.AddField(
            model_name="warehouseauthorization",
            name="external_warehouse_code",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="warehouseauthorization",
            name="external_warehouse_region",
            field=models.CharField(blank=True, default="", max_length=8),
        ),
        migrations.AddField(
            model_name="warehouseauthorization",
            name="external_warehouse_identity_key",
            field=models.CharField(blank=True, default=None, max_length=64, null=True),
        ),
        migrations.RunPython(backfill_legacy_warehouse_identity, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="warehouseauthorization",
            constraint=models.UniqueConstraint(
                fields=("tenant", "external_warehouse_identity_key"),
                name="uniq_active_wh_external_identity",
            ),
        ),
    ]
