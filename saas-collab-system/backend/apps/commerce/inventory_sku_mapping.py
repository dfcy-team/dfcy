"""Conservative SKU resolution for warehouse inventory, never fuzzy matching."""

from django.db.models import Q

from apps.products.models import ProductLegacyItem, ProductSKU, ProductSKUAlias
from apps.products.sku_aliases import code_key

from .models import InventorySnapshot


def _alias_rows(tenant, warehouse, codes):
    keys = {code_key(code) for code in codes if code}
    if not keys:
        return []
    return list(ProductSKUAlias.objects.filter(tenant=tenant, code_key__in=keys).filter(
        Q(scope_type="tenant") | Q(scope_type="warehouse", warehouse=warehouse)
    ).values_list("alias_code", "sku_id", "scope_type", "warehouse_id", "effective_from", "effective_to"))


def resolve_inventory_sku(*, tenant, warehouse, source_sku, seller_sku, snapshot_at_utc=None):
    # Reuse warehouse-scoped decisions, including explicitly approved aliases.
    # Compare strings in Python: MySQL's collation can ignore case.
    aliases = _alias_rows(tenant, warehouse, {source_sku})
    dated = [row for row in aliases if row[0] == source_sku]
    active_aliases = {sku_id for code, sku_id, scope, wid, start, end in dated
                      if snapshot_at_utc is not None and start <= snapshot_at_utc and (end is None or snapshot_at_utc < end)}
    history = InventorySnapshot.objects.filter(
        tenant=tenant, warehouse=warehouse, site_code=warehouse.country_code.upper(),
        source_sku=source_sku, internal_sku__isnull=False, internal_sku__tenant=tenant,
        source_run__sync_job__integration_config__platform="jifeng_wms",
    ).values_list("source_sku", "internal_sku_id")
    targets = {sku_id for code, sku_id in history if code == source_sku}
    if targets:
        if len(targets | active_aliases) > 1:
            return None, "history_conflict"
        return (next(iter(targets)), "warehouse_history") if len(targets) == 1 else (None, "history_conflict")

    if seller_sku and seller_sku != source_sku:
        return None, "seller_sku_conflict"

    catalogue = ProductSKU.objects.filter(tenant=tenant).filter(
        Q(sku_code=source_sku) | Q(legacy_sku_code=source_sku)
    ).values_list("id", "sku_code", "legacy_sku_code")
    targets = {sku_id for code, sku_id, scope, wid, start, end in dated
               if snapshot_at_utc is not None and start <= snapshot_at_utc and (end is None or snapshot_at_utc < end)} | {
        sku_id for sku_id, code, legacy in catalogue
        if source_sku in (code, legacy)
    }
    legacy_rows = ProductLegacyItem.objects.filter(
        tenant=tenant, legacy_sku_code=source_sku, status=ProductLegacyItem.Status.GENERATED,
        generated_sku__isnull=False, generated_sku__tenant=tenant,
    ).values_list("legacy_sku_code", "generated_sku_id")
    if not dated:
        targets.update(sku_id for code, sku_id in legacy_rows if code == source_sku)
    else:
        targets.difference_update(sku_id for sku_id, _code, legacy in catalogue if legacy == source_sku)
    if len(targets) == 1:
        return next(iter(targets)), "exact_catalogue_code"
    return None, "catalogue_conflict" if targets else "unmatched"


def resolve_inventory_skus(*, tenant, warehouse, sku_pairs, snapshot_times=None):
    """Resolve one inventory page with the same conservative rules as the scalar resolver."""
    pairs = list(dict.fromkeys((str(item[0]), str(item[1] or ""), item[2]) if len(item) > 2 else (str(item[0]), str(item[1] or ""), None) for item in sku_pairs))
    source_codes = {source for source, _seller, _at in pairs}
    snapshot_times = snapshot_times or {}
    history_targets = {source: set() for source in source_codes}
    for code, sku_id in InventorySnapshot.objects.filter(
        tenant=tenant,
        warehouse=warehouse,
        site_code=warehouse.country_code.upper(),
        source_sku__in=source_codes,
        internal_sku__isnull=False,
        internal_sku__tenant=tenant,
        source_run__sync_job__integration_config__platform="jifeng_wms",
    ).values_list("source_sku", "internal_sku_id"):
        if code in history_targets:
            history_targets[code].add(sku_id)

    catalogue_targets = {source: set() for source in source_codes}
    legacy_targets = {source: set() for source in source_codes}
    for sku_id, code, legacy in ProductSKU.objects.filter(tenant=tenant).filter(
        Q(sku_code__in=source_codes) | Q(legacy_sku_code__in=source_codes)
    ).values_list("id", "sku_code", "legacy_sku_code"):
        for exact_code in (code, legacy):
            if exact_code in catalogue_targets:
                catalogue_targets[exact_code].add(sku_id)
        if legacy in legacy_targets:
            legacy_targets[legacy].add(sku_id)
    alias_rows = _alias_rows(tenant, warehouse, source_codes)
    dated_codes = {code for code, *_ in alias_rows if code in source_codes}
    for code, sku_id in ProductLegacyItem.objects.filter(
        tenant=tenant,
        legacy_sku_code__in=source_codes,
        status=ProductLegacyItem.Status.GENERATED,
        generated_sku__isnull=False,
        generated_sku__tenant=tenant,
    ).values_list("legacy_sku_code", "generated_sku_id"):
        if code in catalogue_targets and code not in dated_codes:
            catalogue_targets[code].add(sku_id)
        if code in legacy_targets:
            legacy_targets[code].add(sku_id)

    resolved = {}
    for source_sku, seller_sku, at in pairs:
        history = history_targets[source_sku]
        active_aliases = {sku_id for code, sku_id, scope, wid, start, end in alias_rows
                          if code == source_sku and at is not None and start <= at and (end is None or at < end)}
        if history:
            union = history | active_aliases
            resolved[(source_sku, seller_sku, at)] = ((next(iter(union)), "warehouse_history")
                                                     if len(union) == 1 else (None, "history_conflict"))
        elif seller_sku and seller_sku != source_sku:
            resolved[(source_sku, seller_sku, at)] = (None, "seller_sku_conflict")
        else:
            catalogue = set(catalogue_targets[source_sku])
            catalogue.update(sku_id for code, sku_id, scope, wid, start, end in alias_rows
                             if code == source_sku and at is not None and start <= at and (end is None or at < end))
            if source_sku in dated_codes:
                catalogue.difference_update(legacy_targets[source_sku])
            resolved[(source_sku, seller_sku, at)] = (
                (next(iter(catalogue)), "exact_catalogue_code")
                if len(catalogue) == 1
                else (None, "catalogue_conflict" if catalogue else "unmatched")
            )
    return resolved
