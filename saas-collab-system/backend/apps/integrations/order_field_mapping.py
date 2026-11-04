"""Explicit, non-secret order observations; absence is never a zero or a timestamp."""
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError


ORDER_AMOUNTS = ('seller_discount_amount', 'platform_discount_amount', 'tax_amount', 'shipping_amount')
LINE_AMOUNTS = ('original_unit_price', 'sale_unit_price', 'discount_amount', 'tax_amount')
ORDER_COLUMNS = ('raw_status', 'paid_at_utc', 'cancelled_at_utc', 'completed_at_utc', *ORDER_AMOUNTS)
LINE_COLUMNS = ('variation_snapshot', *LINE_AMOUNTS)


def text(value, maximum=240):
    return str(value).strip()[:maximum] if isinstance(value, (str, int)) and not isinstance(value, bool) else ''


def amount(value):
    if value in (None, ''):
        return None
    if isinstance(value, dict):
        value = value.get('amount')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError('平台订单金额格式无效。')
    if not number.is_finite() or number < 0 or number >= Decimal('10000000000000000'):
        raise ValidationError('平台订单金额超出允许范围。')
    return str(number)


def timestamp(value):
    if value in (None, '', 0, '0') or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            number = float(value)
            parsed = datetime.fromtimestamp(number / 1000 if number > 100000000000 else number, tz=UTC)
        else:
            parsed = parse_datetime(str(value))
        if parsed is None or parsed.tzinfo is None:
            return None  # Do not guess a provider timezone.
        return parsed.astimezone(UTC).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def packages(rows):
    if not isinstance(rows, list):
        return []
    allowed = ('package_number', 'package_id', 'tracking_number', 'tracking_no', 'logistics_status',
               'shipping_carrier', 'logistics_channel_id', 'group_shipment_id')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        package = {key: text(row[key], 191) for key in allowed if text(row.get(key), 191)}
        if isinstance(row.get('item_list'), list):
            package['items'] = []
            for item in row['item_list']:
                if not isinstance(item, dict):
                    continue
                identity = {key: text(item[key], 191) for key in ('item_id', 'model_id', 'order_item_id')
                            if text(item.get(key), 191)}
                quantity = item.get('model_quantity')
                identity['quantity'] = quantity if type(quantity) is int and quantity >= 0 else None
                package['items'].append(identity)
        result.append(package)
    return [row for row in result if row]


def recipient_summary(value):
    if not isinstance(value, dict):
        return {}
    # Only coarse destination and masked contact details leave the RAW archive.
    result = {key: text(value[key], 80) for key in ('country', 'state', 'province', 'city') if text(value.get(key), 80)}
    name = text(value.get('name') or value.get('first_name'))
    phone = ''.join(char for char in text(value.get('phone') or value.get('phone_number')) if char.isdigit())
    if name:
        result['name_masked'] = name[0] + '***'
    if phone:
        result['phone_masked'] = '***' + phone[-4:] if len(phone) > 4 else '***'
    return result


def enrich_order_fields(platform, raw, canonical):
    """Extend the existing canonical contract without changing totals or quantities."""
    result = deepcopy(canonical)
    observed = {}
    statuses = raw.get('statuses')
    raw_status = raw.get('order_status') if platform == 'shopee' else (
        statuses[-1] if platform == 'lazada' and isinstance(statuses, list) and statuses else raw.get('status'))
    if text(raw_status, 80):
        observed['raw_status'] = text(raw_status, 80)
    for target, key in (('paid_at_utc', 'pay_time' if platform == 'shopee' else 'paid_time'),
                        ('cancelled_at_utc', 'cancel_time'), ('completed_at_utc', 'complete_time')):
        value = timestamp(raw.get(key))
        if value:
            observed[target] = value
    method = raw.get('payment_method')
    carrier = raw.get('shipping_carrier')
    if text(method, 80):
        observed['payment_method'] = text(method, 80)
    if text(carrier, 160):
        observed['shipping_carrier'] = text(carrier, 160)
    if isinstance(raw.get('package_list'), list):
        observed['packages'] = packages(raw['package_list'])
    if platform == 'shopee':
        if isinstance(raw.get('_platform_logistics'), dict):
            from .shopee_logistics import safe_snapshot
            observed['platform_logistics'] = safe_snapshot(raw['_platform_logistics'])
        # Platform pickup and shipping deadline are not warehouse outbound facts.
        for target, key in (('platform_pickup_at_utc', 'pickup_done_time'), ('ship_by_at_utc', 'ship_by_date')):
            value = timestamp(raw.get(key))
            if value:
                observed[target] = value
        for key in ('booking_sn', 'fulfillment_flag', 'cancel_by'):
            if text(raw.get(key)):
                observed[key] = text(raw[key])
        for key in ('split_up', 'actual_shipping_fee_confirmed'):
            if type(raw.get(key)) is bool:
                observed[key] = raw[key]
    summary = recipient_summary(raw.get('recipient_address') or raw.get('address_shipping'))
    if summary:
        observed['recipient_summary'] = summary
    if text(raw.get('cancel_reason')):
        observed['cancel_reason'] = text(raw['cancel_reason'])
    if platform == 'lazada':
        order_money = {'seller_discount_amount': 'voucher_seller', 'platform_discount_amount': 'voucher_platform',
                       'shipping_amount': 'shipping_fee'}
    elif platform == 'shopee':
        order_money = {'shipping_amount': 'actual_shipping_fee' if raw.get('actual_shipping_fee') is not None else 'estimated_shipping_fee'}
        if raw.get('actual_shipping_fee') is not None or raw.get('estimated_shipping_fee') is not None:
            observed['shipping_amount_basis'] = 'actual' if raw.get('actual_shipping_fee') is not None else 'estimated'
    else:
        payment = raw.get('payment') if isinstance(raw.get('payment'), dict) else {}
        order_money = {}
        value = amount(payment.get('shipping_fee'))
        if value is not None:
            observed['shipping_amount'] = value
    for target, key in order_money.items():
        value = amount(raw.get(key))
        if value is not None:
            observed[target] = value
    # No sum/difference is labelled as a seller discount or tax without an
    # explicit provider field. In particular, Lazada paid_price is not assumed
    # to be a unit price for a multi-quantity item.
    raw_lines = raw.get('item_list' if platform == 'shopee' else 'order_items' if platform == 'lazada' else 'line_items') or []
    raw_lines = [row for row in raw_lines if isinstance(row, dict)] if isinstance(raw_lines, list) else []
    for line, source in zip(result.get('lines', []), raw_lines):
        details = {}
        original, sale = (('model_original_price', 'model_discounted_price') if platform == 'shopee'
                          else ('item_price', 'paid_price') if platform == 'lazada' else ('original_price', 'sale_price'))
        for field, key in (('original_unit_price', original), ('sale_unit_price', sale),
                           ('tax_amount', 'tax_amount'), ('discount_amount', 'discount_amount')):
            value = amount(source.get(key))
            if value is not None and not (platform == 'lazada' and field == 'sale_unit_price' and line.get('quantity') != 1):
                details[field] = value
        if platform == 'lazada' and source.get('paid_price') not in (None, ''):
            details['reported_paid_price'] = amount(source['paid_price'])
        variation = text(source.get('model_name') if platform == 'shopee' else source.get('variation'))
        if variation:
            details['variation_snapshot'] = variation
        if platform == 'shopee':
            for target, key in (('platform_item_sku', 'item_sku'), ('platform_model_sku', 'model_sku'),
                                ('platform_order_item_id', 'order_item_id')):
                if source.get(key) is not None:
                    details[target] = text(source[key])
        line['observed_fields'] = details
    result['observed_fields'] = observed
    return result


def apply_order_observations(order, payload, *, save=True):
    """Update only explicitly observed fields on an already matched local order."""
    changed = {'order_fields': 0, 'item_fields': 0, 'unmatched_items': 0}
    incoming = dict(payload.get('observed_fields') or {})
    # Also support reviewed canonical callers which supply fields directly.
    if 'observed_fields' not in payload:
        for key in ORDER_COLUMNS:
            if payload.get(key) not in (None, ''):
                incoming[key] = timestamp(payload[key]) if key.endswith('_at_utc') else (
                    amount(payload[key]) if key in ORDER_AMOUNTS else text(payload[key], 80))
    incoming = {key: value for key, value in incoming.items() if value is not None}
    metadata = {**(order.source_details or {}), **incoming}
    fields = []
    for key in ORDER_COLUMNS:
        if key in metadata:
            value = timestamp(metadata[key]) if key.endswith('_at_utc') else metadata[key]
            if key.endswith('_at_utc'):
                value = parse_datetime(value) if value else None
            elif key in ORDER_AMOUNTS:
                value = Decimal(value)
            if getattr(order, key) != value:
                setattr(order, key, value)
                fields.append(key)
    if metadata != order.source_details:
        order.source_details = metadata
        fields.append('source_details')
    if fields:
        if save:
            order.save(update_fields=fields)
        changed['order_fields'] = len(fields)
    local_lines = {line.external_line_id: line for line in order.items.all()}
    for source in payload.get('lines') or []:
        line = local_lines.get(str(source.get('external_line_id') or source.get('source_line_id') or ''))
        if line is None or (source.get('platform_variant_id') and str(source['platform_variant_id']) != line.platform_variant_id) or (
                source.get('platform_product_id') and str(source['platform_product_id']) != line.platform_product_id) or (
                str(source.get('seller_sku') or source.get('sku') or '') != line.seller_sku) or source.get('quantity') != line.quantity:
            changed['unmatched_items'] += 1
            continue
        incoming = dict(source.get('observed_fields') or {})
        if 'observed_fields' not in source:
            for key in LINE_COLUMNS:
                if source.get(key) not in (None, ''):
                    incoming[key] = amount(source[key]) if key in LINE_AMOUNTS else text(source[key])
        if (line.source_details or {}).get('api_price_source') == 'shopee_escrow':
            incoming = {key: value for key, value in incoming.items() if key not in ('original_unit_price', 'sale_unit_price')}
        metadata = {**(line.source_details or {}), **{key: value for key, value in incoming.items() if value is not None}}
        fields = []
        for key in LINE_COLUMNS:
            if key in metadata:
                value = Decimal(metadata[key]) if key in LINE_AMOUNTS else metadata[key]
                if getattr(line, key) != value:
                    setattr(line, key, value)
                    fields.append(key)
        if metadata != line.source_details:
            line.source_details = metadata
            fields.append('source_details')
        if fields:
            if save:
                line.save(update_fields=fields)
            changed['item_fields'] += len(fields)
    return changed
