"""Supplier-visible product descriptions. Never serialize the whole product model."""
from copy import deepcopy
from urllib.parse import urlsplit
from apps.products.models import ProductSKU
from .models import BusinessEvent


def safe_image_url(value, tenant_id):
    value = str(value or '').strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
            return value
        prefix = f'/media/product-images/tenant-{int(tenant_id)}/'
        if value.startswith(prefix) and '\\' not in value and '..' not in parsed.path.split('/') and not parsed.query and not parsed.fragment:
            return value
    except (ValueError, TypeError):
        pass
    return ''


def product_details(sku):
    spu = sku.spu
    result = {name: getattr(sku, name) or '' for name in (
        'specification', 'size', 'material', 'unit', 'origin_country', 'hs_code', 'inventory_type', 'product_description')}
    result.update(image_url=safe_image_url(sku.image_url, sku.tenant_id), spu=spu.spu_code,
        brand=spu.brand, category=spu.category_node.name if spu.category_node_id else spu.category,
        product_type=spu.product_type, color=sku.color_code, spec_values=deepcopy(sku.spec_values),
        selling_points=deepcopy(sku.selling_points))
    for field, key in [('package_weight', 'package_weight_g'), ('package_volume', 'package_volume_cbm'),
                       ('package_length_cm', 'package_length_cm'), ('package_width_cm', 'package_width_cm'),
                       ('package_height_cm', 'package_height_cm')]:
        value = getattr(sku, field)
        result[key] = str(value) if value is not None else None
    return result


def enrich_snapshot(snapshot, tenant_id, *, source='current_archive'):
    result = deepcopy(snapshot)
    missing = [line for line in result['lines'] if not line.get('product_details') or 'legacy_sku_code' not in line]
    products = {sku.pk: sku for sku in ProductSKU.objects.filter(tenant_id=tenant_id,
        pk__in=[line['sku_id'] for line in missing]).select_related('spu__category_node')}
    for line in result['lines']:
        if 'legacy_sku_code' not in line:
            sku = products.get(line['sku_id'])
            line['legacy_sku_code'] = (sku.legacy_sku_code or '') if sku else ''
        if not line.get('product_details'):
            sku = products.get(line['sku_id'])
            line['product_details'] = product_details(sku) if sku else {}
            line['product_details_source'] = source
        else:
            line['product_details'] = deepcopy(line['product_details'])
        line['product_details']['image_url'] = safe_image_url(line['product_details'].get('image_url'), tenant_id)
    return result


def order_product_details(order, snapshot):
    result = deepcopy(snapshot)
    event = BusinessEvent.objects.filter(tenant=order.tenant, aggregate_type='purchaseorder',
        aggregate_id=order.pk, action='confirmed').first()
    frozen = {line['id']: line for line in ((event.payload.get('purchase_snapshot') or {}).get('lines') or [])} if event else {}
    for line in result['lines']:
        original = frozen.get(line['id'], {})
        if original.get('product_details'):
            line.update(product_details=original['product_details'], product_details_source='confirmation')
    result = enrich_snapshot(result, order.tenant_id)
    for line in result['lines']:
        line['label_pdf_url'] = f'/api/external/supplier/supply-chain/v2/purchase-orders/{order.pk}/skus/{line["sku_id"]}/labels/'
        line['image_preview_url'] = f'/api/external/supplier/supply-chain/v2/purchase-orders/{order.pk}/skus/{line["sku_id"]}/image/'
    return result


def shipment_line_product_details(lines):
    """Return display details for shipment lines, preferring confirmed purchase snapshots."""
    lines = list(lines)
    if not lines:
        return {}
    tenant_id = lines[0].tenant_id
    order_ids = {line.shipment.order_id for line in lines}
    events = BusinessEvent.objects.filter(tenant_id=tenant_id, aggregate_type='purchaseorder',
        aggregate_id__in=order_ids, action='confirmed').only('aggregate_id', 'payload')
    frozen = {}
    for event in events:
        snapshot = event.payload.get('purchase_snapshot') or {}
        for row in snapshot.get('lines') or []:
            if row.get('product_details'):
                frozen[row.get('id')] = row['product_details']
    missing_ids = {line.sku_id for line in lines if not frozen.get(line.purchase_line_id)}
    products = {sku.pk: sku for sku in ProductSKU.objects.filter(tenant_id=tenant_id,
        pk__in=missing_ids).select_related('spu__category_node')}
    result = {}
    for line in lines:
        details = frozen.get(line.purchase_line_id)
        if details is None:
            sku = products.get(line.sku_id)
            details = product_details(sku) if sku else {}
        else:
            details = deepcopy(details)
        details['image_url'] = safe_image_url(details.get('image_url'), tenant_id)
        result[line.pk] = details
    return result
