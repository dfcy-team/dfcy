"""Local-only reconciliation. Platform refunds and warehouse inventory are never written."""
import calendar
from collections import Counter
from datetime import UTC
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.audit.models import OperationLog
from apps.commerce.models import RefundReturn, SalesOrder
from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes
from .aftersales_models import AftersalesCase, WarehouseReturnReceipt, WarehouseReturnLine, ReturnAllocation
from .scopes import filter_sales_queryset

READ = 'sales_management.returns.view'
MANAGE = 'sales_management.aftersales.manage'
RETURN_STATES = {'unknown', 'not_required', 'pending', 'partial', 'received', 'failed', 'cancelled'}


def calendar_deadline(value):
    local = value.astimezone(ZoneInfo('Asia/Shanghai'))
    year, month = divmod(local.year * 12 + local.month - 1 + 2, 12)
    month += 1
    return local.replace(year=year, month=month, day=min(local.day, calendar.monthrange(year, month)[1])).astimezone(UTC)


def visible_cases(user, permission=READ):
    return filter_sales_queryset(user, permission, AftersalesCase.objects.filter(tenant=user.tenant),
        {'store_ids': 'store_id', 'platforms': 'store__platform__platform_type', 'regions': 'store__country_code'})


def require_full_scope(user):
    scopes = get_permission_data_scopes(user, MANAGE)
    if not user.is_superuser and not any(row['scope_type'] == DataScope.ScopeType.ALL for row in scopes):
        raise PermissionDenied('未匹配回仓单尚无店铺归属，需要全部数据范围的订单售后管理权限。')


def audit(user, obj, action, before=None, after=None):
    OperationLog.objects.create(tenant_id=obj.tenant_id, user=user, module='sales_management',
        object_type=type(obj).__name__, object_id=str(obj.pk), action=action, before_data=before or {}, after_data=after or {})


def expected_skus(source):
    result = Counter()
    for line in source.items.select_related('internal_sku'):
        sku = line.internal_sku.sku_code if line.internal_sku_id else line.seller_sku
        if not sku or not line.quantity:
            return {}  # Incomplete evidence cannot prove that a whole order was returned.
        result[sku] += line.quantity
    return dict(result)


@transaction.atomic
def track_source(source, *, requires_return=None, from_warehouse=False):
    refund = isinstance(source, RefundReturn)
    if refund and source.normalized_status in {'cancelled', 'canceled'}:
        case = AftersalesCase.objects.select_for_update().filter(tenant_id=source.tenant_id, refund=source).first()
        if case is not None:
            case.refund = source
            refresh_case(case)
        return case
    if not refund and source.normalized_status != 'cancelled' and not from_warehouse:
        return None
    kind = 'refund' if refund else 'cancelled' if source.normalized_status == 'cancelled' else 'order'
    key = f'{kind}:{source.pk}'
    if kind == 'cancelled':
        # Preserve receipt links when a known warehouse return is followed by
        # a platform cancellation, rather than creating a second expected return.
        prior = AftersalesCase.objects.select_for_update().filter(
            tenant_id=source.tenant_id, source_key=f'order:{source.pk}').first()
        if prior and not AftersalesCase.objects.filter(tenant_id=source.tenant_id, source_key=key).exists():
            prior.source_key = key
            prior.version += 1
            prior.save(update_fields=['source_key', 'version'])
    case, created = AftersalesCase.objects.get_or_create(tenant_id=source.tenant_id, source_key=key,
        defaults={'store_id': source.store_id, 'order_id': source.sales_order_id if refund else source.pk,
                  'refund': source if refund else None})
    case = AftersalesCase.objects.select_for_update().get(pk=case.pk)
    before = (case.requires_return, case.expected_skus, case.order_id)
    required = source.requires_physical_return if refund else requires_return
    if required is None and not refund and source.shipment_records.filter(shipped_at_utc__isnull=False).exists():
        required = True
    # Unknown incoming evidence must not erase a reviewed local decision.
    if required is not None and not case.expectation_reviewed:
        case.requires_return = required
    case.order_id = source.sales_order_id if refund else source.pk
    if not case.expectation_reviewed:
        case.expected_skus = expected_skus(source)
    if not created and before != (case.requires_return, case.expected_skus, case.order_id):
        case.version += 1
    case.save()
    refresh_case(case)
    return case


def quantities(case):
    if hasattr(case, '_received_quantities'):
        return case._received_quantities
    return {row['case_sku']: row['quantity'] for row in case.allocations.values('case_sku').annotate(quantity=Sum('quantity'))}


def refresh_case(case, *, now=None):
    now = now or timezone.now()
    previous = case.return_status
    received = quantities(case)
    complete = bool(case.expected_skus) and all(received.get(sku, 0) >= count for sku, count in case.expected_skus.items())
    if case.refund_id and case.refund.normalized_status in {'cancelled', 'canceled'}:
        state = 'cancelled'
    elif case.requires_return is False:
        state = 'not_required'
    elif case.requires_return is None:
        state = 'unknown'
    else:
        if case.pending_since is None:
            case.pending_since = now
            case.due_at = calendar_deadline(now)
        if complete:
            state = 'received'
        elif case.due_at and now >= case.due_at:
            state = 'failed'
            case.timed_out_at = case.timed_out_at or now
        else:
            state = 'partial' if any(received.values()) else 'pending'
    case.return_status = state
    case.save(update_fields=['return_status', 'pending_since', 'due_at', 'timed_out_at', 'updated_at'])
    if previous != state:
        audit(None, case, 'return_state_changed', {'state': previous}, {'state': state})
    return case


def _quantity(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 0 <= int(value) <= 2147483647:
        raise ValidationError('实收数量须为非负整数。')
    return int(value)


def _text(value, *, required=False):
    if not isinstance(value, str) or len(value.strip()) > 191 or any(ord(char) < 32 for char in value):
        raise ValidationError('单号和 SKU 须为不超过191字的文本。')
    value = value.strip()
    if required and not value:
        raise ValidationError('退货单号和 SKU 不能为空。')
    return value


@transaction.atomic
def ingest_receipt(user, warehouse, value, *, auto_match=True, source='file'):
    if warehouse.tenant_id != user.tenant_id:
        raise ValidationError('仓库不属于当前租户。')
    require_full_scope(user)
    number = _text(value.get('return_no', ''), required=True)
    raw_time = value.get('received_at')
    try:
        received_at = parse_datetime(raw_time) if isinstance(raw_time, str) else raw_time
    except ValueError as exc:
        raise ValidationError('实际入库时间格式错误。') from exc
    if not received_at or timezone.is_naive(received_at) or received_at > timezone.now():
        raise ValidationError('实际入库时间须包含时区，且不能晚于当前时间。')
    lines = value.get('lines')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 1000:
        raise ValidationError('退货单需提供1至1000条实收商品明细。')
    counts = Counter()
    for line in lines:
        counts[_text(line.get('sku', ''), required=True)] += _quantity(line.get('received_quantity'))
    fields = {key: _text(value.get(key, '')) for key in ('platform_order_no', 'erp_no', 'tracking_no')}
    receipt, created = WarehouseReturnReceipt.objects.get_or_create(tenant=user.tenant, warehouse=warehouse,
        return_no=number, defaults={**fields, 'received_at': received_at, 'source': source,
                                    'provider_status': str(value.get('provider_status', ''))[:40]})
    receipt = WarehouseReturnReceipt.objects.select_for_update().get(pk=receipt.pk)
    existing = dict(receipt.lines.values_list('sku', 'received_quantity'))
    if not created and (any(getattr(receipt, key) != val for key, val in fields.items()) or
                        receipt.received_at != received_at or existing != dict(counts)):
        if source != 'api':
            raise ValidationError('同一仓库退货单已存在但内容不同，请核对，不覆盖已导入记录。')
        if any(existing_sku not in counts for existing_sku in existing):
            raise ValidationError('接口删除了已保存商品明细，需人工核对。')
        if any(getattr(receipt, key) and getattr(receipt, key) != val for key, val in fields.items()):
            raise ValidationError('接口更改了已保存单据归属标识，需人工核对。')
        for key, val in fields.items():
            setattr(receipt, key, val)
        receipt.received_at = received_at
        receipt.version += 1
        receipt.save()
    for sku, count in counts.items():
        line, line_created = WarehouseReturnLine.objects.get_or_create(receipt=receipt, sku=sku, defaults={'received_quantity': count})
        if not line_created and line.received_quantity != count:
            assigned = line.allocations.aggregate(count=Sum('quantity'))['count'] or 0
            if count < assigned:
                raise ValidationError('实收数量小于已分配数量，需先核对关联记录。')
            line.received_quantity = count
            line.save(update_fields=['received_quantity'])
    if created:
        audit(user, receipt, 'return_receipt_ingested', after={'source': source, 'lines': len(counts)})
    if auto_match:
        auto_allocate(user, receipt)
    receipt.refresh_from_db()
    return receipt, created


def auto_allocate(user, receipt):
    # Local facts may predate this feature. Materialize only sources identified
    # by this received document, never backfill the provider or invent refunds.
    if receipt.platform_order_no:
        orders = SalesOrder.objects.filter(tenant=user.tenant, store__country_code=receipt.warehouse.country_code,
                                         external_order_id=receipt.platform_order_no)
        if orders.count() == 1:
            order = orders.first()
            returns = order.refund_returns.filter(requires_physical_return=True)
            if returns.exists():
                for refund in returns:
                    track_source(refund)
            elif order.normalized_status == 'cancelled':
                # Actual returned goods are positive evidence that shipment occurred.
                track_source(order, requires_return=True)
            else:
                # The order is known, but a completed shipment alone does not
                # establish which quantities the customer was expected to return.
                track_source(order, from_warehouse=True)
    candidates = visible_cases(user, MANAGE).filter(store__country_code=receipt.warehouse.country_code,
        requires_return=True).exclude(refund__normalized_status__in=['cancelled', 'canceled']).filter(
            Q(warehouse__isnull=True) | Q(warehouse=receipt.warehouse))
    identifiers = []
    if receipt.platform_order_no:
        identifiers.append(set(candidates.filter(order__external_order_id=receipt.platform_order_no).values_list('pk', flat=True)))
    if receipt.tracking_no:
        tracking = set(candidates.filter(tracking_no=receipt.tracking_no).values_list('pk', flat=True))
        # An unrecognized extra identifier cannot contradict a unique order number;
        # a recognized conflicting identifier must never be ignored.
        if tracking or not identifiers:
            identifiers.append(tracking)
    if not identifiers:
        return
    common = set.intersection(*identifiers)
    if len(common) != 1:
        return
    case = candidates.get(pk=next(iter(common)))
    for line in receipt.lines.order_by('pk'):
        sku = line.sku
        if sku not in case.expected_skus or line.allocations.filter(Q(manual=True) | ~Q(case=case, case_sku=sku)).exists():
            continue
        assigned = line.allocations.aggregate(count=Sum('quantity'))['count'] or 0
        available = case.expected_skus[sku] - quantities(case).get(sku, 0)
        count = min(available, line.received_quantity - assigned)
        if count > 0:
            allocate_line(user, line.pk, case, sku, count, reason='唯一单号及明确 SKU 自动关联',
                          expected_version=receipt.version, manual=False)
            receipt.refresh_from_db()


@transaction.atomic
def allocate_line(user, line_id, case, sku, quantity, *, reason, expected_version, manual=True):
    require_full_scope(user)
    # A consistent receipt -> case -> allocation lock order covers splits across orders.
    line_ref = WarehouseReturnLine.objects.filter(pk=line_id, receipt__tenant=user.tenant).first()
    if line_ref is None:
        raise NotFound('回仓商品不在当前租户范围内。')
    receipt = WarehouseReturnReceipt.objects.select_for_update().get(pk=line_ref.receipt_id, tenant=user.tenant)
    case = visible_cases(user, MANAGE).select_for_update().filter(pk=case.pk).first()
    if case is None:
        raise NotFound('订单售后记录不在授权范围内。')
    if case.refund_id and case.refund.normalized_status in {'cancelled', 'canceled'}:
        raise ValidationError('已取消售后不能新增回仓分配；既有回仓凭据保留。')
    line = WarehouseReturnLine.objects.select_for_update().get(pk=line_id)
    if receipt.version != expected_version:
        raise ValidationError('回仓单已更新，请刷新后重试。')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValidationError('请填写不超过500字的关联原因。')
    count = _quantity(quantity)
    if not count or sku not in case.expected_skus or case.requires_return is not True:
        raise ValidationError('只能关联明确需要回仓的商品及正数数量。')
    if case.store.country_code != receipt.warehouse.country_code or (case.warehouse_id and case.warehouse_id != receipt.warehouse_id):
        raise ValidationError('退货仓库国家或预期仓库与订单不一致。')
    assigned = line.allocations.aggregate(count=Sum('quantity'))['count'] or 0
    case_assigned = quantities(case).get(sku, 0)
    if count + assigned > line.received_quantity or count + case_assigned > case.expected_skus[sku]:
        raise ValidationError('分配数量超过实收数量或订单尚需回仓数量。')
    allocation, created = ReturnAllocation.objects.get_or_create(line=line, case=case, case_sku=sku,
        defaults={'quantity': count, 'manual': manual, 'actor': user})
    if not created:
        allocation.quantity += count
        allocation.manual = allocation.manual or manual
        allocation.actor = user
        allocation.save(update_fields=['quantity', 'manual', 'actor'])
    receipt.version += 1
    receipt.save(update_fields=['version', 'updated_at'])
    case.version += 1
    case.save(update_fields=['version'])
    refresh_case(case)
    audit(user, case, 'return_allocated', after={'allocation_id': allocation.pk, 'line_id': line.pk,
                                               'sku': sku, 'quantity': count, 'manual': manual, 'reason': reason})
    return allocation


@transaction.atomic
def unlink_allocation(user, allocation_id, *, reason, expected_version):
    require_full_scope(user)
    allocation = ReturnAllocation.objects.select_related('line__receipt').filter(pk=allocation_id, case__tenant=user.tenant).first()
    if not allocation:
        raise NotFound('关联记录不存在。')
    receipt = WarehouseReturnReceipt.objects.select_for_update().get(pk=allocation.line.receipt_id)
    case = visible_cases(user, MANAGE).select_for_update().get(pk=allocation.case_id)
    if receipt.version != expected_version or not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValidationError('版本已变化或未填写解除原因，请刷新后核对。')
    audit(user, case, 'return_unlinked', before={'allocation_id': allocation.pk, 'line_id': allocation.line_id,
          'sku': allocation.case_sku, 'quantity': allocation.quantity}, after={'reason': reason})
    allocation.delete()  # Only the reversible association is removed; receipt and audit remain.
    receipt.version += 1
    receipt.save(update_fields=['version', 'updated_at'])
    case.version += 1
    case.save(update_fields=['version'])
    refresh_case(case)
