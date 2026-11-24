from django.db import transaction
from django.db.models import Min
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from . import logistics, services, wms_documents
from .models import InboundOrder, WmsDocumentLink, domain_write
from .permissions import MANAGE, VIEW


def source(actor, pk):
    row = wms_documents.document_detail(actor, pk)
    return row


def local(actor, doc, pk, permission):
    obj = logistics.inbound_for(actor, pk, permission)
    if obj.status != 'confirmed' or obj.warehouse_id != doc['warehouse_id'] or obj.batch.country_code_snapshot.upper() != doc['site_code'].upper():
        raise ValidationError('请选择同国家、同仓库的已确认入库单。')
    return obj


def candidates(actor, pk, search):
    doc = source(actor, pk)
    query = InboundOrder.objects.filter(batch__in=logistics.batches_for(actor, VIEW),
        status='confirmed', warehouse_id=doc['warehouse_id'],
        batch__country_code_snapshot__iexact=doc['site_code']).select_related('batch')
    if search:
        from django.db.models import Q
        query = query.filter(Q(number__icontains=search) | Q(batch__number__icontains=search))
    return {'items': [{'id': obj.pk, 'number': obj.number, 'batch_number': obj.batch.number,
             'received_quantity': sum(value or 0 for value in obj.lines.values_list('received_quantity', flat=True)) + sum(obj.extra_lines.filter(is_active=True).values_list('received_quantity', flat=True))}
             for obj in query.order_by('-pk')[:50]], 'total': query.count()}


def preview(actor, pk, inbound_id):
    doc = source(actor, pk)
    obj = local(actor, doc, inbound_id, VIEW)
    from .logistics import inbound_data
    detail = inbound_data(obj)
    totals = {}
    for line in doc['lines']:
        code = line['internal_sku__sku_code'] or line['source_sku']
        key = code.lower()
        row = totals.setdefault(key, {'sku': code, 'legacy_sku_code': line['internal_sku__legacy_sku_code'] or '', 'wms_quantity': 0, 'local_quantity': 0})
        row['wms_quantity'] += line['received_quantity']
    for line in detail['lines'] + detail['extra_lines']:
        code = line['sku']
        row = totals.setdefault(code.lower(), {'sku': code, 'legacy_sku_code': line['legacy_sku_code'], 'wms_quantity': 0, 'local_quantity': 0})
        row['local_quantity'] += line['received_quantity'] or 0
    rows = [{**row, 'difference': row['wms_quantity'] - row['local_quantity']} for row in totals.values()]
    result = {'wms_document_id': pk, 'inbound_id': obj.pk, 'version': obj.version, 'rows': rows,
              'status': 'needs_review' if any(row['difference'] for row in rows) else 'matched'}
    result['preview_token'] = services.request_hash(result)
    return result


@transaction.atomic
def link(actor, pk, body, key):
    services._internal(actor)
    services._tenant_lock(actor)
    doc = source(actor, pk)
    obj = local(actor, doc, body['inbound_id'], MANAGE)
    if services._prior_event(actor, obj, 'wms_document_linked', key, body):
        return source(actor, pk)
    services._version(obj, body['expected_version'])
    current = preview(actor, pk, obj.pk)
    if current['preview_token'] != body['preview_token']:
        raise ValidationError('单据内容已变化，请重新预览。')
    reason = str(body.get('reason') or '').strip()
    if not reason:
        raise ValidationError('请填写关联说明。')
    with domain_write():
        row = WmsDocumentLink.objects.filter(tenant_id=actor.tenant_id, site_code=doc['site_code'],
            warehouse_id=doc['warehouse_id'], external_inbound_id=doc['external_inbound_id'],
            inbound=obj, is_active=True).first()
        if row is None:
            row = WmsDocumentLink.objects.create(tenant=actor.tenant, created_by=actor,
                site_code=doc['site_code'], warehouse_id=doc['warehouse_id'],
                external_inbound_id=doc['external_inbound_id'], inbound=obj,
                reason=reason, preview_snapshot=current)
        services._event(actor, obj, 'wms_document_linked', key, body, audit={'link_id': row.pk})
    return source(actor, pk)


@transaction.atomic
def deactivate(actor, pk, link_id, body, key):
    services._internal(actor)
    services._tenant_lock(actor)
    doc = source(actor, pk)
    row = WmsDocumentLink.objects.filter(tenant_id=actor.tenant_id, pk=link_id,
        site_code=doc['site_code'], warehouse_id=doc['warehouse_id'],
        external_inbound_id=doc['external_inbound_id']).first()
    if row is None:
        raise ValidationError('关联不存在或不可访问。')
    local(actor, doc, row.inbound_id, MANAGE)
    if services._prior_event(actor, row, 'wms_document_unlinked', key, body):
        return source(actor, pk)
    services._version(row, body['expected_version'])
    reason = str(body.get('reason') or '').strip()
    if not reason:
        raise ValidationError('请填写解除原因。')
    with domain_write():
        row.is_active = False
        row.deactivated_by = actor
        row.deactivated_at = timezone.now()
        row.deactivate_reason = reason
        row.version += 1
        row.save()
        services._event(actor, row, 'wms_document_unlinked', key, body)
    return source(actor, pk)

def inbound_documents(actor, inbound_id):
    obj = logistics.inbound_for(actor, inbound_id, VIEW)
    visible = wms_documents.visible_lines(actor)
    docs = []
    for row in visible.filter(site_code__iexact=obj.batch.country_code_snapshot,
                              warehouse_id=obj.warehouse_id).order_by().values(
            'site_code', 'warehouse_id', 'external_inbound_id').annotate(id=Min('pk')):
        docs.append(dict(row))
    wms_documents.attach_links(actor, visible, docs)
    return {'items': [{'id': doc['id'], 'external_inbound_id': doc['external_inbound_id']}
                     for doc in docs if any(link['id'] == obj.pk for link in doc['inbounds'])]}
