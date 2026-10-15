"""Quantity-only projection; stages never add a second copy of the same shipment."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Sum
from apps.commerce.models import InboundRecord
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.supply_chain.models import (PurchaseLine, ShipmentLine, DispatchMembership,
    InternalStockReceiptLine, OperatingAllocation, WmsReceiptAllocation)
from apps.sales_management.operating_models import OperatingOrderLine
from apps.supply_chain.services import request_hash

SUMMARY_PERMISSION = 'sales_management.supply_summary.view'
STAGES = ('production_unshipped', 'awaiting_dispatch', 'transporting', 'arrived_unchecked',
          'received_awaiting_wms', 'wms_received', 'excess_shipped', 'additional_shipped',
          'open_operating_demand', 'effective_incoming', 'unknown_eta')


def summary_allowed(actor, country):
    if not check_user_permission(actor, SUMMARY_PERMISSION):
        return False
    scopes = get_permission_data_scopes(actor, SUMMARY_PERMISSION)
    return bool(actor.is_superuser or any(s['scope_type'] == 'all' or (
        s['scope_type'] == 'custom' and country.pk in (s.get('config') or {}).get('site_ids', [])) for s in scopes))


def open_demand(actor, country, sku_ids, *, exclude_order_id=None):
    """Drafts reserve demand too; a draft PO must not make that reservation vanish."""
    rows = OperatingOrderLine.objects.filter(tenant_id=actor.tenant_id, order__country=country,
        order__status__in=['draft', 'submitted'], is_active=True, sku_id__in=sku_ids)
    if exclude_order_id is not None:
        rows = rows.exclude(order_id=exclude_order_id)
    allocated = dict(OperatingAllocation.objects.filter(tenant_id=actor.tenant_id,
        operating_line__in=rows, purchase_line__is_active=True, purchase_line__order__status='confirmed')
        .values('operating_line_id').annotate(total=Sum('allocated_quantity'))
        .values_list('operating_line_id', 'total'))
    totals = defaultdict(int)
    signature = []
    for row in rows.order_by('pk').values('id', 'sku_id', 'quantity', 'order__version'):
        reserved = max(0, row['quantity'] - allocated.get(row['id'], 0))
        totals[row['sku_id']] += reserved
        signature.append([row['id'], row['quantity'], row['order__version'], allocated.get(row['id'], 0)])
    return totals, request_hash(signature)


def valid_wms_allocations(rows):
    """A later upstream correction invalidates an over-allocation instead of hiding it."""
    values = list(rows.select_related('wms_line__source_run__sync_job__integration_config', 'receipt_line__receipt__inbound__batch'))
    wms_ids = [a.wms_line_id for a in values]
    totals = dict(WmsReceiptAllocation.objects.filter(is_active=True, wms_line_id__in=wms_ids)
        .values('wms_line_id').annotate(total=Sum('quantity')).values_list('wms_line_id', 'total'))
    valid, invalid = defaultdict(int), set()
    for row in values:
        wms, local = row.wms_line, row.receipt_line
        if (wms.source_run.status != 'success' or wms.source_run.failed_count or
            wms.source_run.sync_job.resource_type != 'inbound' or
            wms.source_run.sync_job.integration_config.platform != 'jifeng_wms' or
            wms.internal_sku_id != local.sku_id or wms.warehouse_id != local.receipt.warehouse_id or
            wms.site_code.upper() != local.receipt.inbound.batch.country_code_snapshot.upper() or
            totals.get(wms.pk, 0) > wms.received_quantity):
            invalid.add(local.pk)
        else:
            valid[local.pk] += row.quantity
    return valid, invalid


def pipeline_for(actor, country, sku_ids, *, today, target_days, warehouse_ids=None, exclude_order_id=None):
    authorized = summary_allowed(actor, country)
    result = {pk: {'authorized': authorized, **{key: 0 if authorized else None for key in STAGES},
                   'issues': []} for pk in sku_ids}
    if not authorized:
        return result
    pending, signature = open_demand(actor, country, sku_ids, exclude_order_id=exclude_order_id)
    for pk in sku_ids:
        result[pk]['open_operating_demand'] = pending[pk]
        result[pk]['open_demand_signature'] = signature
    # Purchase production has no warehouse identity. Restricted warehouse views cannot claim completeness.
    restricted = warehouse_ids is not None
    purchase = PurchaseLine.objects.filter(tenant_id=actor.tenant_id, order__country=country,
        order__status='confirmed', is_active=True, sku_id__in=sku_ids)
    shipments = ShipmentLine.objects.filter(tenant_id=actor.tenant_id, shipment__order__country=country,
        shipment__status='submitted', is_active=True, sku_id__in=sku_ids)
    shipped = dict(shipments.filter(purchase_line__isnull=False).values('purchase_line_id')
        .annotate(total=Sum('quantity')).values_list('purchase_line_id', 'total'))
    if not restricted:
        for line in purchase.values('pk', 'sku_id', 'quantity'):
            remaining = max(0, line['quantity'] - shipped.get(line['pk'], 0))
            result[line['sku_id']]['production_unshipped'] += remaining
            result[line['sku_id']]['unknown_eta'] += remaining
    else:
        for value in result.values():
            value['issues'].append('warehouse_supply_scope_incomplete')
            value['production_unshipped'] = None
            value['open_operating_demand'] = None
    members = {m.shipment_id: m.batch for m in DispatchMembership.objects.filter(
        tenant_id=actor.tenant_id, shipment_id__in=shipments.values('shipment_id'),
        active_guard=True, batch__status='active').select_related('batch')}
    receipts = {r.inbound_line.shipment_line_id: r for r in InternalStockReceiptLine.objects.filter(
        tenant_id=actor.tenant_id, inbound_line__shipment_line__in=shipments,
        receipt__inbound__status='confirmed').select_related('inbound_line', 'receipt__inbound__batch')}
    matched, invalid = valid_wms_allocations(WmsReceiptAllocation.objects.filter(
        tenant_id=actor.tenant_id, is_active=True, receipt_line_id__in=[r.pk for r in receipts.values()]))
    # WMS may receive goods before someone updates the manually tracked batch stage.
    # Such a receipt may already be in available stock: unresolved overlap blocks a usable recommendation.
    upstream = InboundRecord.objects.filter(tenant_id=actor.tenant_id, site_code__iexact=country.country_code,
        internal_sku_id__in=sku_ids, received_quantity__gt=0, source_run__status='success',
        source_run__failed_count=0, source_run__sync_job__resource_type='inbound',
        source_run__sync_job__integration_config__platform='jifeng_wms')
    linked = defaultdict(int)
    for allocation in WmsReceiptAllocation.objects.filter(tenant_id=actor.tenant_id, is_active=True,
            wms_line__in=upstream).select_related('wms_line', 'receipt_line__receipt'):
        if (allocation.receipt_line.sku_id == allocation.wms_line.internal_sku_id and
            allocation.receipt_line.receipt.warehouse_id == allocation.wms_line.warehouse_id):
            linked[allocation.wms_line_id] += allocation.quantity
    latest_unmatched = {}
    for row in upstream.values('pk', 'internal_sku_id', 'warehouse_id', 'received_quantity', 'received_at_utc', 'updated_at_utc'):
        if linked[row['pk']] == row['received_quantity']:
            continue
        identity = (row['internal_sku_id'], row['warehouse_id'])
        moment = row['received_at_utc'] or row['updated_at_utc']
        latest_unmatched[identity] = max(latest_unmatched.get(identity, moment), moment)
    for line in shipments.values('pk', 'shipment_id', 'sku_id', 'quantity', 'excess_quantity', 'exception_type'):
        item, batch, receipt = result[line['sku_id']], members.get(line['shipment_id']), receipts.get(line['pk'])
        destination = receipt.receipt.warehouse_id if receipt else batch.planned_warehouse_id if batch else None
        if restricted and destination not in warehouse_ids:
            if destination is None and 'unassigned_warehouse_supply' not in item['issues']:
                item['issues'].append('unassigned_warehouse_supply')
            continue
        item['excess_shipped'] += line['excess_quantity']
        item['additional_shipped'] += line['quantity'] if line['exception_type'] == 'additional' else 0
        if receipt:
            reconciled = min(receipt.received_quantity, matched.get(receipt.pk, 0))
            item['received_awaiting_wms'] += receipt.received_quantity - reconciled
            item['wms_received'] += reconciled
            if receipt.pk in invalid:
                item['issues'].append('wms_allocation_requires_review')
            if receipt.received_quantity != line['quantity']:
                item['issues'].append('local_receipt_quantity_difference')
            # Local receipts never add available stock; the WMS snapshot is authoritative.
            continue
        if batch and batch.stage == 'arrived_warehouse':
            item['arrived_unchecked'] += line['quantity']
            continue
        stage = 'transporting' if batch and batch.stage in ['departed', 'arrived_port'] else 'awaiting_dispatch'
        item[stage] += line['quantity']
        eta = batch.expected_warehouse_date if batch else None
        if eta is None:
            item['unknown_eta'] += line['quantity']
        elif eta < today:
            item['issues'].append('overdue_eta')
        elif eta <= today + timedelta(days=target_days):
            item['effective_incoming'] += line['quantity']
            if batch:
                sent_at = batch.departed_at or batch.created_at
                overlap = any(moment >= sent_at for (sku_id, warehouse_id), moment in latest_unmatched.items()
                    if sku_id == line['sku_id'] and (batch.planned_warehouse_id is None or warehouse_id == batch.planned_warehouse_id))
                if overlap:
                    item['issues'].append('wms_receipt_overlap_unresolved')
    for value in result.values():
        if value['unknown_eta']:
            value['issues'].append('unknown_eta')
        value['issues'] = sorted(set(value['issues']))
        if 'wms_receipt_overlap_unresolved' in value['issues']:
            value['effective_incoming'] = None
    return result
