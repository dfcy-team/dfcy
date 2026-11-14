"""Durable, read-only warehouse enrichment. Never updates order/financial facts."""
from datetime import timedelta, timezone as dt_timezone
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.commerce.models import SalesOrder
from apps.integrations.models import WarehouseAuthorization
from apps.integrations.warehouse_api_service import execute_operation
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .scopes import filter_sales_queryset
from .warehouse_order_models import OrderWarehouseLookup
from .warehouse_order_policy import fingerprint, unpaid, next_refresh


LABELS = {'pending': '等待查询', 'running': '查询中', 'matched': '已关联仓库',
          'not_found': '仓库未查到', 'conflict': '多个仓库匹配', 'partial': '查询未完成',
          'blocked': '查询条件未就绪', 'failed': '查询失败', 'not_requested': '尚未查询', 'deferred': '待付款，暂缓查询'}


def require_access(actor, order):
    if (not actor or not actor.is_active or actor.tenant_id != order.tenant_id or
            not all(check_user_permission(actor, code) for code in (
                'sales_management.orders.view', 'integrations.run_live_readonly', 'integrations.warehouse.view')) or
            not filter_sales_queryset(actor, 'sales_management.orders.view',
                                      SalesOrder.objects.filter(pk=order.pk, tenant_id=actor.tenant_id)).exists()):
        raise PermissionDenied('需要订单查看、仓库查看及只读查询权限，且订单须在可见范围内。')


def publish_lookup(pk, revision):
    from .tasks import synchronize_order_warehouse
    try:
        synchronize_order_warehouse.apply_async(args=[pk, str(revision)], queue='warehouse-orders', retry=False)
    except Exception:
        # The durable pending record survives broker failure; the dispatcher retries delivery.
        OrderWarehouseLookup.objects.filter(pk=pk, revision=revision, status='pending').update(
            message='任务尚未送达后台队列；等待调度恢复，也可稍后重试。')


@transaction.atomic
def request_lookup(order_id, actor=None, *, manual=False, scheduled=False):
    order = SalesOrder.objects.select_for_update().select_related('authorization__created_by').get(pk=order_id)
    if manual:
        require_access(actor, order)
    elif not scheduled and order.authorization_id:
        actor = order.authorization.created_by
    elif not scheduled and order.internal_sync_batch_id:
        actor = order.internal_sync_batch.source.created_by
    status = fingerprint(order)
    now = timezone.now()
    if not manual and unpaid(order):
        row = OrderWarehouseLookup.objects.select_for_update().filter(order=order).first()
        if row:
            row.next_query_at, row.polling_until = None, None
            if row.status in {'pending', 'running'}:
                row.status, row.revision = 'deferred', uuid.uuid4()
                row.lease, row.lease_until, row.followup_required = None, None, False
            row.save()
        return row
    row, created = OrderWarehouseLookup.objects.select_for_update().get_or_create(order=order)
    if scheduled and (not row.next_query_at or row.next_query_at > now):
        return row
    changed = row.order_status != status
    if row.status == 'running' and row.lease_until and row.lease_until > now:
        if changed:
            row.order_status, row.followup_required = status, True
            row.polling_until = now + timedelta(days=7)
            row.retry_count = 0
            row.save(update_fields=['order_status', 'followup_required', 'polling_until', 'retry_count'])
        return row
    if not created and not changed and not scheduled:
        if not manual or row.status == 'pending':
            return row
    if not scheduled:
        row.polling_until, row.retry_count = now + timedelta(days=7), 0
    row.next_query_at, row.followup_required = None, False

    row.revision = uuid.uuid4()
    row.order_status = status
    row.requested_by = actor if actor and actor.tenant_id == order.tenant_id else None
    row.status, row.message, row.checks = 'pending', '', []
    row.lease, row.lease_until = None, None
    row.requested_at = timezone.now()
    row.save()
    transaction.on_commit(lambda: publish_lookup(row.pk, row.revision), robust=True)
    return row


def utc_time(value):
    if value in (None, ''):
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValidationError('仓库返回的时间格式无效。')
    # Jifeng documents shippedTime as UTC, even when the offset is omitted.
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc).isoformat()


def jifeng_package(data):
    fields = {'warehouse_order_no': 'orderNo', 'erp_no': 'erpNo', 'tracking_no': 'trackingNo',
              'carrier': 'carrier', 'status': 'status'}
    package = {key: data[source] for key, source in fields.items() if source in data}
    if any(value is not None and not isinstance(value, (str, int)) for value in package.values()):
        raise ValidationError('仓库单号或状态格式无效。')
    # Jifeng /api/order/get: status is the warehouse document state.
    package['status_label'] = {'1': '待移货', '2': '待生成', '3': '待拣货', '4': '待包装',
        '5': '包装中', '6': '待发货', '7': '已发货', '8': '异常', '9': '已取消',
        '10': '获取中', '11': '获取失败'}.get(str(data.get('status')), '未提供或未知状态')
    if 'shippedTime' in data:
        package['shipped_at_utc'] = utc_time(data['shippedTime'])
    items = data.get('skuList')
    if items is not None:
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValidationError('仓库商品明细格式无效。')
        package['items'] = [{key: item[source] for key, source in (
            ('sku', 'sku'), ('warehouse_sku', 'skuNo'), ('quantity', 'num'), ('name', 'platformProductName'))
            if source in item and isinstance(item[source], (str, int, float))} for item in items]
    return package


def fetch_packages(actor, authorization, order, is_current):
    if authorization.provider == 'best_ecapi':
        from .best_warehouse_orders import fetch_packages as fetch_best_packages
        return fetch_best_packages(actor, authorization, order, is_current)
    if authorization.provider != 'jifeng_wms':
        raise ValidationError('该仓库平台的订单查询字段尚未完成适配。')
    # The live API rejects time ranges longer than half a year (10035).
    # Start around platform creation and include later warehouse processing.
    start = order.created_at_utc.astimezone(dt_timezone.utc).replace(microsecond=0) - timedelta(days=1)
    finish = timezone.now().astimezone(dt_timezone.utc).replace(microsecond=0)
    if start > finish:
        raise ValidationError('订单创建时间晚于当前时间，无法确定仓库查询范围。')
    packages, identities = [], set()
    while start <= finish:
        end = min(start + timedelta(days=180) - timedelta(seconds=1), finish)
        for package in _fetch_packages_window(actor, authorization, order, is_current, start, end):
            identity = package.get('erp_no') or package.get('warehouse_order_no')
            if identity in identities:
                raise ValidationError('仓库包裹跨时间分段重复，请核查。')
            identities.add(identity)
            packages.append(package)
        start = end + timedelta(seconds=1)
    return packages


def _fetch_packages_window(actor, authorization, order, is_current, start, end):
    packages, seen, total = [], set(), None
    for page in range(1, 101):
        if not is_current():
            raise ValidationError('订单已变化，本次查询停止。')
        actor.refresh_from_db()
        require_access(actor, order)
        authorization.refresh_from_db()
        # Load fresh related configuration, so revoked bindings/permissions cannot be reused.
        authorization = WarehouseAuthorization.objects.select_related('warehouse', 'integration_config').get(pk=authorization.pk)
        if not authorization.oauth_expires_at or authorization.oauth_expires_at <= timezone.now():
            raise PermissionDenied('仓库令牌已过期或缺少有效期，请刷新仓库授权后重试。',
                                   code='warehouse_token_expired')
        if authorization.warehouse.country_code.upper() != order.store.country_code.upper():
            raise ValidationError('仓库国家与订单店铺国家不一致。')
        if not integration_values_allowed(actor, 'integrations.warehouse.view', platform=authorization.provider,
                environment=authorization.integration_config.environment, regions=[authorization.external_warehouse_region],
                config_id=authorization.integration_config_id, warehouse_id=authorization.warehouse_id):
            raise PermissionDenied('仓库不在当前账户查看范围内。')
        result = execute_operation(actor=actor, authorization=authorization, name='order_page', payload={
            'platformOrderNo': order.external_order_id, 'pageNo': page, 'pageSize': 300,
            'beginTime': start.strftime('%Y-%m-%d %H:%M:%S'),
            'endTime': end.strftime('%Y-%m-%d %H:%M:%S')})
        data = result.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('rows'), list):
            raise ValidationError('仓库分页结果不完整。')
        if (not isinstance(data.get('totalSize'), int) or data['totalSize'] < 0 or
                not isinstance(data.get('totalPage'), int) or data['totalPage'] < 0 or
                data.get('pageNo') != page):
            raise ValidationError('仓库分页计数不完整。')
        if total is None:
            total = data['totalSize']
        elif total != data['totalSize']:
            raise ValidationError('查询期间仓库订单数量变化，请重试。')
        for item in data['rows']:
            if not isinstance(item, dict) or item.get('platformOrderNo') != order.external_order_id:
                raise ValidationError('仓库响应订单号不一致。')
            # A customer credential can see more than one warehouse. Never attach another warehouse's record.
            if not isinstance(item.get('warehouse'), str) or not item['warehouse']:
                raise ValidationError('仓库响应缺少仓库编码。')
            key = item.get('erpNo') or item.get('orderNo')
            if not isinstance(key, str) or not key or key in seen:
                raise ValidationError('仓库包裹标识缺失或分页重复。')
            seen.add(key)
            if item['warehouse'] == authorization.external_warehouse_code:
                packages.append(jifeng_package(item))
        if page >= data['totalPage']:
            if len(seen) != total:
                raise ValidationError('仓库分页条数不一致。')
            return packages
        if not data['rows']:
            raise ValidationError('仓库分页提前结束。')
    raise ValidationError('仓库返回页数超过单订单查询上限，需核查。')


def synchronize(pk, revision):
    with transaction.atomic():
        row = OrderWarehouseLookup.objects.select_for_update().get(pk=pk)
        now = timezone.now()
        if str(row.revision) != str(revision) or row.status not in {'pending', 'running'}:
            return 'superseded'
        if row.status == 'running' and row.lease_until and row.lease_until > now:
            return 'already_running'
        row.status, row.lease, row.lease_until = 'running', uuid.uuid4(), now + timedelta(minutes=10)
        row.save(update_fields=['status', 'lease', 'lease_until'])
        lease, order, actor = row.lease, row.order, row.requested_by

    current = lambda: OrderWarehouseLookup.objects.filter(pk=pk, revision=revision, lease=lease).exists()
    checks, matches, state, message = [], [], 'failed', '仓库查询失败，请稍后重试。'
    try:
        require_access(actor, order)
        country = (order.store.country_code or '').upper()
        if not country:
            raise PermissionDenied('订单店铺未配置国家，无法确定仓库查询范围。')
        candidates = WarehouseAuthorization.objects.filter(tenant_id=order.tenant_id, status='active',
            warehouse__tenant_id=order.tenant_id, warehouse__status='active',
            warehouse__country_code__iexact=country).select_related('warehouse', 'integration_config')
        if row.warehouse_id:
            candidates = candidates.filter(warehouse_id=row.warehouse_id)
        candidates = list(candidates.order_by('warehouse_id', 'pk'))
        if not candidates:
            raise PermissionDenied('该国家暂无可用仓库授权，或原关联仓库授权已失效。')
        for authorization in candidates:
            if not current():
                return 'superseded'
            check = {'warehouse_id': authorization.warehouse_id, 'warehouse': authorization.warehouse.code,
                     'authorization_id': authorization.pk}
            try:
                packages = fetch_packages(actor, authorization, order, current)
                check['status'] = 'matched' if packages else 'not_found'
                if packages:
                    matches.append((authorization, packages))
            except PermissionDenied as exc:
                check.update(status='blocked', message=(
                    '仓库令牌已过期或缺少有效期，请刷新仓库授权后重试。'
                    if exc.get_codes() == 'warehouse_token_expired'
                    else '仓库授权、只读权限或网络审批未就绪，请检查接入配置。'))
            except ValidationError:
                # Only locally controlled validation messages are persisted, never upstream bodies or tokens.
                check.update(status='failed', message=('该仓库平台的订单查询尚未适配。'
                    if authorization.provider not in {'jifeng_wms', 'best_ecapi'} else '接口响应未通过订单、包裹或分页完整性核对。'))
            except Exception:
                check.update(status='failed', message='仓库查询异常，请稍后重试。')
            checks.append(check)
        if len(matches) > 1:
            state, message = 'conflict', '多个仓库返回该订单，未自动关联。'
        elif any(check['status'] in {'blocked', 'failed'} for check in checks):
            state, message = 'partial', '部分仓库未完成查询，暂不能确认唯一匹配；原有快照保留。'
        elif matches:
            state, message = 'matched', '已唯一匹配仓库，包裹明细按接口返回保存。'
        else:
            state, message = 'not_found', '本次未查到匹配订单，不代表订单未发货。'
    except PermissionDenied:
        state, message = 'blocked', '订单查询权限、店铺国家或仓库授权未就绪，请检查后重试。'
    except Exception:
        pass
    changes = dict(status=state, message=message, checks=checks, checked_at=timezone.now(), lease=None, lease_until=None)
    if state == 'matched':
        authorization, packages = matches[0]
        warehouse = authorization.warehouse
        changes.update(warehouse=warehouse, snapshot={'authorization_id': authorization.pk, 'warehouse_code': warehouse.code,
            'warehouse_name': warehouse.name, 'packages': packages}, snapshot_at=timezone.now())
    with transaction.atomic():
        latest = OrderWarehouseLookup.objects.select_for_update().get(pk=pk)
        if str(latest.revision) != str(revision) or latest.lease != lease:
            return 'superseded'
        if latest.followup_required:
            latest.status, latest.revision = 'pending', uuid.uuid4()
            latest.lease, latest.lease_until, latest.next_query_at = None, None, None
            latest.followup_required = False
            latest.save()
            transaction.on_commit(lambda: publish_lookup(pk, latest.revision), robust=True)
            return 'superseded'
        order.refresh_from_db()
        changes['next_query_at'], changes['retry_count'] = next_refresh(latest, order, state, checks, matches[0][1] if state == 'matched' else [])
        OrderWarehouseLookup.objects.filter(pk=pk).update(**changes)
        if state == 'matched':
            from .aftersales import track_source
            from apps.commerce.models import RefundReturn
            track_source(order)
            for refund in RefundReturn.objects.filter(tenant_id=order.tenant_id, sales_order=order):
                track_source(refund)
    return state



def lookup_data(order):
    if not getattr(settings, 'SALES_ORDER_WAREHOUSE_SYNC_ENABLED', False):
        return {'status': 'disabled', 'status_label': '自动查询未启用', 'message': '仓库查询功能尚未启用。'}
    row = OrderWarehouseLookup.objects.filter(order_id=order.pk).first()
    if row is None:
        return {'status': 'not_requested', 'status_label': LABELS['not_requested'],
                'message': '首次同步或状态变化后查询；历史订单未自动补采。'}
    return {'status': row.status, 'status_label': LABELS.get(row.status, row.status), 'message': row.message,
            'snapshot': row.snapshot, 'checks': row.checks, 'checked_at': row.checked_at,
            'snapshot_at': row.snapshot_at, 'requested_at': row.requested_at,
            'next_query_at': row.next_query_at, 'retry_count': row.retry_count,
            'stale': bool(row.snapshot) and row.status != 'matched'}


def scheduled_ready(row):
    """Recheck local approvals without calling the warehouse while blocked."""
    try:
        from apps.integrations.warehouse_api_service import execution_gate
        from apps.integrations.warehouse_api_contract import operation_for
        from apps.integrations.warehouse_credential_service import require_verified_warehouse
        from apps.integrations.readonly_clients import JifengWmsReadonlyClient
        order, actor = row.order, row.requested_by
        require_access(actor, order)
        execution_gate(operation_for('order_page'))
        candidates = WarehouseAuthorization.objects.filter(tenant_id=order.tenant_id, status='active',
            warehouse__tenant_id=order.tenant_id, warehouse__status='active',
            warehouse__country_code__iexact=order.store.country_code).select_related('warehouse', 'integration_config')
        if row.warehouse_id:
            candidates = candidates.filter(warehouse_id=row.warehouse_id)
        candidates = list(candidates)
        if not candidates or not order.store.country_code:
            return False
        for auth in candidates:
            if auth.provider not in {'jifeng_wms', 'best_ecapi'}:
                return False
            if auth.provider == 'jifeng_wms' and (not auth.oauth_expires_at or auth.oauth_expires_at <= timezone.now()):
                return False
            for code in ('integrations.warehouse.view', 'integrations.run_live_readonly'):
                if not integration_values_allowed(actor, code, platform=auth.provider,
                        environment=auth.integration_config.environment, regions=[auth.external_warehouse_region],
                        config_id=auth.integration_config_id, warehouse_id=auth.warehouse_id):
                    return False
            require_verified_warehouse(auth)
            if auth.provider == 'best_ecapi':
                from apps.integrations.best_ecapi import BestEcapiClient
                BestEcapiClient(auth.integration_config, auth).preflight()
            else:
                JifengWmsReadonlyClient(auth.integration_config, auth).preflight()
        return True
    except Exception:
        return False
