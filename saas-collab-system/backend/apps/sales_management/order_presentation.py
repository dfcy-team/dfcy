"""Read-only order presentation, without inferring missing business facts."""
import hashlib
from datetime import datetime
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware


def attach_event_milestones(tenant_id, rows):
    from django.db.models import Min, Max
    from apps.integrations.models import MarketplaceStoreAuthorization, WebhookEvent
    from .order_event_scope import shop_identity, milestone_filters
    shops = list(MarketplaceStoreAuthorization.objects.filter(tenant_id=tenant_id,
        store_id__in=[row['store']['id'] for row in rows])
        .values_list('store_id', 'platform', 'region', 'platform_store_id'))
    by_identity = {}
    for row in rows:
        for store_id, platform, region, shop_id in shops:
            if row['store']['id'] == store_id and row['platform'] == platform:
                by_identity[(platform, shop_identity(platform, region, shop_id), row['external_order_id'])] = row
    for event in WebhookEvent.objects.filter(tenant_id=tenant_id, signature_status='valid',
            external_shop_id__in=[identity[1] for identity in by_identity],
            external_order_id__in=[row['external_order_id'] for row in rows]).values(
                'platform', 'external_shop_id', 'external_order_id').annotate(**{
                    key + '_utc': (Max if key == 'cancel_requested_at' else Min)('event_at', filter=value)
                    for key, value in milestone_filters().items()}):
        row = by_identity.get((event['platform'], event['external_shop_id'], event['external_order_id']))
        if row is not None:
            for field in ('completed_at_utc', 'cancelled_at_utc', 'cancel_requested_at_utc'):
                if not row.get(field) and event[field]:
                    row[field] = event[field].isoformat()
                    row.setdefault('time_sources', {})[field] = 'verified_platform_push'


def factual_events(order, warehouse=None):
    events = {}

    def add(value, title, source, status=''):
        try:
            at = value if isinstance(value, datetime) else parse_datetime(value) if value else None
        except (TypeError, ValueError):
            return
        if at is None or not is_aware(at):
            return
        identity = hashlib.sha256(f'{at.isoformat()}|{title}|{source}|{status}'.encode()).hexdigest()
        events[identity] = dict(id=identity, event_at=at, title=title, source=source, status=status)

    add(order.created_at_utc, '订单创建', '平台订单')
    for field, title in [('paid_at_utc', '买家支付'), ('completed_at_utc', '订单完成'),
                         ('cancelled_at_utc', '订单取消')]:
        add(getattr(order, field, None), title, '平台订单')
    details = order.source_details or {}
    add(details.get('platform_pickup_at_utc'), '平台揽收', '平台订单')
    add(details.get('platform_shipped_at_utc'), '平台安排发货', '平台订单')
    add(details.get('platform_delivered_at_utc'), '平台妥投', '平台订单')
    snapshot = details.get('platform_logistics') or {}
    for package in snapshot.get('packages', []) if isinstance(snapshot, dict) else []:
        for event in package.get('events') or []:
            add(event.get('occurred_at_utc'), event.get('description') or '物流节点更新',
                '平台物流', event.get('status') or '')
    if warehouse and not warehouse.get('stale'):
        for package in warehouse.get('snapshot', {}).get('packages', []):
            identity = package.get('package_no') or package.get('warehouse_order_no') or ''
            add(package.get('shipped_at_utc'), '仓库发货', '仓库接口', identity)
            add(package.get('pickup_at_utc'), '仓库揽收', '仓库接口', identity)
    return list(events.values())
