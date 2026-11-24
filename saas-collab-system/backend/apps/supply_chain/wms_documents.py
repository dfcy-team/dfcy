"""Read-only document view of the WMS records used for receipt reconciliation."""
from django.db.models import Exists, Max, Min, OuterRef, Q, Sum
from django.utils.dateparse import parse_date
from rest_framework.exceptions import NotFound, ValidationError

from . import logistics
from .models import WmsReceiptAllocation
from .permissions import VIEW, require_internal_supply_permission
from .wms_reconciliation import _eligible_wms, _wms_access


def visible_lines(actor):
    require_internal_supply_permission(actor, VIEW)
    return _eligible_wms(_wms_access(actor))


def document_key(row):
    return row['site_code'], row['warehouse_id'], row['external_inbound_id']


def document_links(actor, lines):
    return WmsReceiptAllocation.objects.filter(
        tenant_id=actor.tenant_id, is_active=True, wms_line__in=lines,
        receipt_line__receipt__inbound__batch__in=logistics.batches_for(actor, VIEW),
    ).order_by().values_list(
        'wms_line__site_code', 'wms_line__warehouse_id', 'wms_line__external_inbound_id',
        'receipt_line__receipt__inbound_id', 'receipt_line__receipt__inbound__number',
    ).distinct()


def attach_links(actor, lines, docs):
    if not docs:
        return
    keyed = {document_key(doc): doc for doc in docs}
    groups = Q(pk__in=[])
    for site, warehouse, number in keyed:
        groups |= Q(site_code=site, warehouse_id=warehouse, external_inbound_id=number)
    for doc in docs:
        doc['inbounds'] = []
    for site, warehouse, number, pk, local_number in document_links(actor, lines.filter(groups)):
        keyed[site, warehouse, number]['inbounds'].append({'id': pk, 'number': local_number})
    from .models import WmsDocumentLink
    manual_groups = Q(pk__in=[])
    for site, warehouse, number in keyed:
        manual_groups |= Q(site_code=site, warehouse_id=warehouse, external_inbound_id=number)
    links = WmsDocumentLink.objects.filter(manual_groups,tenant_id=actor.tenant_id, is_active=True,
        inbound__batch__in=logistics.batches_for(actor, VIEW)).select_related('inbound__batch')
    for link in links:
        key = (link.site_code, link.warehouse_id, link.external_inbound_id)
        if (key not in keyed or link.inbound.warehouse_id != link.warehouse_id
                or link.inbound.batch.country_code_snapshot.upper() != link.site_code.upper()):
            continue
        values = keyed[key]['inbounds']
        existing = next((value for value in values if value['id'] == link.inbound_id), None)
        value = {'id': link.inbound_id, 'number': link.inbound.number,
                 'manual_link_id': link.pk, 'manual_link_version': link.version,
                 'association_status': link.preview_snapshot.get('status', 'needs_review'),
                 'association_reason': link.reason, 'associated_at': link.created_at}
        if existing:
            existing.update(value)
        else:
            values.append(value)



def list_documents(actor, params):
    lines = visible_lines(actor)
    try:
        page = int(params.get('page', '1'))
        start = parse_date(params['start_date']) if params.get('start_date') else None
        end = parse_date(params['end_date']) if params.get('end_date') else None
        if not 1 <= page <= 100000 or (params.get('start_date') and not start) or (params.get('end_date') and not end):
            raise ValueError
        if start and end and start > end:
            raise ValueError
    except ValueError as exc:
        raise ValidationError('请检查入库日期和页码。') from exc
    warehouse = params.get('warehouse', '').strip()[:100]
    if warehouse:
        lines = lines.filter(Q(warehouse__name__icontains=warehouse) | Q(warehouse__code__icontains=warehouse))
    search = params.get('search', '').strip()[:160]
    if search or start or end:
        matching = lines.filter(site_code=OuterRef('site_code'), warehouse_id=OuterRef('warehouse_id'),
                                external_inbound_id=OuterRef('external_inbound_id'))
        if search:
            matching = matching.filter(Q(external_inbound_id__icontains=search) | Q(source_sku__icontains=search)
                                       | Q(internal_sku__sku_code__icontains=search)
                                       | Q(internal_sku__legacy_sku_code__icontains=search))
        if start:
            matching = matching.filter(received_at_utc__date__gte=start)
        if end:
            matching = matching.filter(received_at_utc__date__lte=end)
        lines = lines.filter(Exists(matching))
    docs = lines.order_by().values('site_code', 'warehouse_id', 'warehouse__name', 'external_inbound_id').annotate(
        id=Min('pk'), received_quantity=Sum('received_quantity'), received_at=Max('received_at_utc'),
    ).order_by('-received_at', '-id')
    start_at = (page - 1) * 20
    items = list(docs[start_at:start_at + 20])
    attach_links(actor, lines, items)
    return {'items': items, 'total': docs.count()}


def document_detail(actor, pk):
    visible = visible_lines(actor)
    row = visible.filter(pk=pk).values('site_code', 'warehouse_id', 'warehouse__name', 'external_inbound_id').first()
    if row is None:
        raise NotFound('三方仓入库单不存在或不在授权范围。')
    row['id'] = pk
    site, warehouse, number = document_key(row)
    lines = visible.filter(site_code=site, warehouse_id=warehouse, external_inbound_id=number)
    row['lines'] = list(lines.order_by('pk').values(
        'id', 'source_sku', 'internal_sku__sku_code', 'internal_sku__legacy_sku_code',
        'internal_sku__product_name', 'planned_quantity', 'received_quantity', 'status',
    ))
    attach_links(actor, lines, [row])
    return row
