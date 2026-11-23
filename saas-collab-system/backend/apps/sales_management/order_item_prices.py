"""Attach verified historical API prices to existing order items, without changing sales facts."""
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrder
from apps.integrations.order_field_mapping import amount
from apps.integrations.raw_services import load_raw_payload, payload_digest


PRICE_FIELDS = ('original_unit_price', 'sale_unit_price', 'discount_amount', 'tax_amount')


def price_records(platform, payload):
    seen = set()
    for record in payload.get('records') or []:
        if platform == 'shopee' and record.get('order_sn') and isinstance(record.get('item_list'), list):
            seen.add(str(record['order_sn']))
            yield str(record['order_sn']), record['item_list'], 'shopee_order', 1, record.get('currency')
        elif platform == 'lazada' and record.get('order_id') and isinstance(record.get('order_items'), list):
            yield str(record['order_id']), record['order_items'], 'lazada_order', 1, record.get('currency')
    if platform == 'shopee':
        for trace in payload.get('responses') or []:
            if 'get_order_detail' in trace.get('endpoint', ''):
                for record in ((trace.get('payload') or {}).get('response') or {}).get('order_list') or []:
                    if record.get('order_sn') and str(record['order_sn']) not in seen:
                        seen.add(str(record['order_sn']))
                        yield str(record['order_sn']), record.get('item_list') or [], 'shopee_order', 1, record.get('currency')
            if 'get_escrow_detail' not in trace.get('endpoint', ''):
                continue
            detail = (trace.get('payload') or {}).get('response') or {}
            income = detail.get('order_income') or {}
            if detail.get('order_sn') and isinstance(income.get('items'), list):
                yield str(detail['order_sn']), income['items'], 'shopee_escrow', 2, income.get('currency') or detail.get('currency')


def observations(item, source, quantity):
    values = {'api_price_source': source, 'api_price_priority': 2 if source == 'shopee_escrow' else 1}
    if source == 'shopee_escrow':
        line_amount = amount(item.get('discounted_price'))
        if line_amount is None:
            return {}
        for field, provider in [('original_unit_price', 'original_price'), ('sale_unit_price', 'discounted_price')]:
            value = amount(item.get(provider))
            if value is not None:
                values[field] = str((Decimal(value) / quantity).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP))
    elif source == 'shopee_order':
        for field, provider in [('original_unit_price', 'model_original_price'), ('sale_unit_price', 'model_discounted_price')]:
            value = amount(item.get(provider))
            if value is not None:
                values[field] = value
        line_amount = str(Decimal(values['sale_unit_price']) * quantity) if 'sale_unit_price' in values else None
        if values.get('sale_unit_price') is not None and Decimal(values['sale_unit_price']) == 0 and Decimal(values.get('original_unit_price') or 0) > 0:
            values['api_price_unverified_zero'] = True
    else:
        value = amount(item.get('item_price'))
        if value is not None:
            values['original_unit_price'] = value
        line_amount = amount(item.get('paid_price'))
        if line_amount is not None:
            values['reported_paid_price'] = line_amount
            if quantity == 1:
                values['sale_unit_price'] = line_amount
    for field in ('discount_amount', 'tax_amount'):
        value = amount(item.get(field))
        if value is not None:
            values[field] = value
    if line_amount is not None:
        values['reported_line_amount'] = line_amount
    return values


@transaction.atomic
def enrich_item_prices(envelope, *, save=True):
    payload = load_raw_payload(envelope)
    if payload_digest(payload) != envelope.payload_hash:
        raise ValidationError('原始商品价格响应完整性校验失败。')
    summary = Counter()
    if envelope.platform not in ('shopee', 'lazada') or not envelope.store_id:
        return summary
    if envelope.store.tenant_id != envelope.tenant_id or envelope.store.platform.platform_type != envelope.platform:
        raise ValidationError('商品价格响应店铺或租户不匹配。')
    records = list(price_records(envelope.platform, payload))
    orders = {order.external_order_id: order for order in SalesOrder.objects.filter(
        tenant_id=envelope.tenant_id, store_id=envelope.store_id,
        external_order_id__in={record[0] for record in records}).prefetch_related('items')}
    for order_id, items, source, priority, currency in records:
        order = orders.get(order_id)
        if order is None:
            summary['missing_orders'] += 1
            continue
        for item in items:
            if currency and currency != order.currency or item.get('currency') and item['currency'] != order.currency:
                summary['currency_mismatch'] += 1
                continue
            shopee = source.startswith('shopee')
            quantity = item.get('model_quantity_purchased' if source == 'shopee_order' else 'quantity_purchased' if shopee else 'quantity', 1)
            product = str(item.get('item_id') or '') if shopee else str(item.get('product_id') or '')
            variant = str(item.get('model_id') or '') if shopee else str(item.get('sku_id') or '')
            external = str(item.get('order_item_id') or '')
            sku = str(item.get('model_sku') or item.get('item_sku') or '') if shopee else str(item.get('sku') or item.get('seller_sku') or '')
            candidates = [line for line in order.items.all() if line.quantity == quantity
                and (not product or line.platform_product_id == product)
                and (not variant or line.platform_variant_id == variant)
                and (external and line.external_line_id == external or product and variant
                     or sku and line.seller_sku == sku)]
            direct = [line for line in candidates if external and line.external_line_id == external]
            candidates = direct or candidates
            if not candidates or not isinstance(quantity, int) or quantity < 1:
                summary['unmatched_items'] += 1
                continue
            incoming = observations(item, source, quantity)
            if len(candidates) > 1:
                quantity_field = 'model_quantity_purchased' if source == 'shopee_order' else 'quantity_purchased' if shopee else 'quantity'
                same_items = [other for other in items if str(other.get('item_id') or other.get('product_id') or '') == product
                    and str(other.get('model_id') or other.get('sku_id') or '') == variant
                    and other.get(quantity_field, 1) == quantity]
                if not product or not variant or len(same_items) != len(candidates) or any(observations(other, source, quantity) != incoming for other in same_items):
                    summary['unmatched_items'] += 1
                    continue
            if not any(key in incoming for key in (*PRICE_FIELDS, 'reported_line_amount')):
                continue
            incoming.update(api_price_raw_ref=envelope.raw_ref, api_price_raw_hash=envelope.payload_hash, api_price_raw_id=envelope.pk)
            for line in candidates:
                if int((line.source_details or {}).get('api_price_priority') or 0) > priority:
                    continue
                if int((line.source_details or {}).get('api_price_priority') or 0) == priority and int((line.source_details or {}).get('api_price_raw_id') or 0) > envelope.pk:
                    continue
                metadata = {**(line.source_details or {}), **incoming}
                if 'api_price_unverified_zero' in metadata and 'api_price_unverified_zero' not in incoming and 'sale_unit_price' in incoming:
                    metadata['api_price_unverified_zero'] = False
                fields = []
                for field in PRICE_FIELDS:
                    if field in incoming and getattr(line, field) != Decimal(incoming[field]):
                        setattr(line, field, Decimal(incoming[field]))
                        fields.append(field)
                if metadata != line.source_details:
                    line.source_details = metadata
                    fields.append('source_details')
                if fields:
                    summary['items_updated'] += 1
                    if save:
                        line.save(update_fields=fields)
                else:
                    summary['items_unchanged'] += 1
    return summary
