"""Country-scoped listing evidence. Unknown evidence must remain explicit."""
from collections import defaultdict
from apps.listings.models import PlatformProductDetail

def country_listing_evidence(actor, country_code, skus):
    from apps.commerce.country_decisions import filter_sales_queryset, SALES
    from apps.masterdata.models import StoreMaster
    from apps.permissions.services import check_user_permission
    tenant_id = actor.tenant_id
    if not check_user_permission(actor, SALES):
        return {s.pk: ["unknown"] for s in skus}
    allowed = filter_sales_queryset(actor, SALES, StoreMaster.objects.filter(tenant_id=tenant_id, country_code__iexact=country_code, status="active"), {"store_ids":"id", "platforms":"platform__platform_type", "regions":"country_code"})
    result=defaultdict(list)
    ids=[s.pk for s in skus]
    rows=PlatformProductDetail.objects.filter(tenant_id=tenant_id,internal_sku_id__in=ids,
        store__tenant_id=tenant_id,store_id__in=allowed.values("pk"),store__country_code__iexact=country_code,
        store__status='active',platform__status='active').select_related('marketplace_mapping','platform','store')
    for row in rows:
        mapping=getattr(row,'marketplace_mapping',None)
        valid=(mapping is not None and mapping.status=='mapped' and mapping.sku_id==row.internal_sku_id
            and mapping.tenant_id==tenant_id and row.platform_id==row.store.platform_id)
        status=(row.sales_status or '').upper()
        platform=row.platform.platform_type
        value='unknown'
        if valid and row.source=='api':
            if (platform=='tiktok' and status=='ACTIVATE'):value='on'
            elif (platform=='tiktok' and status=='SELLER_DEACTIVATED') or (platform=='shopee' and status in {'UNLIST','SELLER_DELETE'}):value='off'
        result[row.internal_sku_id].append(value)
    incomplete_scope = StoreMaster.objects.filter(tenant_id=tenant_id,country_code__iexact=country_code,status="active",platform__status="active").exclude(pk__in=allowed.values("pk")).exists()
    if incomplete_scope:
        for sku in skus:
            result[sku.pk].append("unknown")
    return dict(result)
