"""Preserve the distinction between provider zero and a missing quantity."""
from django.core.exceptions import ValidationError

QUANTITY_FIELDS = ('on_hand_qty', 'available_qty', 'reserved_qty', 'in_transit_qty', 'pending_putaway_qty', 'defective_qty')


def provided_quantities(payload):
    values = payload.get('provided_quantity_fields')
    if values is None:
        return [key for key in QUANTITY_FIELDS if payload.get(key) not in (None, '')]
    if not isinstance(values, list) or any(not isinstance(key, str) or key not in QUANTITY_FIELDS for key in values):
        raise ValidationError('库存来源字段标记无效。')
    if any(payload.get(key) in (None, '') for key in values):
        raise ValidationError('库存来源字段标记与实际数量不一致。')
    return sorted(set(values))
