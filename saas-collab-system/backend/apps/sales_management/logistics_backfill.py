"""One-off, audited logistics-only enrichment of a frozen settlement order set."""
import hashlib
import json
from datetime import date
from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import OperationLog
from apps.commerce.models import SalesOrder
from apps.finance.models import PlatformFinanceTransaction
from apps.integrations.shopee_logistics import safe_snapshot
from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission
from .scopes import filter_sales_queryset


def require_actor(actor):
    if not actor.is_active or not all(check_user_permission(actor, code) for code in (
            'integrations.run_live_readonly', 'integrations.manage', 'sales_management.orders.view')):
        raise PermissionDenied('物流快照补齐需要活动账户及相应接入管理、只读执行和订单查看权限。')


def business_hash(order):
    value = {field.attname: getattr(order, field.attname) for field in order._meta.concrete_fields
             if field.name != 'source_details'}
    value['items'] = [{field.attname: getattr(line, field.attname) for field in line._meta.concrete_fields}
                      for line in sorted(order.items.all(), key=lambda line: line.pk)]
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        default=lambda item: format(item.normalize(), 'f') if isinstance(item, Decimal) else str(item)).encode()).hexdigest()


def settlement_plan(actor, store_code, month):
    require_actor(actor)
    try:
        start = date.fromisoformat(month + '-01')
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    except (ValueError, TypeError):
        raise ValidationError('结算月份须为 YYYY-MM。') from None
    store = filter_sales_queryset(actor, 'sales_management.orders.view',
        StoreMaster.objects.filter(tenant=actor.tenant, code=store_code, platform__platform_type='shopee'),
        {'store_ids': 'id', 'platforms': 'platform__platform_type', 'regions': 'country_code'}).get()
    finance = PlatformFinanceTransaction.objects.filter(tenant=actor.tenant, store=store, platform='shopee',
        business_date__gte=start, business_date__lt=end).exclude(external_order_id='')
    ids = set(finance.order_by().values_list('external_order_id', flat=True).distinct())
    orders = filter_sales_queryset(actor, 'sales_management.orders.view',
        SalesOrder.objects.filter(tenant=actor.tenant, store=store, external_order_id__in=ids))
    rows = [{'id': order.id, 'external_order_id': order.external_order_id, 'business_hash': business_hash(order)}
            for order in orders.prefetch_related('items').order_by('id')]
    plan = {'store_id': store.id, 'store_code': store.code, 'month': month, 'finance_rows': finance.count(),
            'settled_orders': len(ids), 'missing_local_orders': len(ids) - len(rows), 'orders': rows}
    plan['scope_hash'] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return plan


def start_batch(actor, plan):
    require_actor(actor)
    # Rebuild before creating the manifest: no stale or caller-invented order set.
    if settlement_plan(actor, plan['store_code'], plan['month']) != plan:
        raise ValidationError('结算范围已变化，请重新核定。')
    return OperationLog.objects.create(tenant=actor.tenant, user=actor, module='sales_management',
        object_type='SalesOrderLogisticsBackfill', object_id=f"{plan['store_id']}:{plan['month']}",
        action='logistics_backfill_started', after_data=plan)


@transaction.atomic
def save_snapshot(actor, batch, external_order_id, snapshot, *, return_id=None):
    require_actor(actor)
    if (batch.tenant_id != actor.tenant_id or batch.user_id != actor.id
            or batch.action != 'logistics_backfill_started' or batch.object_type != 'SalesOrderLogisticsBackfill'):
        raise PermissionDenied('物流补齐批次不属于当前账户。')
    manifest = next((row for row in batch.after_data['orders'] if row['external_order_id'] == external_order_id), None)
    if manifest is None:
        raise ValidationError('订单不在已确认结算清单内。')
    if (snapshot.get('status') != 'ok' or snapshot.get('order_sn') != external_order_id
            or (return_id is not None and snapshot.get('return_sn') != return_id)):
        raise ValidationError('物流快照尚不完整或标识不一致，未覆盖本地快照。')
    order = filter_sales_queryset(actor, 'sales_management.orders.view', SalesOrder.objects.select_for_update().filter(
        tenant=actor.tenant, store_id=batch.after_data['store_id'], pk=manifest['id'],
        external_order_id=external_order_id)).prefetch_related('items').get()
    if business_hash(order) != manifest['business_hash']:
        raise ValidationError('订单业务字段已变化，未覆盖；请核对后重建批次。')
    details = dict(order.source_details or {})
    previous = (details.get('platform_return_logistics') or {}).get(return_id) if return_id else details.get('platform_logistics')
    if isinstance(previous, dict) and previous.get('source_operation_id'):
        prior = OperationLog.objects.filter(pk=previous['source_operation_id'], tenant=actor.tenant,
            action='logistics_snapshot_saved', after_data__batch_id=batch.pk, object_id=str(order.id)).exists()
        if prior:
            return 'already_saved'
    clean = safe_snapshot(snapshot)
    audit = OperationLog.objects.create(tenant=actor.tenant, user=actor, module='sales_management',
        object_type='SalesOrder', object_id=str(order.id), action='logistics_snapshot_saved',
        before_data={'snapshot': previous, 'business_hash': manifest['business_hash']},
        after_data={'batch_id': batch.id, 'return_id': return_id, 'snapshot': clean})
    clean['source_operation_id'] = audit.id
    if return_id:
        details['platform_return_logistics'] = {**(details.get('platform_return_logistics') or {}), return_id: clean}
    else:
        details['platform_logistics'] = clean
    order.source_details = details
    order.save(update_fields=['source_details'])
    return 'saved'
