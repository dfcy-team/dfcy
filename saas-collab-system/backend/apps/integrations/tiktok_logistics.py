"""Official order tracking with a conservative eight-hour request interval."""
import hashlib
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache.backends.redis import RedisCache
from rest_framework.exceptions import ValidationError

from .order_field_mapping import text


INTERVAL = 8 * 60 * 60
TRACKING_PATH = '/fulfillment/202309/orders/{order_id}/tracking'


def _tracking_cache():
    # Use the existing shared Redis, not Django's process-local default cache.
    # A cache failure must stop the request rather than bypass rate protection.
    return RedisCache(settings.CELERY_BROKER_URL, {})


def collect_order_logistics(client, record):
    order_id = text(record.get('id'), 191)
    if not order_id.isascii() or not order_id.isdecimal():
        raise ValidationError('TikTok tracking order identity is invalid.')
    identity = f'{client.config.tenant_id}:{client.authorization.pk}:{order_id}'
    key = 'tk-order-tracking:' + hashlib.sha256(identity.encode()).hexdigest()
    cache = _tracking_cache()
    # Older snapshots predate required-event validation. Keep their request
    # reservation, but never reuse an unvalidated success snapshot.
    snapshot_key = key + ':validated-v2'
    cached = cache.get(snapshot_key)
    if cached is not None:
        return cached, []
    # Keep the reservation even on upstream failure: retries cannot violate
    # the platform's per-order query interval or create concurrent requests.
    if not cache.add(key + ':requested', True, timeout=INTERVAL):
        raise ValidationError('TikTok tracking query is pending or cooling down; retry after eight hours.')
    response = client._request(TRACKING_PATH.format(order_id=order_id),
        query={'shop_cipher': client.authorization.shop_cipher})
    data = response.get('data')
    if not isinstance(data, dict) or (data.get('order_id') is not None and str(data['order_id']) != order_id):
        raise ValidationError('TikTok tracking response identity does not match the order.')
    rows = data.get('tracking')
    if not isinstance(rows, list):
        raise ValidationError('TikTok tracking events are invalid.')
    facts = {'order_sn': order_id, 'status': 'ok',
             'collected_at_utc': client.now().isoformat(), 'packages': []}
    events = []
    for event in rows:
        if (not isinstance(event, dict)
                or type(event.get('action_code')) is not int
                or not isinstance(event.get('description'), str)
                or not event['description'].strip()
                or type(event.get('update_time_millis')) is not int
                or event['update_time_millis'] <= 0):
            raise ValidationError('TikTok tracking event is invalid.')
        try:
            occurred_at = datetime.fromtimestamp(event['update_time_millis'] / 1000, UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            raise ValidationError('TikTok tracking event time is invalid.') from None
        events.append({'occurred_at_utc': occurred_at,
            'description': text(event.get('description'), 2000),
            'status': text(event.get('action_code'), 100)})
    # This endpoint returns order-level events, not a package-to-event mapping.
    # Keep the package identity absent rather than assigning events to a parcel.
    facts['packages'].append({'package_number': None, 'events': events})
    cache.set(snapshot_key, facts, timeout=INTERVAL)
    return facts, [{'endpoint': TRACKING_PATH.format(order_id=order_id),
                    'payload': {'normalized_logistics_snapshot': facts}}]
