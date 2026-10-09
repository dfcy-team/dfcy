"""Sales-only filter options derived from already scoped fact querysets."""

from apps.masterdata.models import PlatformMaster, StoreMaster


def _tenant_distinct_values(queryset, field):
    # Keep the tenant prefix in DISTINCT for the fact-table indexes, while
    # letting the database retain blank values and apply its text collation.
    rows = queryset.order_by("tenant_id", field).values_list("tenant_id", field).distinct()
    return [value for _, value in rows]


def sales_filter_catalog(orders, refunds, sync_jobs):
    """Build filter options without widening caller-provided tenant/data scopes."""
    # Keep fact platform IDs: validated writes normally align them to the store,
    # but legacy/bulk-loaded facts may not. Resolve both dimensions separately.
    facts = list(
        orders.order_by()
        .values_list("tenant_id", "platform_id", "store_id")
        .distinct()
    )
    store_ids = {store_id for _, _, store_id in facts}
    platform_ids = {platform_id for _, platform_id, _ in facts}
    fact_tenants = {tenant_id for tenant_id, _, _ in facts}
    platform_rows = PlatformMaster.objects.filter(id__in=platform_ids).values_list(
        "id", "tenant_id", "platform_type"
    )
    platforms_by_id = {
        platform_id: (tenant_id, platform_type)
        for platform_id, tenant_id, platform_type in platform_rows
        if tenant_id in fact_tenants
    }
    # Preserve the fact's platform dimension and the legacy database ordering.
    # Include tenant keys to reject malformed cross-tenant fact relations.
    store_rows = StoreMaster.objects.filter(id__in=store_ids).order_by("code").values(
        "id", "tenant_id", "code", "name", "country_code",
    )
    pairs_by_store = {}
    for tenant_id, platform_id, store_id in facts:
        pairs_by_store.setdefault(store_id, []).append((tenant_id, platform_id))
    stores = []
    seen_store_options = set()
    for store in store_rows:
        for tenant_id, platform_id in pairs_by_store[store["id"]]:
            platform = platforms_by_id.get(platform_id)
            if not platform or tenant_id != store["tenant_id"] or tenant_id != platform[0]:
                continue
            platform_type = platform[1]
            option = (store["id"], platform_type)
            if option in seen_store_options:
                continue
            seen_store_options.add(option)
            stores.append({
                "id": store["id"], "code": store["code"], "name": store["name"],
                "region": store["country_code"], "platform": platform_type,
            })
    # This is a small master-data lookup; DISTINCT and ordering stay in SQL.
    platform_types = list(
        PlatformMaster.objects.filter(id__in=platform_ids, tenant_id__in=fact_tenants)
        .values_list("platform_type", flat=True)
        .distinct()
        .order_by("platform_type")
    )

    return {
        "platforms": platform_types,
        "stores": stores,
        "sites": [],
        "warehouses": [],
        "currencies": _tenant_distinct_values(orders, "currency"),
        "order_statuses": _tenant_distinct_values(orders, "normalized_status"),
        "refund_statuses": _tenant_distinct_values(refunds, "normalized_status"),
        "coverage_statuses": _tenant_distinct_values(sync_jobs, "status"),
    }
