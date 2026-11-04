"""Shopee GET-only logistics snapshots. Never warehouse or inventory evidence."""
from rest_framework.exceptions import ValidationError

from .order_field_mapping import text, timestamp


NUMBER_PATH = '/api/v2/logistics/get_tracking_number'
TRACKING_PATH = '/api/v2/logistics/get_tracking_info'
REVERSE_PATH = '/api/v2/returns/get_reverse_tracking_info'
SNAPSHOT_KEYS = frozenset({
    'status', 'order_sn', 'collected_at_utc', 'packages', 'package_number', 'tracking_number',
    'first_mile_tracking_number', 'last_mile_tracking_number', 'logistics_status',
    'events', 'occurred_at_utc', 'description', 'number_query_status', 'tracking_query_status',
    'failed_delivery_return', 'courier_name', 'return_sn', 'validation_type', 'buyer_return',
    'post_return', 'updated_at_utc', 'source_run_id', 'source_operation_id',
})


def safe_snapshot(value):
    if isinstance(value, dict):
        return {key: safe_snapshot(item) for key, item in value.items() if key in SNAPSHOT_KEYS}
    if isinstance(value, list):
        return [safe_snapshot(item) for item in value if isinstance(item, dict)]
    return value if type(value) in (str, int, bool, type(None)) else None


def _events(rows):
    if not isinstance(rows, list):
        return []
    return [{'occurred_at_utc': timestamp(row.get('update_time')),
             'description': text(row.get('tracking_description') or row.get('description'), 2000),
             'status': text(row.get('logistics_status'), 100)}
            for row in rows if isinstance(row, dict)]


def _read(client, path, query):
    try:
        payload = client._request(path, query)
    except ValidationError as exc:
        if 'SHOPEE_TOKEN_REFRESH_REQUIRED' in str(exc.detail):
            raise
        # No provider error text, authentication material, or collection PIN is exposed.
        return None
    response = payload.get('response')
    return response if isinstance(response, dict) else None


def _trace(path, facts):
    return {'endpoint': path, 'payload': {'normalized_logistics_snapshot': safe_snapshot(facts)}}


def collect_order_logistics(client, record):
    order_id = text(record.get('order_sn'), 191)
    if not order_id:
        raise ValidationError('Shopee logistics order identity is missing.')
    rows = record.get('package_list') or []
    ids = [text(row.get('package_number'), 191) for row in rows if isinstance(row, dict)]
    facts = {'order_sn': order_id, 'collected_at_utc': client.now().isoformat(), 'packages': [], 'status': 'ok'}
    if (rows and (len(ids) != len(rows) or not all(ids) or len(ids) != len(set(ids)))) or (
            record.get('split_up') is True and not ids):
        facts['status'] = 'missing_package_identity'
        return facts, []
    traces = []
    for package_id in ids or ['']:
        query = {'order_sn': order_id, **({'package_number': package_id} if package_id else {})}
        number = _read(client, NUMBER_PATH, {**query,
            'response_optional_fields': 'first_mile_tracking_number,last_mile_tracking_number'})
        tracking = _read(client, TRACKING_PATH, query)
        if tracking is not None and (tracking.get('order_sn') != order_id or (
                package_id and tracking.get('package_number') != package_id)):
            raise ValidationError('Shopee logistics response identity does not match the query.')
        package = {'package_number': package_id or None,
                   'number_query_status': 'ok' if number is not None else 'unavailable',
                   'tracking_query_status': 'ok' if tracking is not None else 'unavailable'}
        if number is not None:
            for key in ('tracking_number', 'first_mile_tracking_number', 'last_mile_tracking_number'):
                package[key] = text(number.get(key), 191) or None
            traces.append(_trace(NUMBER_PATH, {**package, 'order_sn': order_id}))
        if tracking is not None:
            package.update(logistics_status=text(tracking.get('logistics_status'), 100) or None,
                           events=_events(tracking.get('tracking_info')))
            if any(tracking.get(key) for key in ('reversed_tracking_number', 'reversed_tracking_info')):
                package['failed_delivery_return'] = {
                    'tracking_number': text(tracking.get('reversed_tracking_number'), 191) or None,
                    'courier_name': text(tracking.get('reversed_courier_name'), 160) or None,
                    'events': _events(tracking.get('reversed_tracking_info'))}
            traces.append(_trace(TRACKING_PATH, {**package, 'order_sn': order_id}))
        if number is None or tracking is None:
            facts['status'] = 'partial'
        facts['packages'].append(package)
    return facts, traces


def collect_return_logistics(client, return_id):
    return_id = text(return_id, 191)
    if not return_id:
        raise ValidationError('Shopee logistics return identity is missing.')
    response = _read(client, REVERSE_PATH, {'return_sn': return_id})
    facts = {'return_sn': return_id, 'collected_at_utc': client.now().isoformat(),
             'status': 'ok' if response is not None else 'unavailable'}
    if response is None:
        return facts, []
    if response.get('return_sn') != return_id:
        raise ValidationError('Shopee reverse logistics response identity does not match the query.')
    facts['validation_type'] = text(response.get('validation_type'), 100) or None
    for name, status_key, time_key, number_key, events_key in (
        ('buyer_return', 'reverse_logistics_status', 'reverse_logistics_update_time', 'tracking_number', 'tracking_info'),
        ('post_return', 'post_return_logistics_status', 'post_return_logistics_update_time',
         'rts_tracking_number', 'post_return_logistics_tracking_info'),
    ):
        facts[name] = {'status': text(response.get(status_key), 100) or None,
                       'updated_at_utc': timestamp(response.get(time_key)),
                       'tracking_number': text(response.get(number_key), 191) or None,
                       'events': _events(response.get(events_key))}
    return facts, [_trace(REVERSE_PATH, facts)]
