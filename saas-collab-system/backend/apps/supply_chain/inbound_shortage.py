"""Order-level final unreceived shortage: logistics closure, never a payment reduction."""
from collections import defaultdict
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from .models import (PurchaseOrder, DispatchBatch, DispatchAllocation, ShipmentLine,
                     InboundShortageTermination, domain_write)
from . import services, logistics, inbound_split
from .permissions import MANAGE


def preview(actor, order_id):
    services._internal(actor)
    order = services._order(actor, order_id)
    if order.status != 'confirmed':
        raise ValidationError('只有已下单采购单可处理最终未到货短缺。')
    allowed_batches = logistics.batches_for(actor, MANAGE).filter(status='active',stage='arrived_warehouse')
    allocations = list(DispatchAllocation.objects.filter(tenant_id=actor.tenant_id,
        membership__batch__in=allowed_batches, membership__active_guard=True,
        shipment_line__is_active=True, shipment_line__shipment__status='submitted').filter(
            Q(shipment_line__purchase_line__order_id=order.pk) |
            Q(shipment_line__purchase_line__isnull=True,shipment_line__shipment__order_id=order.pk)
        ).select_related('membership__batch','shipment_line__sku').order_by('membership__batch_id','shipment_line_id'))
    by_batch = {}
    for allocation in allocations:
        by_batch.setdefault(allocation.membership.batch_id, {'batch':allocation.membership.batch,'allocations':[]})['allocations'].append(allocation)
    rows = []
    for data in by_batch.values():
        batch = data['batch']
        planned, received, consumed, reserved, terminated = inbound_split.quantities(batch)
        for allocation in data['allocations']:
            source = allocation.shipment_line
            remaining = max(0,planned.get(source.pk,0)-consumed[source.pk]-terminated[source.pk])
            if not remaining:
                continue
            can_terminate = reserved[source.pk] == 0
            rows.append({'batch_id':batch.pk,'batch_number':batch.number,'batch_version':batch.version,
                'shipment_line_id':source.pk,'sku':source.sku_code_snapshot,
                'legacy_sku':source.sku.legacy_sku_code or '', 'name':source.product_name_snapshot,
                'planned_quantity':planned[source.pk],'received_quantity':received[source.pk],
                'reserved_quantity':reserved[source.pk],'remaining_quantity':remaining,
                'available_quantity':remaining if can_terminate else 0,'can_terminate':can_terminate})
    result={'scope':'inbound_shortage','version':order.version,'rows':rows}
    result['preview_token']=services.request_hash(result)
    return result


@transaction.atomic
def terminate(actor, order_id, payload, request_key):
    services._internal(actor); services._tenant_lock(actor)
    permitted=services._order(actor,order_id)
    order=PurchaseOrder.objects.select_for_update().get(pk=permitted.pk,tenant_id=actor.tenant_id)
    reason=str(payload.get('reason') or '').strip()
    supplied=payload.get('lines')
    if not reason or not isinstance(supplied,list) or not supplied:
        raise ValidationError('请选择最终短缺商品、数量并填写原因。')
    normalized=[];seen=set()
    for row in supplied:
        batch_id,source_id,quantity=row.get('batch_id'),row.get('shipment_line_id'),row.get('quantity')
        if any(isinstance(v,bool) or not isinstance(v,int) or v<=0 for v in (batch_id,source_id,quantity)) or (batch_id,source_id) in seen:
            raise ValidationError('最终短缺商品不得重复，数量须为正整数。')
        seen.add((batch_id,source_id));normalized.append({'batch_id':batch_id,'shipment_line_id':source_id,'quantity':quantity})
    normalized.sort(key=lambda r:(r['batch_id'],r['shipment_line_id']))
    action_payload={'scope':'inbound_shortage','expected_version':payload.get('expected_version'),
        'preview_token':payload.get('preview_token'),'reason':reason,'lines':normalized}
    if services._prior_event(actor,order,'purchase_inbound_shortage_terminated',request_key,action_payload):
        return order
    services._version(order,action_payload['expected_version'])
    current=preview(actor,order.pk)
    if current['preview_token'] != action_payload['preview_token']:
        raise ValidationError('实收、草稿占用或订单版本已变化，请重新预览。')
    options={(row['batch_id'],row['shipment_line_id']):row for row in current['rows']}
    for row in normalized:
        state=options.get((row['batch_id'],row['shipment_line_id']))
        if state is None or not state['can_terminate'] or row['quantity']>state['available_quantity']:
            raise ValidationError('终止数量超过可处理的最终未到货数量，或仍有入库草稿占用。')
    batches={};ids=[]
    with domain_write():
        for row in normalized:
            if row['batch_id'] not in batches:
                permitted_batch=logistics.batch_for(actor,row['batch_id'],MANAGE)
                batches[row['batch_id']]=DispatchBatch.objects.select_for_update().get(pk=permitted_batch.pk,tenant_id=actor.tenant_id)
            record=InboundShortageTermination.objects.create(tenant=actor.tenant,created_by=actor,
                purchase_order=order,batch=batches[row['batch_id']],shipment_line_id=row['shipment_line_id'],
                quantity=row['quantity'],reason=reason,request_key=services._key(request_key),origin='final_shortage')
            ids.append(record.pk)
        for batch in batches.values():
            batch.version+=1;batch.save()
            batch_key='inbound-shortage-'+str(batch.pk)+'-'+services.request_hash({'key':request_key})[:24]
            services._event(actor,batch,'inbound_shortage_terminated',batch_key,{'order_id':order.pk,
                'reason':reason,'lines':[r for r in normalized if r['batch_id']==batch.pk]},audit={'shortage_ids':ids})
        order.version+=1;order.save()
        services._event(actor,order,'purchase_inbound_shortage_terminated',request_key,action_payload,
            audit={'shortage_ids':ids,'terminated_inbound_quantity':sum(r['quantity'] for r in normalized),
                'prices_and_payments_changed':False})
    from .inbound_costs import estimate_for_batch_shortage
    for batch in batches.values():
        estimate_for_batch_shortage(actor,batch,request_key)
    return order
