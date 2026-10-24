"""Quantity-only projection; stages never add a second copy of the same shipment."""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Q, Sum
from apps.commerce.models import InboundRecord
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.supply_chain.models import (PurchaseLine, ShipmentLine, DispatchMembership, DispatchAllocation,
    InternalStockReceiptLine, OperatingAllocation, WmsReceiptAllocation)
from apps.sales_management.operating_models import OperatingOrderLine
from apps.supply_chain.services import request_hash

SUMMARY_PERMISSION = 'sales_management.supply_summary.view'
STAGES = ('production_unshipped', 'awaiting_dispatch', 'transporting', 'arrived_unchecked',
          'received_awaiting_wms', 'wms_received', 'excess_shipped', 'additional_shipped',
          'open_operating_demand', 'effective_incoming', 'unknown_eta')


def summary_allowed(actor, country, permission_cache=None):
    for permission in (SUMMARY_PERMISSION, 'supply.v2.view'):
        if not check_user_permission(actor, permission, cache=permission_cache):
            continue
        scopes = get_permission_data_scopes(actor, permission, cache=permission_cache)
        if actor.is_superuser or any(s['scope_type'] == 'all' for s in scopes):
            return True
        if any(s['scope_type'] == 'custom' and country.pk in (s.get('config') or {}).get('site_ids', [])
               for s in scopes):
            return True
    return False


def open_demand_breakdown(actor, country, sku_ids, *, exclude_order_id=None, horizon_start=None, horizon_end=None):
    """Return submitted and draft reservations separately; both prevent duplicate demand."""
    rows = OperatingOrderLine.objects.filter(tenant_id=actor.tenant_id, order__country=country,
        order__status__in=['draft', 'submitted'], is_active=True, sku_id__in=sku_ids)
    if exclude_order_id is not None:
        rows = rows.exclude(order_id=exclude_order_id)
    if horizon_start is not None and horizon_end is not None:
        rows = rows.filter(Q(order__demand_start__isnull=True) | Q(order__demand_end__isnull=True) |
            Q(order__demand_start__lte=horizon_end, order__demand_end__gte=horizon_start))
    allocated = dict(OperatingAllocation.objects.filter(tenant_id=actor.tenant_id,
        operating_line__in=rows, purchase_line__is_active=True, purchase_line__order__status='confirmed')
        .values('operating_line_id').annotate(total=Sum('allocated_quantity'))
        .values_list('operating_line_id', 'total'))
    totals = defaultdict(lambda: {'submitted': 0, 'draft_reserved': 0})
    signature = []
    for row in rows.order_by('pk').values('id', 'sku_id', 'quantity', 'order__version', 'order__status'):
        reserved = max(0, row['quantity'] - allocated.get(row['id'], 0))
        status = row['order__status']
        totals[row['sku_id']]['submitted' if status == 'submitted' else 'draft_reserved'] += reserved
        signature.append([row['id'], row['quantity'], row['order__version'], allocated.get(row['id'], 0)])
    return totals, request_hash(signature)


def open_demand(actor, country, sku_ids, *, exclude_order_id=None, horizon_start=None, horizon_end=None):
    """Backward-compatible total demand reservation, including existing drafts."""
    breakdown, signature = open_demand_breakdown(actor, country, sku_ids,
        exclude_order_id=exclude_order_id, horizon_start=horizon_start, horizon_end=horizon_end)
    return {sku_id: value['submitted'] + value['draft_reserved'] for sku_id, value in breakdown.items()}, signature


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


def pipeline_for(actor, country, sku_ids, *, today, target_days, warehouse_ids=None, exclude_order_id=None,
                 horizon_start=None, horizon_end=None, permission_cache=None):
    authorized = summary_allowed(actor, country, permission_cache)
    result = {pk: {'authorized': authorized, **{key: 0 if authorized else None for key in STAGES},
                   'eta_rows': [], 'issues': []} for pk in sku_ids}
    if not authorized:
        return result
    pending, signature = open_demand_breakdown(actor, country, sku_ids,
        exclude_order_id=exclude_order_id, horizon_start=horizon_start, horizon_end=horizon_end)
    purchase = PurchaseLine.objects.filter(tenant_id=actor.tenant_id, order__country=country,
        order__status='confirmed', is_active=True, sku_id__in=sku_ids)
    purchase_rows = list(purchase.values('pk', 'sku_id', 'quantity', 'order__version', 'order__status',
        'order__updated_at').order_by('pk'))
    source_rows = defaultdict(lambda: {'purchase': [], 'shipment': [], 'allocation': [], 'receipt': [], 'wms': []})
    for row in purchase_rows:
        source_rows[row['sku_id']]['purchase'].append(row)
    for pk in sku_ids:
        result[pk]['submitted_operating_demand'] = pending[pk]['submitted']
        result[pk]['draft_reserved_demand'] = pending[pk]['draft_reserved']
        result[pk]['open_operating_demand'] = pending[pk]['submitted'] + pending[pk]['draft_reserved']
        result[pk]['open_demand_signature'] = signature
        result[pk]['demand_horizon'] = {'start': horizon_start.isoformat() if horizon_start else None,
            'end': horizon_end.isoformat() if horizon_end else None,
            'unbounded_periods_included': horizon_start is not None and horizon_end is not None}
    # Purchase production has no warehouse identity. Restricted warehouse views cannot claim completeness.
    restricted = warehouse_ids is not None
    shipments = ShipmentLine.objects.filter(tenant_id=actor.tenant_id, shipment__order__country=country,
        shipment__status='submitted', is_active=True, sku_id__in=sku_ids)
    shipped = dict(shipments.filter(purchase_line__isnull=False).values('purchase_line_id')
        .annotate(total=Sum('quantity')).values_list('purchase_line_id', 'total'))
    if not restricted:
        for line in purchase_rows:
            remaining = max(0, line['quantity'] - shipped.get(line['pk'], 0))
            result[line['sku_id']]['production_unshipped'] += remaining
            result[line['sku_id']]['unknown_eta'] += remaining
    else:
        for value in result.values():
            value['issues'].append('warehouse_supply_scope_incomplete')
            value['production_unshipped'] = None
            value['open_operating_demand'] = None
            value['submitted_operating_demand'] = None
            value['draft_reserved_demand'] = None
    allocations = list(DispatchAllocation.objects.filter(tenant_id=actor.tenant_id,
        shipment_line__in=shipments, membership__active_guard=True,
        membership__batch__status='active').select_related('membership__batch', 'shipment_line'))
    allocations_by_line = defaultdict(list)
    for allocation in allocations:
        allocations_by_line[allocation.shipment_line_id].append(allocation)
        batch = allocation.membership.batch
        source_rows[allocation.shipment_line.sku_id]['allocation'].append({
            'id': allocation.pk, 'version': allocation.version, 'quantity': allocation.quantity,
            'shipment_line_id': allocation.shipment_line_id, 'batch_id': batch.pk,
            'batch_version': batch.version, 'batch_status': batch.status, 'batch_stage': batch.stage,
            'expected_warehouse_date': batch.expected_warehouse_date, 'updated_at': batch.updated_at})
    receipts = list(InternalStockReceiptLine.objects.filter(tenant_id=actor.tenant_id,
        inbound_line__shipment_line__in=shipments, receipt__inbound__status='confirmed')
        .select_related('inbound_line', 'receipt__inbound__batch'))
    receipts_by_line, receipts_by_batch_line = defaultdict(list), defaultdict(int)
    for receipt in receipts:
        line_id = receipt.inbound_line.shipment_line_id
        receipts_by_line[line_id].append(receipt)
        receipts_by_batch_line[(line_id, receipt.receipt.inbound.batch_id)] += receipt.received_quantity
        source_rows[receipt.sku_id]['receipt'].append({'id': receipt.pk, 'received_quantity': receipt.received_quantity,
            'inbound_line_id': receipt.inbound_line_id, 'inbound_version': receipt.receipt.inbound.version,
            'inbound_status': receipt.receipt.inbound.status, 'receipt_id': receipt.receipt_id,
            'warehouse_id': receipt.receipt.warehouse_id})
    matched, invalid = valid_wms_allocations(WmsReceiptAllocation.objects.filter(
        tenant_id=actor.tenant_id, is_active=True, receipt_line_id__in=[r.pk for r in receipts]))
    # WMS may receive goods before someone updates the manually tracked batch stage.
    # Such a receipt may already be in available stock: unresolved overlap blocks a usable recommendation.
    upstream = InboundRecord.objects.filter(tenant_id=actor.tenant_id, site_code__iexact=country.country_code,
        internal_sku_id__in=sku_ids, received_quantity__gt=0, source_run__status='success',
        source_run__failed_count=0, source_run__sync_job__resource_type='inbound',
        source_run__sync_job__integration_config__platform='jifeng_wms')
    if restricted:
        upstream = upstream.filter(warehouse_id__in=warehouse_ids)
    linked = defaultdict(int)
    for allocation in WmsReceiptAllocation.objects.filter(tenant_id=actor.tenant_id, is_active=True,
            wms_line__in=upstream).select_related('wms_line', 'receipt_line__receipt'):
        if (allocation.receipt_line.sku_id == allocation.wms_line.internal_sku_id and
            allocation.receipt_line.receipt.warehouse_id == allocation.wms_line.warehouse_id):
            linked[allocation.wms_line_id] += allocation.quantity
        source_rows[allocation.wms_line.internal_sku_id]['wms'].append({'id': allocation.pk,
            'quantity': allocation.quantity, 'wms_line_id': allocation.wms_line_id,
            'source_run_id': allocation.wms_line.source_run_id,
            'source_run_status': allocation.wms_line.source_run.status,
            'source_run_failed_count': allocation.wms_line.source_run.failed_count,
            'receipt_line_id': allocation.receipt_line_id})
    latest_unmatched = {}
    for row in upstream.values('pk', 'internal_sku_id', 'warehouse_id', 'received_quantity', 'received_at_utc', 'updated_at_utc',
            'source_run_id', 'source_run__status', 'source_run__failed_count').order_by('pk'):
        source_rows[row['internal_sku_id']]['wms'].append(row)
        if linked[row['pk']] == row['received_quantity']:
            continue
        identity = (row['internal_sku_id'], row['warehouse_id'])
        moment = row['received_at_utc'] or row['updated_at_utc']
        latest_unmatched[identity] = max(latest_unmatched.get(identity, moment), moment)
    scope_unattributable = set()
    for line in shipments.values('pk', 'shipment_id', 'sku_id', 'quantity', 'excess_quantity', 'exception_type',
            'shipment__version', 'shipment__updated_at', 'shipment__status'):
        item = result[line['sku_id']]
        line_allocations = allocations_by_line.get(line['pk'], [])
        received_rows = receipts_by_line.get(line['pk'], [])
        total_received = sum(row.received_quantity for row in received_rows)
        if restricted:
            # Shipment-line exceptions have no warehouse of their own. Attribute the
            # whole line only when all of it is assigned to exactly one in-scope warehouse.
            destinations = set()
            unknown_destination = False
            for allocation in line_allocations:
                batch = allocation.membership.batch
                destination = next((r.receipt.warehouse_id for r in received_rows
                                    if r.receipt.inbound.batch_id == batch.pk), batch.planned_warehouse_id)
                if destination is None:
                    unknown_destination = True
                else:
                    destinations.add(destination)
            allocated_total = sum(row.quantity for row in line_allocations)
            wholly_out_of_scope = (destinations and not unknown_destination and
                                   destinations.isdisjoint(warehouse_ids) and allocated_total == line['quantity'])
            if wholly_out_of_scope:
                count_line_exceptions = False
            elif (not unknown_destination and len(destinations) == 1 and
                  destinations.issubset(warehouse_ids) and allocated_total == line['quantity']):
                count_line_exceptions = True
            else:
                count_line_exceptions = False
                scope_unattributable.add(line['sku_id'])
        else:
            count_line_exceptions = True
        if count_line_exceptions:
            item['excess_shipped'] += line['excess_quantity']
            item['additional_shipped'] += line['quantity'] if line['exception_type'] == 'additional' else 0
        source_rows[line['sku_id']]['shipment'].append({'id': line['pk'], 'shipment_id': line['shipment_id'],
            'quantity': line['quantity'], 'excess_quantity': line['excess_quantity'],
            'exception_type': line['exception_type'], 'shipment_status': line['shipment__status'],
            'shipment_version': line['shipment__version'], 'shipment_updated_at': line['shipment__updated_at']})
        if total_received > line['quantity']:
            item['issues'].append('shipment_receipt_overallocated')
        for receipt in received_rows:
            if restricted and receipt.receipt.warehouse_id not in warehouse_ids:
                continue
            reconciled = min(receipt.received_quantity, matched.get(receipt.pk, 0))
            item['received_awaiting_wms'] += receipt.received_quantity - reconciled
            item['wms_received'] += reconciled
            if receipt.pk in invalid:
                item['issues'].append('wms_allocation_requires_review')
            # Local receipts and WMS-confirmed receipts are excluded from pipeline supply.
        allocated_total = sum(row.quantity for row in line_allocations)
        if allocated_total > line['quantity']:
            item['issues'].append('dispatch_allocation_overallocated')
        if total_received != line['quantity'] and total_received:
            item['issues'].append('local_receipt_quantity_difference')
        for allocation in line_allocations:
            batch = allocation.membership.batch
            destination = next((r.receipt.warehouse_id for r in received_rows
                                if r.receipt.inbound.batch_id == batch.pk), batch.planned_warehouse_id)
            if restricted and destination not in warehouse_ids:
                if destination is None and 'unassigned_warehouse_supply' not in item['issues']:
                    item['issues'].append('unassigned_warehouse_supply')
                continue
            batch_received = receipts_by_batch_line[(line['pk'], batch.pk)]
            remaining = max(0, allocation.quantity - batch_received)
            if not remaining:
                continue
            if batch.stage == 'arrived_warehouse':
                item['arrived_unchecked'] += remaining
                continue
            stage = 'transporting' if batch.stage in ['departed', 'arrived_port'] else 'awaiting_dispatch'
            item[stage] += remaining
            eta = batch.expected_warehouse_date
            if eta is None:
                item['unknown_eta'] += remaining
                item['eta_rows'].append({'expected_date': None, 'quantity': remaining,
                    'batch_id': batch.pk, 'batch_number': batch.number, 'stage': batch.stage})
            elif eta < today:
                item['issues'].append('overdue_eta')
                item['eta_rows'].append({'expected_date': eta.isoformat(), 'quantity': remaining,
                    'batch_id': batch.pk, 'batch_number': batch.number, 'stage': batch.stage, 'overdue': True})
            elif eta <= today + timedelta(days=target_days):
                item['effective_incoming'] += remaining
                item['eta_rows'].append({'expected_date': eta.isoformat(), 'quantity': remaining,
                    'batch_id': batch.pk, 'batch_number': batch.number, 'stage': batch.stage})
                sent_at = batch.departed_at or batch.created_at
                overlap = any(moment >= sent_at for (sku_id, warehouse_id), moment in latest_unmatched.items()
                    if sku_id == line['sku_id'] and (batch.planned_warehouse_id is None or warehouse_id == batch.planned_warehouse_id))
                if overlap:
                    item['issues'].append('wms_receipt_overlap_unresolved')
            else:
                item['eta_rows'].append({'expected_date': eta.isoformat(), 'quantity': remaining,
                    'batch_id': batch.pk, 'batch_number': batch.number, 'stage': batch.stage, 'outside_horizon': True})
        # Shipment quantity not allocated to an active batch remains at the supplier.
        unallocated = max(0, line['quantity'] - allocated_total)
        if unallocated:
            if restricted:
                item['issues'].append('warehouse_supply_scope_incomplete')
            else:
                # Submitted supplier shipment lines are already shipped; an unallocated
                # remainder awaits assignment to a dispatch batch, not production.
                item['awaiting_dispatch'] += unallocated
                item['unknown_eta'] += unallocated
                item['eta_rows'].append({'expected_date': None, 'quantity': unallocated,
                    'batch_id': None, 'batch_number': '', 'stage': 'awaiting_dispatch'})
    for value in result.values():
        if value['unknown_eta']:
            value['issues'].append('unknown_eta')
        value['issues'] = sorted(set(value['issues']))
        if 'wms_receipt_overlap_unresolved' in value['issues']:
            value['effective_incoming'] = None
    for sku_id in scope_unattributable:
        result[sku_id]['excess_shipped'] = None
        result[sku_id]['additional_shipped'] = None
        result[sku_id]['issues'].append('warehouse_supply_scope_incomplete')
        result[sku_id]['issues'] = sorted(set(result[sku_id]['issues']))
    for sku_id in sku_ids:
        result[sku_id]['supply_basis_signature'] = request_hash(source_rows[sku_id])
        result[sku_id]['open_demand_signature'] = signature
    return result
