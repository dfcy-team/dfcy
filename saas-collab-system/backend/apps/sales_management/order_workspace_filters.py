"""Order workspace filters over saved records, within warehouse read scopes."""
from collections import Counter

from django.core.exceptions import EmptyResultSet
from django.db import connections
from django.db.models import Case, CharField, Count, F, Q, Subquery, Value, When
from rest_framework.exceptions import ValidationError
from apps.integrations.models import WarehouseAuthorization
from apps.permissions.services import check_stored_business_read_permission, get_stored_business_read_scopes
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .warehouse_order_models import OrderWarehouseLookup


def visible_authorizations(user):
    if not check_stored_business_read_permission(user, 'integrations.warehouse.view'):
        return []
    return [auth for auth in WarehouseAuthorization.objects.filter(tenant_id=user.tenant_id).select_related('integration_config', 'warehouse')
            if integration_values_allowed(user, 'integrations.warehouse.view', platform=auth.provider,
                environment=auth.integration_config.environment, regions=[auth.external_warehouse_region],
                config_id=auth.integration_config_id, warehouse_id=auth.warehouse_id,
                scope_resolver=get_stored_business_read_scopes)]


def visible_lookups(user):
    if not check_stored_business_read_permission(user, 'integrations.warehouse.view'):
        return OrderWarehouseLookup.objects.none()
    return _visible_lookup_queryset(user, visible_authorizations(user))


def _visible_lookup_queryset(user, authorizations):
    return OrderWarehouseLookup.objects.filter(order__tenant_id=user.tenant_id).filter(
        Q(snapshot={}) | Q(snapshot__authorization_id__in=[auth.pk for auth in authorizations]))


def filter_workspace(request, queryset):
    params = request.query_params
    warehouse = params.get('warehouse_id')
    state = params.get('warehouse_status')
    search = params.get('search', '').strip()
    if not (warehouse or state or search):
        return queryset
    lookups = visible_lookups(request.user).filter(order__in=queryset)
    if warehouse:
        try:
            warehouse = int(warehouse)
            if warehouse <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError({'warehouse_id': '仓库 ID 必须为正整数。'}) from None
        queryset = queryset.filter(pk__in=Subquery(lookups.filter(warehouse_id=warehouse).values('order_id')))
    if state:
        if state not in {'matched', 'not_found', 'not_requested', 'pending', 'running', 'partial', 'conflict', 'failed', 'blocked'}:
            raise ValidationError({'warehouse_status': '无效的仓库查询状态。'})
        if not check_stored_business_read_permission(request.user, 'integrations.warehouse.view'):
            return queryset.none()
        if state == 'not_requested':
            queryset = queryset.filter(warehouse_lookup__isnull=True)
        else:
            queryset = queryset.filter(pk__in=Subquery(lookups.filter(status=state).values('order_id')))
    if search:
        if len(search) > 160:
            raise ValidationError({'search': '搜索内容最多 160 字符。'})
        # JSON candidate narrowing followed by explicit field matching; never search unrelated snapshot values.
        warehouse_ids = []
        needle = search.casefold()
        for order_id, snapshot in lookups.filter(snapshot__packages__icontains=search).values_list('order_id', 'snapshot').iterator():
            values = []
            for package in snapshot.get('packages', []):
                values.extend(package.get(key) for key in ('tracking_no', 'warehouse_order_no', 'erp_no', 'booking_no', 'package_no'))
                for item in package.get('items', []):
                    values.extend(item.get(key) for key in ('sku', 'warehouse_sku'))
            if any(needle in str(value).casefold() for value in values if value is not None):
                warehouse_ids.append(order_id)
        platform_ids = []
        candidates = queryset.filter(Q(source_details__packages__icontains=search) | Q(source_details__platform_logistics__packages__icontains=search))
        for order_id, details in candidates.values_list('pk', 'source_details').iterator():
            packages = list(details.get('packages') or []) + list((details.get('platform_logistics') or {}).get('packages') or [])
            if any(needle in str(package.get(key) or '').casefold() for package in packages
                   for key in ('tracking_number', 'package_number', 'package_id')):
                platform_ids.append(order_id)
        from apps.commerce.models import SalesOrderItem
        item_ids = SalesOrderItem.objects.filter(sales_order__in=queryset, seller_sku__icontains=search).values('sales_order_id')
        queryset = queryset.filter(Q(external_order_id__icontains=search) | Q(pk__in=Subquery(item_ids)) | Q(pk__in=warehouse_ids) | Q(pk__in=platform_ids))
    return queryset


def workspace_summary(request, queryset):
    status_query = queryset.order_by().values('normalized_status')
    connection = connections[status_query.db]
    params = request.query_params
    has_date_range = (params.get('date_from') or params.get('period_start')) and (
        params.get('date_to') or params.get('period_end'))
    can_view = check_stored_business_read_permission(request.user, 'integrations.warehouse.view')
    authorizations = visible_authorizations(request.user) if can_view else []
    warehouse_counts = None

    if connection.vendor == 'mysql' and has_date_range:
        warehouse_group = '__missing_lookup__'
        if can_view:
            visible = Q(warehouse_lookup__snapshot={}) | Q(
                warehouse_lookup__snapshot__authorization_id__in=[auth.pk for auth in authorizations])
            status_query = status_query.values('normalized_status', warehouse_group=Case(
                When(warehouse_lookup__isnull=True, then=Value(warehouse_group)),
                When(visible, then=F('warehouse_lookup__status')),
                default=Value(None), output_field=CharField(),
            ))
        status_query = status_query.annotate(count=Count('pk'))
        try:
            sql, values = status_query.query.get_compiler(using=status_query.db).as_sql()
        except EmptyResultSet:
            grouped = []
        else:
            # Use the tenant/store/time range instead of scanning the status index for GROUP BY.
            sql = sql.replace('SELECT ', 'SELECT /*+ INDEX(sales_order idx_sales_order_store_time) */ ', 1)
            with connection.cursor() as cursor:
                cursor.execute(sql, values)
                grouped = cursor.fetchall()
        status_counts = Counter()
        if can_view:
            warehouse_counts = {'not_requested': 0}
            for status, lookup_status, count in grouped:
                status_counts[status] += count
                if lookup_status == warehouse_group:
                    warehouse_counts['not_requested'] += count
                elif lookup_status is not None and lookup_status != 'not_requested':
                    warehouse_counts[lookup_status] = warehouse_counts.get(lookup_status, 0) + count
        else:
            status_counts.update(dict(grouped))
        statuses = [{'normalized_status': status, 'count': count} for status, count in status_counts.items()]
    else:
        statuses = list(status_query.annotate(count=Count('pk')))
        if can_view:
            lookups = _visible_lookup_queryset(request.user, authorizations).filter(order__in=queryset)
            warehouse_counts = dict(lookups.order_by().values_list('status').annotate(count=Count('pk')))
            warehouse_counts['not_requested'] = queryset.filter(warehouse_lookup__isnull=True).count()

    warehouses = {auth.warehouse_id: {'value': auth.warehouse_id, 'label': f'{auth.warehouse.code} · {auth.warehouse.name}'}
                  for auth in authorizations}
    return {'statuses': statuses, 'warehouse_counts': warehouse_counts, 'warehouses': list(warehouses.values())}
