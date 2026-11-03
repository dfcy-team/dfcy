"""Scoped order aftersales endpoints; GETs never synchronize or mutate business data."""
from django.db import transaction
from django.db.models import CharField, F, Q, Subquery, Value
from django.db.models.functions import Cast, Coalesce, Concat
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.views import APIView

from apps.commerce.models import RefundReturn, SalesOrder
from apps.common.responses import success_response
from apps.masterdata.models import StoreMaster, WarehouseMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from .aftersales import READ, MANAGE, RETURN_STATES, visible_cases, require_full_scope, track_source, refresh_case, quantities, audit
from .aftersales_models import AftersalesCase, WarehouseReturnLine, AftersalesSyncSettings
from .scopes import filter_sales_queryset


class AftersalesAPI(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = READ
    write_permission_code = MANAGE


def source_rows(request, permission=READ):
    from .views import _apply_dimensions
    orders = filter_sales_queryset(request.user, permission, SalesOrder.objects.filter(tenant=request.user.tenant))
    refunds = filter_sales_queryset(request.user, permission, RefundReturn.objects.filter(tenant=request.user.tenant),
        {'store_ids': 'store_id', 'platforms': 'platform__platform_type', 'regions': 'store__country_code'})
    orders = orders.annotate(source_at=Coalesce('cancelled_at_utc', 'updated_at_utc'))
    orders = _apply_dimensions(orders, request, date_field='source_at', region_field='store__country_code')
    refunds = _apply_dimensions(refunds, request, date_field='requested_at_utc', region_field='store__country_code')
    search = request.query_params.get('external_order_id', '').strip()
    if search:
        orders = orders.filter(external_order_id__icontains=search)
        refunds = refunds.filter(Q(sales_order__external_order_id__icontains=search) | Q(external_return_id__icontains=search))
    sku = request.query_params.get('sku', '').strip()
    if sku:
        orders = orders.filter(Q(items__seller_sku__icontains=sku) | Q(items__internal_sku__sku_code__icontains=sku)).distinct()
        refunds = refunds.filter(Q(items__seller_sku__icontains=sku) | Q(items__internal_sku__sku_code__icontains=sku)).distinct()
    if request.query_params.get('case_type'):
        case_type = request.query_params['case_type']
        refunds = refunds.filter(case_type=case_type)
        if case_type != 'cancelled':
            orders = orders.none()
    if request.query_params.get('platform_status'):
        orders = orders.filter(normalized_status=request.query_params['platform_status'])
        refunds = refunds.filter(normalized_status=request.query_params['platform_status'])
    return orders, refunds


def source_object(user, key, permission=READ):
    try:
        kind, pk = key.split(':')
        pk = int(pk)
    except (ValueError, TypeError):
        raise NotFound('售后来源标识无效。')
    if kind not in {'refund', 'cancelled', 'order'}:
        raise NotFound('售后来源不存在。')
    model = RefundReturn if kind == 'refund' else SalesOrder
    query = filter_sales_queryset(user, permission, model.objects.filter(tenant=user.tenant),
        {'store_ids': 'store_id', 'platforms': 'platform__platform_type', 'regions': 'store__country_code'})
    if kind == 'cancelled':
        query = query.filter(normalized_status='cancelled')
    if kind == 'order':
        query = query.exclude(normalized_status='cancelled')
    source = query.select_related('store__platform').filter(pk=pk).first()
    if source is None:
        raise NotFound('售后记录不在授权范围内。')
    return source


def case_data(case):
    received = quantities(case)
    state = case.return_status
    if (case.requires_return is True and state in {'pending', 'partial'} and case.due_at and timezone.now() >= case.due_at):
        state = 'failed'  # Read-time display is current; persistence belongs to the scheduler.
    return {'id': case.pk, 'version': case.version, 'requires_return': case.requires_return,
            'return_status': state, 'pending_since': case.pending_since, 'due_at': case.due_at,
            'timed_out_at': case.timed_out_at, 'tracking_no': case.tracking_no,
            'warehouse_id': case.warehouse_id,
            'lines': [{'sku': sku, 'expected': count, 'received': received.get(sku, 0),
                       'remaining': max(0, count - received.get(sku, 0))} for sku, count in case.expected_skus.items()]}


def source_data(source, case=None):
    refund = isinstance(source, RefundReturn)
    order = source.sales_order if refund else source
    required = source.requires_physical_return if refund else None
    tracking = case_data(case) if case else None
    kind = 'refund' if refund else 'cancelled' if source.normalized_status == 'cancelled' else 'order'
    return {'source_key': f'{kind}:{source.pk}',
            'source_type': 'refund_return' if refund else 'cancelled' if kind == 'cancelled' else 'warehouse_return',
            'external_order_id': order.external_order_id if order else '',
            'external_return_id': source.external_return_id if refund else '',
            'platform': source.store.platform.platform_type,
            'store': {'id': source.store_id, 'code': source.store.code, 'name': source.store.name},
            'country': source.store.country_code,
            'platform_status': source.normalized_status, 'case_type': source.case_type if refund else kind,
            'source_at': source.requested_at_utc if refund else (source.cancelled_at_utc or source.updated_at_utc),
            'refund_amount': str(source.refund_amount) if refund else None, 'currency': source.currency,
            'return_status': 'cancelled' if refund and source.normalized_status in {'cancelled', 'canceled'} else
                tracking['return_status'] if tracking else ('not_required' if required is False else 'unknown'),
            'tracking': tracking}


class AftersalesCollection(AftersalesAPI):
    def get(self, request):
        from .views import _pagination
        orders, refunds = source_rows(request)
        warehouse_orders = orders.exclude(normalized_status='cancelled').filter(pk__in=Subquery(visible_cases(request.user).filter(source_key__startswith='order:').values('order_id')))
        warehouse_orders = warehouse_orders.order_by().annotate(source_key=Concat(Value('order:'), Cast('pk', CharField())))
        orders = orders.filter(normalized_status='cancelled').order_by().annotate(
            source_key=Concat(Value('cancelled:'), Cast('pk', CharField())))
        refunds = refunds.order_by().annotate(source_key=Concat(Value('refund:'), Cast('pk', CharField())), source_at=F('requested_at_utc'))
        kind = request.query_params.get('source_type')
        if kind and kind not in {'refund_return', 'cancelled', 'warehouse_return'}:
            raise ValidationError('售后来源筛选无效。')
        if kind == 'refund_return':
            orders = orders.none()
            warehouse_orders = warehouse_orders.none()
        if kind == 'cancelled':
            refunds = refunds.none()
            warehouse_orders = warehouse_orders.none()
        if kind == 'warehouse_return':
            refunds, orders = refunds.none(), orders.none()
        state = request.query_params.get('return_status')
        if state:
            if state not in RETURN_STATES:
                raise ValidationError('回仓状态筛选无效。')
            keys = visible_cases(request.user).filter(return_status=state).values('source_key')
            if state == 'failed':
                keys = visible_cases(request.user).filter(Q(return_status=state) | Q(return_status__in=['pending', 'partial'], due_at__lte=timezone.now())).values('source_key')
            if state in {'pending', 'partial'}:
                keys = visible_cases(request.user).filter(return_status=state).filter(Q(due_at__isnull=True) | Q(due_at__gt=timezone.now())).values('source_key')
            known = visible_cases(request.user).values('source_key')
            if state != 'cancelled':
                refunds = refunds.exclude(normalized_status__in=['cancelled', 'canceled'])
            order_condition, refund_condition = Q(source_key__in=Subquery(keys)), Q(source_key__in=Subquery(keys))
            if state == 'unknown':
                order_condition |= ~Q(source_key__in=Subquery(known))
                refund_condition |= ~Q(source_key__in=Subquery(known)) & ~Q(requires_physical_return=False)
            if state == 'not_required':
                refund_condition |= ~Q(source_key__in=Subquery(known)) & Q(requires_physical_return=False)
            if state == 'cancelled':
                refund_condition |= Q(normalized_status__in=['cancelled', 'canceled'])
            orders, refunds = orders.filter(order_condition), refunds.filter(refund_condition)
            warehouse_orders = warehouse_orders.filter(source_key__in=Subquery(keys))
        combined = refunds.values('source_key', 'source_at').union(orders.values('source_key', 'source_at'), warehouse_orders.values('source_key', 'source_at'), all=True).order_by('-source_at', 'source_key')
        page, size = _pagination(request)
        count = combined.count()
        entries = list(combined[(page - 1) * size:page * size])
        case_map = {item.source_key: item for item in visible_cases(request.user).filter(source_key__in=[row['source_key'] for row in entries]).prefetch_related('allocations')}
        for case in case_map.values():
            received = {}
            for allocation in case.allocations.all():
                received[allocation.case_sku] = received.get(allocation.case_sku, 0) + allocation.quantity
            case._received_quantities = received
        order_ids = [int(row['source_key'].split(':')[1]) for row in entries if not row['source_key'].startswith('refund:')]
        refund_ids = [int(row['source_key'].split(':')[1]) for row in entries if row['source_key'].startswith('refund:')]
        sources = {f'cancelled:{obj.pk}': obj for obj in orders.filter(pk__in=order_ids).select_related('store__platform')}
        sources.update({f'order:{obj.pk}': obj for obj in warehouse_orders.filter(pk__in=order_ids).select_related('store__platform')})
        sources.update({f'refund:{obj.pk}': obj for obj in refunds.filter(pk__in=refund_ids).select_related('store__platform', 'sales_order')})
        return success_response({'count': count, 'results': [source_data(sources[row['source_key']], case_map.get(row['source_key'])) for row in entries]})


class AftersalesOptions(AftersalesAPI):
    def get(self, request):
        stores = filter_sales_queryset(request.user, READ, StoreMaster.objects.filter(tenant=request.user.tenant),
            {'store_ids': 'pk', 'platforms': 'platform__platform_type', 'regions': 'country_code'})
        return success_response({'stores': list(stores.values('id', 'code', 'name', 'country_code', 'currency', platform_type=F('platform__platform_type')))})


class MatchingOrders(AftersalesAPI):
    def get(self, request):
        require_full_scope(request.user)
        search = request.query_params.get('external_order_id', '').strip()
        if len(search) < 3:
            raise ValidationError('请至少输入3位平台订单号，不按商品名称猜测匹配。')
        orders = filter_sales_queryset(request.user, MANAGE, SalesOrder.objects.filter(tenant=request.user.tenant))
        from django.db.models import Prefetch
        orders = orders.filter(external_order_id__icontains=search).select_related('store__platform').prefetch_related(
            Prefetch('refund_returns', queryset=RefundReturn.objects.select_related('store__platform', 'sales_order'))).order_by('pk')[:21]
        result = []
        for order in orders[:20]:
            refunds = list(order.refund_returns.all())
            # Select the actual aftersales case rather than inventing a second
            # whole-order return beside an existing partial-return request.
            if refunds:
                result.extend(source_data(item) for item in refunds)
            else:
                result.append(source_data(order))
        return success_response({'results': result, 'refine_search': len(orders) > 20})


class CaseInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=0)
    requires_return = serializers.BooleanField(allow_null=True)
    expected_skus = serializers.DictField(child=serializers.IntegerField(min_value=1, max_value=2147483647))
    tracking_no = serializers.CharField(max_length=191, allow_blank=True, default='')
    warehouse_id = serializers.IntegerField(min_value=1, allow_null=True, default=None)
    reason = serializers.CharField(max_length=500)

    def validate(self, value):
        if value['requires_return'] is True and not value['expected_skus']:
            raise ValidationError('需要回仓时请明确应退商品和数量。')
        return value

    def validate_expected_skus(self, value):
        if len(value) > 1000 or any(not key.strip() or len(key) > 191 for key in value):
            raise ValidationError('商品 SKU 不完整或明细超过1000行。')
        return value


def checked(serializer_class, data):
    serializer = serializer_class(data=data)
    if set(data) - set(serializer.fields):
        raise ValidationError('请求包含不支持的字段。')
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class AftersalesDetail(AftersalesAPI):
    def get(self, request, source_key):
        source = source_object(request.user, source_key)
        case = visible_cases(request.user).filter(source_key=source_key).first()
        result = source_data(source, case)
        from .aftersales import expected_skus
        result['expected_skus'] = case.expected_skus if case else expected_skus(source)
        if isinstance(source, RefundReturn):
            from .serializers import SalesReturnSerializer
            result['platform_record'] = SalesReturnSerializer(source).data
        result['history'] = []
        if case:
            from apps.audit.models import OperationLog
            result['history'] = list(OperationLog.objects.filter(tenant=request.user.tenant, object_type='AftersalesCase', object_id=str(case.pk))
                .values('action', 'before_data', 'after_data', 'created_at', 'user_id')[:50])
        return success_response(result)

    @transaction.atomic
    def patch(self, request, source_key):
        value = checked(CaseInput, request.data)
        source = source_object(request.user, source_key, MANAGE)
        if isinstance(source, RefundReturn) and source.normalized_status in {'cancelled', 'canceled'}:
            raise ValidationError('已取消售后不能重新生成应退任务；既有回仓凭据保留。')
        existing = visible_cases(request.user, MANAGE).select_for_update().filter(source_key=source_key).first()
        if (existing.version if existing else 0) != value['expected_version']:
            raise ValidationError('售后记录已变化，请刷新后核对。')
        case = existing or track_source(source, from_warehouse=True)
        if existing is None and case.version != 1:
            raise ValidationError('售后记录已被其他操作更新，请刷新后核对。')
        before = case_data(case)
        assigned = quantities(case)
        if assigned and (value['requires_return'] is not True or any(value['expected_skus'].get(sku, 0) < count for sku, count in assigned.items())):
            raise ValidationError('应退数量不能小于已关联实收数量；请先核对或解除关联。')
        case.requires_return = value['requires_return']
        case.expectation_reviewed = True
        case.expected_skus = value['expected_skus']
        case.tracking_no = value['tracking_no']
        if value['warehouse_id']:
            warehouse = WarehouseMaster.objects.filter(pk=value['warehouse_id'], tenant=request.user.tenant,
                                                      country_code=source.store.country_code).first()
            if not warehouse:
                raise ValidationError('预期回仓仓库须属于当前租户及订单国家。')
        case.warehouse_id = value['warehouse_id']
        case.version += 1
        case.save()
        refresh_case(case)
        # Timestamps are ISO strings in persisted JSON audit data.
        from django.core.serializers.json import DjangoJSONEncoder
        import json
        audit(request.user, case, 'return_expectation_reviewed', json.loads(json.dumps(before, cls=DjangoJSONEncoder)),
              {'requires_return': case.requires_return, 'expected_skus': case.expected_skus, 'reason': value['reason']})
        return success_response(source_data(source, case))


class ReceiptCollection(AftersalesAPI):
    def get(self, request):
        from .views import _pagination
        require_full_scope(request.user)
        from django.db.models import Sum
        rows = WarehouseReturnLine.objects.filter(receipt__tenant=request.user.tenant).select_related('receipt__warehouse').prefetch_related('allocations__case')
        rows = rows.annotate(assigned=Coalesce(Sum('allocations__quantity'), 0))
        if request.query_params.get('unmatched', 'true') == 'true':
            rows = rows.filter(received_quantity__gt=F('assigned'))
        search = request.query_params.get('search', '').strip()
        if search:
            rows = rows.filter(Q(receipt__platform_order_no__icontains=search) | Q(receipt__return_no__icontains=search) | Q(receipt__tracking_no__icontains=search))
        page, size = _pagination(request)
        count = rows.count()
        result = []
        for row in rows.order_by('-receipt__received_at', '-pk')[(page - 1) * size:page * size]:
            receipt = row.receipt
            result.append({'id': row.pk, 'return_no': receipt.return_no, 'version': receipt.version,
                'warehouse': {'code': receipt.warehouse.code, 'name': receipt.warehouse.name},
                'platform_order_no': receipt.platform_order_no, 'tracking_no': receipt.tracking_no, 'received_at': receipt.received_at,
                'sku': row.sku, 'received_quantity': row.received_quantity, 'remaining_quantity': row.received_quantity - row.assigned,
                'allocations': [{'id': item.pk, 'source_key': item.case.source_key, 'sku': item.case_sku, 'quantity': item.quantity} for item in row.allocations.all()]})
        return success_response({'count': count, 'results': result})


class AllocationInput(serializers.Serializer):
    source_key = serializers.CharField(max_length=80)
    sku = serializers.CharField(max_length=191)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500)


class ReceiptAllocation(AftersalesAPI):
    def post(self, request, pk):
        from .aftersales import allocate_line
        value = checked(AllocationInput, request.data)
        source = source_object(request.user, value.pop('source_key'), MANAGE)
        if isinstance(source, RefundReturn) and source.normalized_status in {'cancelled', 'canceled'}:
            raise ValidationError('已取消售后不能新增回仓分配；既有回仓凭据保留。')
        kind = 'refund' if isinstance(source, RefundReturn) else 'cancelled' if source.normalized_status == 'cancelled' else 'order'
        case = visible_cases(request.user, MANAGE).filter(source_key=f'{kind}:{source.pk}').first()
        case = case or track_source(source, from_warehouse=True)
        result = allocate_line(request.user, pk, case, value.pop('sku'), value.pop('quantity'), **value)
        return success_response({'id': result.pk})


class UnlinkInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500)


class ReceiptUnlink(AftersalesAPI):
    def post(self, request, pk):
        from .aftersales import unlink_allocation
        unlink_allocation(request.user, pk, **checked(UnlinkInput, request.data))
        return success_response({'unlinked': True})


class SettingsInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=0)
    interval_minutes = serializers.IntegerField(min_value=5, max_value=10080)
    is_enabled = serializers.BooleanField()


def settings_data(row):
    return {'version': row.version if row else 0, 'interval_minutes': row.interval_minutes if row else 60,
            'is_enabled': row.is_enabled if row else False, 'warehouse_bound': bool(row and row.authorization_id),
            'last_run_at': row.last_run_at if row else None, 'last_error_code': row.last_error_code if row else '',
            'next_run_at': row.next_run_at if row else None, 'historical_backfill': False,
            'query_path': '/api/inbound/return/getSingle'}


class AftersalesSettings(AftersalesAPI):
    def get(self, request):
        require_full_scope(request.user)
        return success_response(settings_data(AftersalesSyncSettings.objects.filter(tenant=request.user.tenant).first()))

    @transaction.atomic
    def patch(self, request):
        require_full_scope(request.user)
        value = checked(SettingsInput, request.data)
        row, _ = AftersalesSyncSettings.objects.select_for_update().get_or_create(
            tenant=request.user.tenant, defaults={'version': 0})
        if row.version != value['expected_version']:
            raise ValidationError('同步配置已更新，请刷新后重试。')
        if value['is_enabled'] and (not row or not row.authorization_id):
            raise ValidationError('尚未绑定仓库，仅能保存周期，不能启用真实同步。')
        row.interval_minutes, row.is_enabled = value['interval_minutes'], value['is_enabled']
        from datetime import timedelta
        row.next_run_at = timezone.now() + timedelta(minutes=row.interval_minutes) if row.is_enabled else None
        row.requested_by = request.user
        row.version += 1
        row.save()
        audit(request.user, row, 'return_sync_configured', after={'interval_minutes': row.interval_minutes, 'is_enabled': row.is_enabled})
        return success_response(settings_data(row))


class AftersalesSync(AftersalesAPI):
    def post(self, request):
        require_full_scope(request.user)
        row = AftersalesSyncSettings.objects.filter(tenant=request.user.tenant).first()
        if not row or not row.authorization_id:
            raise ValidationError('尚未绑定仓库；接口已接入，当前不会调用仓库或补采历史。')
        from .tasks import synchronize_aftersales
        synchronize_aftersales.apply_async(args=[row.pk], queue='sync', retry=False)
        return success_response({'queued': True, 'completed': False})


class ReceiptImport(AftersalesAPI):
    def get(self, request):
        require_full_scope(request.user)
        return success_response({'warehouses': list(WarehouseMaster.objects.filter(tenant=request.user.tenant)
                                                   .values('id', 'code', 'name', 'country_code'))})

    def post(self, request):
        from .aftersales_import import prepare_import, commit_import
        operation = request.data.get('operation')
        if operation not in {'preview', 'confirm'}:
            raise ValidationError('请先预览再确认导入。')
        prepared, summary = prepare_import(request.user, request.FILES.get('file'))
        if operation == 'preview':
            return success_response({**summary, 'imported': False})
        if request.data.get('sha256') != summary['sha256']:
            raise ValidationError('文件与预览不一致，请重新预览。')
        return success_response({**commit_import(request.user, prepared), 'imported': True})


class ReceiptTemplate(AftersalesAPI):
    def get(self, request):
        require_full_scope(request.user)
        import csv
        from io import StringIO
        from django.http import HttpResponse
        from .aftersales_import import HEADERS
        output = StringIO()
        csv.writer(output).writerow(HEADERS)
        response = HttpResponse('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="warehouse-return-template.csv"'
        return response
