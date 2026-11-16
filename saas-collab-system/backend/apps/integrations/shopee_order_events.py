"""Verified Shopee status events; never infer event dates from order snapshots."""
import hashlib
import hmac
import json
from datetime import datetime, timezone


def verify_signature(callback_url, body, partner_key, authorization):
    if not callback_url.startswith('https://') or not partner_key:
        return False
    expected = hmac.new(partner_key.encode(), callback_url.encode() + b'|' + body, hashlib.sha256).hexdigest()
    return (isinstance(authorization, str) and authorization.isascii()
            and hmac.compare_digest(expected, authorization))


def parse_status_event(body):
    if len(body) > 65536:
        raise ValueError('Push exceeds size limit')
    payload = json.loads(body)
    if not isinstance(payload, dict) or payload.get('code') != 3:
        raise ValueError('Expected order status push')
    data = payload.get('data')
    if not isinstance(data, dict):
        raise ValueError('Invalid event data')
    shop_id, order_sn, status = payload.get('shop_id'), data.get('ordersn'), data.get('status')
    if type(shop_id) is not int or shop_id <= 0:
        raise ValueError('Invalid shop')
    if not isinstance(order_sn, str) or not 1 <= len(order_sn) <= 191:
        raise ValueError('Invalid order')
    if not isinstance(status, str) or not 1 <= len(status) <= 80:
        raise ValueError('Invalid status')
    scenario = data.get('completed_scenario') or ''
    if not isinstance(scenario, str) or len(scenario) > 40:
        raise ValueError('Invalid completion scenario')
    times = []
    for value in (data.get('update_time'), payload.get('timestamp')):
        if type(value) is not int or not 0 < value < 253402300800:
            raise ValueError('Invalid timestamp')
        times.append(datetime.fromtimestamp(value, timezone.utc))
    # Delivery timestamp may change on retries. The business event identity must not.
    identity = json.dumps([shop_id, order_sn, status, scenario, data['update_time']], separators=(',', ':'))
    return {
        'shop_id': str(shop_id), 'order_sn': order_sn, 'status': status,
        'completed_scenario': scenario, 'event_at': times[0], 'sent_at': times[1],
        'event_key': hashlib.sha256(identity.encode()).hexdigest(),
        'body_hash': hashlib.sha256(body).hexdigest(),
    }


def event_milestones(events):
    """Return earliest evidenced milestones, independent of delivery order."""
    result = {'completed_at': None, 'cancel_requested_at': None, 'cancelled_at': None}
    for event in sorted(events, key=lambda row: row['event_at']):
        field = {'IN_CANCEL': 'cancel_requested_at', 'CANCELLED': 'cancelled_at'}.get(event['status'])
        if event['status'] == 'COMPLETED' and event['completed_scenario'] == 'NORMAL':
            field = 'completed_at'
        if field and result[field] is None:
            result[field] = event['event_at']
    return result
