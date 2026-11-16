"""Batch summaries with the same warehouse scopes as the detail endpoint."""
from apps.integrations.models import WarehouseAuthorization
from apps.permissions.services import check_stored_business_read_permission, get_stored_business_read_scopes
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .warehouse_order_models import OrderWarehouseLookup
from .warehouse_orders import LABELS


def attach_warehouse_summaries(user, rows):
    if not check_stored_business_read_permission(user, 'integrations.warehouse.view'):
        for row in rows:
            row['warehouse_summary'] = {'status': 'forbidden', 'status_label': '无仓库查看权限'}
        return
    lookups = list(OrderWarehouseLookup.objects.filter(
        order__tenant_id=user.tenant_id, order_id__in=[row['id'] for row in rows]))
    ids = {lookup.snapshot.get('authorization_id') for lookup in lookups if lookup.snapshot}
    visible = set()
    for auth in WarehouseAuthorization.objects.filter(tenant_id=user.tenant_id, pk__in=ids).select_related('integration_config'):
        if integration_values_allowed(user, 'integrations.warehouse.view', platform=auth.provider,
                environment=auth.integration_config.environment, regions=[auth.external_warehouse_region],
                config_id=auth.integration_config_id, warehouse_id=auth.warehouse_id,
                scope_resolver=get_stored_business_read_scopes):
            visible.add(auth.pk)
    by_order = {lookup.order_id: lookup for lookup in lookups}
    for row in rows:
        lookup = by_order.get(row['id'])
        summary = {'status': 'not_requested', 'status_label': '尚未查询'}
        if lookup:
            summary = {'status': lookup.status, 'status_label': LABELS.get(lookup.status, lookup.status),
                       'checked_at': lookup.checked_at, 'snapshot_at': lookup.snapshot_at}
            if lookup.snapshot and lookup.snapshot.get('authorization_id') in visible:
                summary['snapshot'] = lookup.snapshot
                summary['stale'] = lookup.status != 'matched'
            elif lookup.snapshot:
                summary = {'status': 'forbidden', 'status_label': '关联仓库不在查看范围内'}
        row['warehouse_summary'] = summary
