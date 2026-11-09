"""Add Ads store subjects without changing other platforms' scope predicates."""
from django.db.models import Q
from apps.permissions import ui_p6_scopes as scopes
from apps.integrations.models import TikTokAdsAdvertiserMapping


def mapping_allowed(user, mapping, permission_code, *, scope_resolver=None):
    config = mapping.integration_config
    return (user.is_active and user.user_type == "internal"
        and mapping.tenant_id == user.tenant_id and mapping.store.tenant_id == user.tenant_id
        and config.tenant_id == user.tenant_id and scopes.integration_values_allowed(
            user, permission_code, platform=config.platform, environment=config.environment,
            regions=list(dict.fromkeys([*(config.regions or []), mapping.store.country_code or "__UNKNOWN__"])),
            config_id=config.pk, resource_type="advertising_report", store_id=mapping.store_id, warehouse_id=None, scope_resolver=scope_resolver))


def filter_sync_jobs(user, queryset, permission_code):
    queryset = queryset.filter(tenant_id=user.tenant_id)
    ordinary = scopes.filter_sync_jobs(user, queryset.filter(ads_mapping__isnull=True), permission_code)
    ids = [job.pk for job in queryset.filter(tenant_id=user.tenant_id, ads_mapping__isnull=False).select_related(
        "ads_mapping__store", "ads_mapping__integration_config")
        if mapping_allowed(user, job.ads_mapping, permission_code)]
    return queryset.filter(Q(pk__in=ordinary.values("pk")) | Q(pk__in=ids))


def filter_sync_runs(user, queryset, permission_code):
    queryset = queryset.filter(tenant_id=user.tenant_id)
    ordinary = scopes.filter_sync_runs(user, queryset.filter(sync_job__ads_mapping__isnull=True), permission_code)
    ads_runs = queryset.filter(sync_job__ads_mapping__isnull=False)
    mapping_ids = ads_runs.order_by().values_list("sync_job__ads_mapping_id", flat=True).distinct()
    # Authorize each distinct mapping once, not once for every historical run.
    # Keep the model/tenant boundary on the mapping lookup and retain the original
    # queryset tenant filter above, so malformed cross-tenant relations remain hidden.
    mappings = TikTokAdsAdvertiserMapping.objects.filter(
        pk__in=mapping_ids,
        tenant_id=user.tenant_id,
        store__tenant_id=user.tenant_id,
        integration_config__tenant_id=user.tenant_id,
    ).select_related("store", "integration_config")
    allowed_mapping_ids = [
        mapping.pk for mapping in mappings
        if mapping_allowed(user, mapping, permission_code)
    ]
    return queryset.filter(Q(pk__in=ordinary.values("pk"))
                           | Q(sync_job__ads_mapping_id__in=allowed_mapping_ids))


def subject(mapping):
    return {"subject_type": "store", "store_id": mapping.store_id, "subject_id": mapping.store_id,
            "subject_code": mapping.store.code, "subject_name": f"{mapping.store.code} {mapping.store.name}".strip(),
            "subject_key": f"store:{mapping.store_id}", "region": mapping.store.country_code,
            "authorization_status": "active" if mapping.enabled else "disabled",
            "external_subject_id": mapping.advertiser_id, "ads_mapping_id": mapping.pk,
            "advertiser_id": mapping.advertiser_id, "advertiser_timezone": mapping.timezone}
