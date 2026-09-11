"""Conservative SKU resolution for warehouse inventory, never fuzzy matching."""

from django.db.models import Q

from apps.products.models import ProductLegacyItem, ProductSKU

from .models import InventorySnapshot


def resolve_inventory_sku(*, tenant, warehouse, source_sku, seller_sku):
    if seller_sku and seller_sku != source_sku:
        return None, "seller_sku_conflict"

    # Reuse warehouse-scoped decisions, including explicitly approved aliases.
    # Compare strings in Python: MySQL's collation can ignore case.
    history = InventorySnapshot.objects.filter(
        tenant=tenant, warehouse=warehouse, site_code=warehouse.country_code.upper(),
        source_sku=source_sku, internal_sku__isnull=False, internal_sku__tenant=tenant,
        source_run__sync_job__integration_config__platform="jifeng_wms",
    ).values_list("source_sku", "internal_sku_id")
    targets = {sku_id for code, sku_id in history if code == source_sku}
    if targets:
        return (next(iter(targets)), "warehouse_history") if len(targets) == 1 else (None, "history_conflict")

    catalogue = ProductSKU.objects.filter(tenant=tenant).filter(
        Q(sku_code=source_sku) | Q(legacy_sku_code=source_sku)
    ).values_list("id", "sku_code", "legacy_sku_code")
    targets = {
        sku_id for sku_id, code, legacy in catalogue
        if source_sku in (code, legacy)
    }
    legacy_rows = ProductLegacyItem.objects.filter(
        tenant=tenant, legacy_sku_code=source_sku, status=ProductLegacyItem.Status.GENERATED,
        generated_sku__isnull=False, generated_sku__tenant=tenant,
    ).values_list("legacy_sku_code", "generated_sku_id")
    targets.update(sku_id for code, sku_id in legacy_rows if code == source_sku)
    if len(targets) == 1:
        return next(iter(targets)), "exact_catalogue_code"
    return None, "catalogue_conflict" if targets else "unmatched"
