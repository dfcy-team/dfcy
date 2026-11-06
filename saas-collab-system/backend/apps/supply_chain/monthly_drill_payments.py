"""Read-only payment and discrepancy projections for one authorized shipment."""
from collections import defaultdict
from decimal import Decimal

from . import costs, domestic_freight
from .models import BusinessEvent, PaymentRecord, PaymentVoucher


def _proofs(tenant_id, records, revision):
    result = defaultdict(list)
    base = '/api/internal/supply-chain/v2/costs'
    for payment, vid, name in PaymentVoucher.objects.filter(
            tenant_id=tenant_id, payment_id__in=records).values_list('payment_id','id','file_name'):
        kind, owner = records[payment]
        result[payment].append({'id':vid,'file_name':name,'download_path':
            f'{base}/{kind}/{owner}/payments/{payment}/vouchers/{vid}/download/'})
    if revision:
        shipment_id = revision.settlement.shipment_id
        for vid, name in PaymentVoucher.objects.filter(tenant_id=tenant_id,
                settlement_revision=revision).values_list('id','file_name'):
            result['historical'].append({'id':vid,'file_name':name,'download_path':
                f'{base}/shipment/{shipment_id}/settlements/{revision.pk}/vouchers/{vid}/download/'})
    return result


def _entry(event, source, number, source_amount, vouchers, cutoff, ref):
    signed = -event.amount if event.reverses_id else event.amount
    return {'id':event.pk,'source':source,'source_number':number,'amount':str(signed),
        'source_amount':str(source_amount) if source_amount is not None else None,'date':str(event.date),
        'reference_number':ref,'is_reversal':bool(event.reverses_id),'after_cutoff':event.date>cutoff,
        'vouchers':vouchers}


def payment_details(shipment, orders, direct, applications, revision, cutoff):
    domestic = list(PaymentRecord.objects.filter(shipment=shipment, tenant_id=shipment.tenant_id,
        purpose='domestic_freight').order_by('date','pk'))
    records = {p.pk:('shipment',shipment.pk) for p in direct}
    records.update({p.pk:('domestic_freight',shipment.pk) for p in domestic})
    visible_orders = dict(orders.filter(pk__in={a.prepayment.purchase_order_id for a in applications})
                          .values_list('pk','number'))
    records.update({a.prepayment_id:('purchase',a.prepayment.purchase_order_id) for a in applications
                    if a.prepayment.purchase_order_id in visible_orders})
    proofs = _proofs(shipment.tenant_id,records,revision)
    payments = [_entry(p,'发货单直接付款',shipment.number,p.amount,proofs[p.pk],cutoff,p.reference_number)
                for p in direct]
    for app in applications:
        p = app.prepayment
        visible = p.purchase_order_id in visible_orders
        payments.append(_entry(app,'采购定金抵扣',visible_orders.get(p.purchase_order_id,'采购付款'),
            p.amount if visible else None,proofs[p.pk] if visible else [],cutoff,p.reference_number if visible else ''))
    if revision and revision.recorded_amount:
        payments.append({'id':f'history-{revision.pk}','date':str(revision.date),'source':'历史已付登记',
            'source_number':shipment.number,'amount':str(revision.recorded_amount),
            'source_amount':None,'reference_number':revision.reference_number,
            'after_cutoff':revision.date>cutoff,'vouchers':proofs['historical']})
    due = costs.settlement_amount('domestic_freight',shipment)
    paid = sum((-p.amount if p.reverses_id else p.amount for p in domestic),Decimal(0))
    labels = {'company_direct':'我司直付承运商','supplier_advance':'供应商代垫','supplier_borne':'供应商自担'}
    return sorted(payments,key=lambda row:row['date']), {
        'mode_label':labels[domestic_freight.settlement_mode(shipment)],'due_amount':None if due is None else str(due),
        'paid_amount':str(paid),'remaining_amount':None if due is None else str(max(due-paid,0)),
        'payments':[_entry(p,'国内运费付款',shipment.number,p.amount,proofs[p.pk],cutoff,p.reference_number)
                    for p in domestic]}


def difference_choices(shipment, revision):
    events = BusinessEvent.objects.filter(tenant_id=shipment.tenant_id, aggregate_id=shipment.pk,
        aggregate_type='suppliershipment',action__in=['count_difference_case_seeded',
        'count_difference_choice_saved']).order_by('pk').values_list('action','payload')
    seeds, selections = {}, {}
    for action, payload in events:
        purchase = payload.get('source_purchase_id')
        (seeds if action=='count_difference_case_seeded' else selections)[purchase] = payload
    labels = {'supplement_supplier':'补付供应商','supplier_waived':'供应商免收','return_goods':'退回商品',
              'wrong_item_net_settlement':'错发换款／按净差结算','pending_review':'继续待核'}
    settled = revision and revision.notes.startswith('HIST-PH-COUNT-20261106')
    result = []
    for purchase,seed in seeds.items():
        choice = selections.get(purchase,{})
        result.append({'source_purchase':seed.get('source_purchase'),'source_shipment':seed.get('source_shipment'),
            'amount':seed['difference_amount'],'option_label':'历史已付款' if settled else
            labels.get(choice.get('option','pending_review'),'继续待核'),'notes':choice.get('notes',''),
            'net_difference_amount':choice.get('net_difference_amount'),
            'href':f'/count-difference-choices/?shipment_id={shipment.pk}&purchase_id={purchase}'})
    return result
