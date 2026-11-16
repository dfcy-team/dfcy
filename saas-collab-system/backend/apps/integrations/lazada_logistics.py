"""LazOP order trace projection, verified against native read snapshots."""
from rest_framework.exceptions import ValidationError

from .order_field_mapping import text, timestamp


TRACE_PATH = '/rest/logistic/order/trace'


def collect_order_logistics(client, record):
    order_id = text(record.get('order_id'), 191)
    if not order_id:
        raise ValidationError('Lazada order identity is missing.')
    payload = client._request(TRACE_PATH, {'order_id': order_id})
    result = payload.get('result')
    if not isinstance(result, dict) or result.get('success') is not True:
        raise ValidationError('Lazada trace query failed; retry without advancing the page.')
    modules = result.get('module', [])
    if not isinstance(modules, list):
        raise ValidationError('Lazada trace module is invalid.')
    facts = {'order_sn': order_id, 'status': 'ok', 'collected_at_utc': client.now().isoformat(), 'packages': []}
    for module in modules:
        rows = module.get('package_detail_info_list') if isinstance(module, dict) else None
        if not isinstance(rows, list):
            raise ValidationError('Lazada trace packages are invalid.')
        for row in rows:
            if not isinstance(row, dict) or not text(row.get('ofc_package_id'), 191):
                raise ValidationError('Lazada trace package identity is missing.')
            events = row.get('logistic_detail_info_list', [])
            if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
                raise ValidationError('Lazada trace events are invalid.')
            normalized = []
            for event in events:
                description = event.get('description') or event.get('title')
                occurred_at = timestamp(event.get('event_time'))
                if (type(event.get('event_time')) is not int or event['event_time'] <= 0 or not occurred_at
                        or not isinstance(description, str) or not description.strip()
                        or type(event.get('status_code')) not in (str, int) or not text(event['status_code'])):
                    raise ValidationError('Lazada trace event fields are invalid.')
                normalized.append({'occurred_at_utc': occurred_at,
                    'description': text(description, 2000), 'status': text(event['status_code'], 100)})
            facts['packages'].append({
                'package_number': text(row['ofc_package_id'], 191),
                'tracking_number': text(row.get('tracking_number'), 191) or None,
                'events': normalized,
            })
    # Do not expose proof images, receiver details or arbitrary provider fields.
    return facts, [{'endpoint': TRACE_PATH, 'payload': {'normalized_logistics_snapshot': facts}}]
