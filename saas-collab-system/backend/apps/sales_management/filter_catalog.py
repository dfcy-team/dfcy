"""Sales-only filter options derived from already scoped fact querysets."""

from django.db.models import F
from apps.masterdata.models import StoreMaster

def _tenant_distinct_values(queryset, field, *, fact_tenants=None):
    # DISTINCT against the original caller-scoped queryset preserves scope and
    # collation semantics in one SQL query. Candidate verification used to issue
    # one extra query per distinct value (up to dozens per catalog request).
    rows = queryset.order_by("tenant_id", field).values_list("tenant_id", field).distinct()
    return [value for _, value in rows]


def sales_filter_catalog(orders, refunds, sync_jobs):
    """Build filter options without widening caller-provided tenant/data scopes."""
    # Keep fact platform IDs: validated writes normally align them to the store,
    # but legacy/bulk-loaded facts may not. Resolve both dimensions separately.
    # Group in SQL by the values the catalog actually returns. Listing distinct
    # tenant/platform/store triples materializes fact-level combinations in
    # Python and grows with historical sales volume even when the catalog is
    # only a handful of stores. Keep malformed cross-tenant relations excluded
    # by checking both joined masters against each fact's tenant.
    valid_orders = orders.filter(
        store__tenant_id=F("tenant_id"),
        platform__tenant_id=F("tenant_id"),
    )
    store_platforms = list(
        valid_orders.order_by().values_list(
            "tenant_id", "store_id", "platform__platform_type",
        ).distinct()
    )
    store_ids = {store_id for _, store_id, _ in store_platforms}
    fact_tenants = {tenant_id for tenant_id, _, _ in store_platforms}
    # Preserve the legacy database ordering.
    store_rows = StoreMaster.objects.filter(id__in=store_ids, tenant_id__in=fact_tenants).order_by("code").values(
        "id", "tenant_id", "code", "name", "country_code",
    )
    pairs_by_store = {}
    for tenant_id, store_id, platform_type in store_platforms:
        pairs_by_store.setdefault(store_id, []).append((tenant_id, platform_type))
    stores = []
    seen_store_options = set()
    for store in store_rows:
        for tenant_id, platform_type in pairs_by_store[store["id"]]:
            if tenant_id != store["tenant_id"]:
                continue
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
        valid_orders.order_by().values_list("platform__platform_type", flat=True)
        .distinct()
        .order_by("platform__platform_type")
    )

    return {
        "platforms": platform_types,
        "stores": stores,
        "sites": [],
        "warehouses": [],
        "currencies": _tenant_distinct_values(orders, "currency", fact_tenants=fact_tenants),
        "order_statuses": _tenant_distinct_values(orders, "normalized_status", fact_tenants=fact_tenants),
        "refund_statuses": _tenant_distinct_values(refunds, "normalized_status"),
        "coverage_statuses": _tenant_distinct_values(sync_jobs, "status"),
    }
