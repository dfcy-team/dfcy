"""Warehouse catalogue ingestion using the inventory SKU resolver."""
from django.core.exceptions import ValidationError
from django.db import transaction

from .inventory_sku_mapping import resolve_inventory_skus
from .models import WarehouseCatalogueItem


@transaction.atomic
def upsert_warehouse_catalogue_page(*, authorization, rows, observed_at):
    warehouse = authorization.warehouse
    config = authorization.integration_config
    if (
        authorization.status != "active"
        or authorization.provider != "best_ecapi"
        or config.platform != authorization.provider
        or config.tenant_id != authorization.tenant_id
        or warehouse.tenant_id != authorization.tenant_id
    ):
        raise ValidationError("An active same-tenant BEST warehouse authorization is required.")

    tenant = authorization.tenant
    customer = config.platform_config["customer_code"]
    by_key = {}
    for row in rows:
        code = row.get("sku")
        if not isinstance(code, str) or not code or code != code.strip() or len(code) > 64:
            raise ValidationError("Invalid warehouse catalogue SKU.")
        key = code.casefold()
        if len(key) > 128 or key in by_key or row.get("customerCode") != customer:
            raise ValidationError("Invalid warehouse catalogue identity.")
        by_key[key] = row

    pairs = [(row["sku"], row["sku"], observed_at) for row in by_key.values()]
    mappings = resolve_inventory_skus(tenant=tenant, warehouse=warehouse, sku_pairs=pairs)
    mapped = 0
    for key, row in by_key.items():
        code = row["sku"]
        sku_id, rule = mappings[(code, code, observed_at)]
        WarehouseCatalogueItem.objects.update_or_create(
            tenant=tenant, warehouse=warehouse, source_sku_key=key,
            defaults={
                "source_sku": code, "internal_sku_id": sku_id,
                "mapping_rule": rule, "source_data": row, "observed_at": observed_at,
            },
        )
        mapped += sku_id is not None
    return {"processed": len(by_key), "mapped": mapped, "unmapped": len(by_key) - mapped}
