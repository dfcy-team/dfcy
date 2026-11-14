"""Official return logistics facts; never proof of warehouse receipt."""
from rest_framework.exceptions import ValidationError

from .order_field_mapping import text

LAZADA_DETAIL_PATH = '/rest/order/reverse/return/detail/list'


def lazada_return_logistics(client, record):
    return_id = text(record.get('reverse_order_id'), 191)
    order_id = text(record.get('trade_order_id'), 191)
    if not return_id or not order_id:
        raise ValidationError('Lazada return identity is missing.')
    response = client._request(LAZADA_DETAIL_PATH, {'reverse_order_id': return_id})
    data = response.get('data')
    if str(response.get('code')) != '0' or not isinstance(data, dict):
        raise ValidationError('Lazada return detail is unavailable.')
    if (text(data.get('reverse_order_id'), 191) != return_id
            or text(data.get('trade_order_id'), 191) != order_id):
        raise ValidationError('Lazada return detail identity mismatch.')
    lines = data.get('reverseOrderLineDTOList')
    if not isinstance(lines, list) or any(not isinstance(row, dict) for row in lines):
        raise ValidationError('Lazada return lines are invalid.')
    destination = 'merchant' if data.get('is_rtm') in (True, 'true') else (
        'platform' if data.get('is_rtm') in (False, 'false') else 'unknown')
    facts = {'platform': 'lazada', 'return_sn': return_id, 'order_sn': order_id,
             'collected_at_utc': client.now().isoformat(), 'status': 'ok',
             'return_destination': destination,
             'packages': [{'tracking_number': text(row.get('tracking_number'), 191) or None,
                           'return_line_id': text(row.get('reverse_order_line_id'), 191),
                           'status': text(row.get('reverse_status'), 100)} for row in lines]}
    return facts, {'endpoint': LAZADA_DETAIL_PATH, 'payload': {'normalized_return_logistics': facts}}
