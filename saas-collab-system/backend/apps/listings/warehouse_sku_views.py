"""Warehouse SKU mapping over existing inventory facts; no duplicate catalogue."""
import csv
from datetime import timezone as datetime_timezone

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Window
from django.db.models.functions import RowNumber
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError

from apps.commerce.inventory_sku_mapping import resolve_inventory_sku
from apps.commerce.models import InventorySnapshot
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.common.query import pagination_query
from apps.common.responses import success_response
from apps.integrations.models import IntegrationAuditLog
from apps.masterdata.models import WarehouseMaster
from apps.permissions.ui_p6_scopes import (
    INTEGRATION_SCOPE_KEYS, _validate_integration_configs, _validate_positive_int_values,
    permission_scope_configs,
)
from apps.products.models import ProductSKU, ProductSPU
from .permissions import permission_class


VIEW = 'integrations.product_mapping.view'
CONFIRM = 'integrations.product_mapping.confirm'
WAREHOUSE_SKU_SCOPE_KEYS = INTEGRATION_SCOPE_KEYS | {'sku_ids', 'spu_ids'}
WAREHOUSE_FACT_FIELDS = {
    'warehouse_ids': 'warehouse_id', 'sku_ids': 'internal_sku_id',
    'spu_ids': 'internal_sku__spu_id', 'regions': 'site_code',
    'platforms': 'source_run__sync_job__integration_config__platform',
    'environments': 'source_run__sync_job__integration_config__environment',
    'integration_config_ids': 'source_run__sync_job__integration_config_id',
    'resource_types': 'source_run__sync_job__resource_type',
}


def _facts(user):
    return InventorySnapshot.objects.filter(
        tenant=user.tenant, warehouse__tenant=user.tenant,
        source_run__sync_job__tenant=user.tenant,
        source_run__sync_job__integration_config__tenant=user.tenant,
        source_run__sync_job__integration_config__platform='jifeng_wms',
        source_run__sync_job__resource_type='inventory_snapshot',
    ).filter(Q(internal_sku__isnull=True) | Q(internal_sku__tenant=user.tenant))


def _scope_configs(user, code):
    configs = permission_scope_configs(
        user, code, WAREHOUSE_SKU_SCOPE_KEYS,
        allowed_keys=WAREHOUSE_SKU_SCOPE_KEYS | {'platform_ids', 'site_ids', 'supplier_ids'},
        incompatible_keys={'platform_ids', 'site_ids', 'supplier_ids', 'store_ids'},
        resource_code='commerce.inventory',
    )
    if configs is None:
        return None
    _validate_integration_configs(configs)
    for config in configs:
        for key, model in (('sku_ids', ProductSKU), ('spu_ids', ProductSPU)):
            if key not in config:
                continue
            _validate_positive_int_values(config[key], f'库存数据范围的{key}包含无效 ID。')
            ids = set(config[key])
            if model.objects.filter(tenant=user.tenant, pk__in=ids).count() != len(ids):
                raise DataScopeDenied('库存数据范围包含其他租户或不存在的商品。',
                                      error_code=ErrorCode.DATA_SCOPE_FORBIDDEN)
    return configs


def _scope_branch(config, *, include_sku=True):
    branch = Q()
    for key, field in WAREHOUSE_FACT_FIELDS.items():
        if key in config and (include_sku or key not in {'sku_ids', 'spu_ids'}):
            branch &= Q(**{f'{field}__in': config[key]})
    return branch


def _scoped(user, code):
    rows = _facts(user)
    configs = _scope_configs(user, code)
    if configs is None:
        return rows
    allowed = Q(pk__in=[])
    for config in configs:
        allowed |= _scope_branch(config)
    return rows.filter(allowed)


def _target_skus(user, code, row):
    """Apply the post-confirm scope to candidate SKUs for this fixed inventory fact."""
    candidates = ProductSKU.objects.filter(tenant=user.tenant, is_active=True)
    configs = _scope_configs(user, code)
    if configs is None:
        return candidates
    allowed = Q(pk__in=[])
    fixed_row = _facts(user).filter(pk=row.pk)
    for config in configs:
        if not fixed_row.filter(_scope_branch(config, include_sku=False)).exists():
            continue
        if 'sku_ids' not in config and 'spu_ids' not in config:
            return candidates
        branch = Q()
        if 'sku_ids' in config:
            branch &= Q(pk__in=config['sku_ids'])
        if 'spu_ids' in config:
            branch &= Q(spu_id__in=config['spu_ids'])
        allowed |= branch
    return candidates.filter(allowed)


def _history(user, row):
    # Exact comparison also on MySQL installations with case-insensitive collation.
    return [item for item in _facts(user).filter(
        warehouse_id=row.warehouse_id, site_code=row.site_code, source_sku=row.source_sku,
    ).only('id', 'source_sku', 'internal_sku_id') if item.source_sku == row.source_sku]


class WarehouseRowSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source='warehouse.name')
    warehouse_code = serializers.CharField(source='warehouse.code')
    internal_sku_code = serializers.CharField(source='internal_sku.sku_code', default='')
    internal_legacy_sku_code = serializers.CharField(source='internal_sku.legacy_sku_code', default='')

    class Meta:
        model = InventorySnapshot
        fields = ['id', 'warehouse_id', 'warehouse_name', 'warehouse_code', 'site_code',
                  'source_sku', 'internal_sku_id', 'internal_sku_code', 'internal_legacy_sku_code',
                  'snapshot_at_utc', 'on_hand_qty']


def _filtered_rows(user, params):
    rows = _scoped(user, VIEW)
    # Rank the eligible facts once. The old correlated latest-row subquery was
    # re-evaluated for every historical snapshot, making counts and pages slow.
    latest_ids = _facts(user).annotate(_latest_rank=Window(
        expression=RowNumber(),
        partition_by=[F('warehouse_id'), F('site_code'), F('source_sku')],
        order_by=[F('snapshot_at_utc').desc(), F('id').desc()],
    )).filter(_latest_rank=1).values('pk')
    rows = rows.filter(pk__in=Subquery(latest_ids))
    warehouse = params.get('warehouse_id')
    if warehouse:
        if not str(warehouse).isdigit() or int(warehouse) <= 0:
            raise ValidationError({'warehouse_id': '请选择有效仓库。'})
        rows = rows.filter(warehouse_id=warehouse)
    search = params.get('search', '').strip()
    if search:
        rows = rows.filter(Q(source_sku__icontains=search) | Q(internal_sku__sku_code__icontains=search)
                           | Q(internal_sku__legacy_sku_code__icontains=search))
    status = params.get('status', '')
    if status not in ('', 'mapped', 'unmapped'):
        raise ValidationError({'status': '请选择已关联或未关联。'})
    if status:
        rows = rows.filter(internal_sku__isnull=status == 'unmapped')
    return rows.select_related('warehouse', 'internal_sku').order_by('warehouse_id', 'source_sku', 'id')


def _warehouse_options(user):
    visible_fact = _scoped(user, VIEW).filter(warehouse_id=OuterRef('pk'))
    return WarehouseMaster.objects.filter(tenant=user.tenant).alias(
        _has_visible_fact=Exists(visible_fact),
    ).filter(_has_visible_fact=True).order_by('code', 'id').values('id', 'name', 'code')


def _page_data(request, rows, page, size):
    # A window count travels with the requested rows, avoiding a second scan
    # of all historical inventory snapshots for Paginator.count.
    page_rows = list(rows.annotate(_result_count=Window(expression=Count('pk')))[(page - 1) * size:page * size])
    if not page_rows and page > 1:
        raise NotFound('Requested page does not exist.')
    total = page_rows[0]._result_count if page_rows else 0

    def page_url(target):
        params = request.query_params.copy()
        params['page'] = target
        params['page_size'] = size
        return request.build_absolute_uri(f'{request.path}?{params.urlencode()}')

    return {
        'count': total,
        'next': page_url(page + 1) if page * size < total else None,
        'previous': page_url(page - 1) if page > 1 else None,
        'results': WarehouseRowSerializer(page_rows, many=True).data,
    }


def _csv_text(value):
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@')) else text


@api_view(['GET'])
@permission_classes([permission_class(VIEW)])
def warehouse_skus(request):
    options = list(_warehouse_options(request.user))
    rows = _filtered_rows(request.user, request.query_params)
    page, size = pagination_query(request)
    data = _page_data(request, rows, page, size)
    data['warehouse_options'] = [{'value': row['id'], 'label': f"{row['name']}（{row['code']}）"} for row in options]
    return success_response(data)


@api_view(['GET'])
@permission_classes([permission_class(VIEW)])
def export_warehouse_skus(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="warehouse-skus-{timezone.now():%Y%m%d-%H%M%S}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['平台', '店铺/仓库', '仓库编码', '来源 SKU', '内部旧 SKU', '内部新 SKU', 'SKU 关联', '在手（件）', '快照时间（UTC）'])
    for row in _filtered_rows(request.user, request.query_params).iterator(chunk_size=1000):
        snapshot_at = row.snapshot_at_utc.astimezone(datetime_timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow(['极风 WMS', _csv_text(row.warehouse.name), _csv_text(row.warehouse.code),
                         _csv_text(row.source_sku), _csv_text(getattr(row.internal_sku, 'legacy_sku_code', '')),
                         _csv_text(getattr(row.internal_sku, 'sku_code', '')), '已关联' if row.internal_sku_id else '未关联',
                         row.on_hand_qty, snapshot_at])
    return response


@api_view(['GET', 'PATCH'])
@permission_classes([permission_class(VIEW)])
def warehouse_sku_mapping(request, pk):
    if request.method == 'GET':
        row = get_object_or_404(_scoped(request.user, VIEW).select_related('warehouse'), pk=pk)
        history = _history(request.user, row)
        if _scoped(request.user, VIEW).filter(pk__in=[item.pk for item in history]).count() != len(history):
            raise NotFound()
        ids = sorted({item.internal_sku_id for item in history if item.internal_sku_id})
        target, rule = resolve_inventory_sku(tenant=request.user.tenant, warehouse=row.warehouse,
                                            source_sku=row.source_sku, seller_sku=row.seller_sku)
        search = request.query_params.get('search', '').strip()
        candidates = _target_skus(request.user, VIEW, row)
        if target and not candidates.filter(pk=target).exists():
            target = None
        if search:
            candidates = candidates.filter(Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search))
        else:
            candidates = candidates.filter(pk__in=ids + ([target] if target else []))
        return success_response({'current_sku_ids': ids, 'suggested_sku_id': target, 'rule': rule,
            'candidates': list(candidates.order_by('sku_code').values('id', 'sku_code', 'legacy_sku_code')[:20])})
    # Explicit confirm grant, not the generic edit or view permission.
    if not permission_class(CONFIRM)().has_permission(request, None):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('缺少 SKU 映射确认权限。')
    payload = ConfirmSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    values = payload.validated_data
    with transaction.atomic():
        row = get_object_or_404(_scoped(request.user, CONFIRM), pk=pk)
        WarehouseMaster.objects.select_for_update().get(pk=row.warehouse_id, tenant=request.user.tenant)
        history = _history(request.user, row)
        before = sorted({item.internal_sku_id for item in history if item.internal_sku_id})
        if before != sorted(set(values['expected_sku_ids'])):
            raise ValidationError('映射已变化，请刷新后重新确认。')
        # All affected facts must be inside both the read and confirm grants.
        ids = [item.id for item in history]
        if _scoped(request.user, CONFIRM).filter(pk__in=ids).count() != len(ids) or _scoped(request.user, VIEW).filter(pk__in=ids).count() != len(ids):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('当前权限未覆盖此仓库 SKU 的全部历史，不能修改共享映射。')
        sku = get_object_or_404(ProductSKU, pk=values['sku_id'], tenant=request.user.tenant, is_active=True)
        if (not _target_skus(request.user, CONFIRM, row).filter(pk=sku.pk).exists()
                or not _target_skus(request.user, VIEW, row).filter(pk=sku.pk).exists()):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('目标 SKU 超出当前数据范围。')
        changed = [item.id for item in history if item.internal_sku_id != sku.id]
        if changed:
            InventorySnapshot.objects.filter(pk__in=changed).update(internal_sku=sku)
            IntegrationAuditLog.objects.create(tenant=request.user.tenant,
                integration_config=row.source_run.sync_job.integration_config, actor=request.user,
                action='inventory_manual_sku_link', result=IntegrationAuditLog.Result.SUCCESS,
                masked_detail={'warehouse_id': row.warehouse_id, 'snapshot_id': row.id,
                               'before_sku_ids': before, 'after_sku_id': sku.id, 'updated_count': len(changed)})
        return success_response({'updated_count': len(changed), 'internal_sku_id': sku.id})


class ConfirmSerializer(serializers.Serializer):
    sku_id = serializers.IntegerField(min_value=1)
    expected_sku_ids = serializers.ListField(child=serializers.IntegerField(min_value=1))
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if value is not True or self.initial_data.get('confirmed') is not True:
            raise serializers.ValidationError('请明确确认该仓库 SKU 的关联。')
        return value
