"""Shared local product resolution for outreach reads and writes."""

from django.db.models import F

from apps.listings.models import PlatformProductDetail
from .models import StoreProductListing


def resolve_outreach_products(*, tenant, product_id, store_id=None):
    # Callers retain the outreach all-tenant permission gate. Never use a
    # platform ID without its tenant and store identity.
    stores = tenant.store_masters.filter(status="active").values("id")
    details = PlatformProductDetail.objects.filter(
        tenant=tenant, store_id__in=stores, platform_product_id=product_id,
        platform_id=F("store__platform_id"), platform__tenant=tenant,
    )
    legacy = StoreProductListing.objects.filter(
        tenant=tenant, store_id__in=stores, external_product_id=product_id,
    )
    ids = details.order_by().values_list("store_id", flat=True).union(
        legacy.order_by().values_list("store_id", flat=True)
    )
    if store_id is not None:
        selected = [store_id]
        truncated = False
    else:
        selected = list(ids.order_by("store_id")[:201])
        truncated = len(selected) > 200
        selected = selected[:200]
    grouped = {}

    def candidate(row, title, source):
        store = row.store
        return grouped.setdefault(store.id, {
            "store_id": store.id, "store_name": store.name,
            "store_code": store.code, "country_code": store.country_code,
            "product_name": title, "source": source, "sku_prefixes": set(), "skus": set(),
        })

    for row in details.filter(store_id__in=selected).select_related("store").order_by("-updated_at", "-id"):
        item = candidate(row, row.title, row.source)
        if row.platform_sku.strip():
            item["skus"].add(row.platform_sku.strip())
        prefix = row.sku_prefix.strip() or row.platform_sku.strip().split("-", 1)[0]
        if prefix:
            item["sku_prefixes"].add(prefix)
    # Only use legacy data for stores without a canonical platform snapshot.
    canonical_stores = set(grouped)
    for row in legacy.filter(store_id__in=selected).exclude(store_id__in=canonical_stores).select_related("store").prefetch_related("sku_prices").order_by("-source_updated_at", "-updated_at", "-id"):
        item = candidate(row, row.product_name, row.source)
        if row.parent_sku.strip():
            item["sku_prefixes"].add(row.parent_sku.strip())
        item["sku_prefixes"].update(
            price.external_sku.strip().split("-", 1)[0]
            for price in row.sku_prices.all()
            if price.tenant_id == tenant.id and price.external_sku.strip()
        )
        item["skus"].update(
            price.external_sku.strip() for price in row.sku_prices.all()
            if price.tenant_id == tenant.id and price.external_sku.strip()
        )
    return {
        "candidates": [{**item, "sku_prefixes": sorted(item["sku_prefixes"]), "skus": sorted(item["skus"])}
                       for item in sorted(grouped.values(), key=lambda item: (item["store_name"], item["store_id"]))],
        "truncated": truncated,
        "has_matches": bool(grouped) or details.exists() or legacy.exists(),
    }
