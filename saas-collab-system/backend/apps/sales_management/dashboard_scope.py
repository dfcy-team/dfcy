"""Small master-data projection for permission-first dashboard store choices."""
from django.db.models import Q

from apps.masterdata.models import StoreMaster
from apps.permissions.role_catalog import user_is_tenant_administrator

from .scopes import filter_sales_queryset


def dashboard_stores(user, permission_code, permission_cache=None):
    # Reuse the same role branches as sales facts; never combine store grants
    # from one role with platform/region grants from another.
    stores = filter_sales_queryset(
        user, permission_code, StoreMaster.objects.filter(tenant_id=user.tenant_id),
        scope_field_map={"store_ids": "pk", "platforms": "platform__platform_type", "regions": "country_code"},
        permission_cache=permission_cache,
    )
    if not (user.is_superuser or user_is_tenant_administrator(user, user.tenant)):
        stores = stores.filter(Q(operator_id=user.pk) | Q(bd_id=user.pk) | Q(leader_id=user.pk))
    return stores.order_by("code", "pk")
