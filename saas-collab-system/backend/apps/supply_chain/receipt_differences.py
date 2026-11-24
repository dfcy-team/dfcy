"""Read-only counted differences and append-only manual payable decisions."""
import hashlib,json
from decimal import Decimal
from collections import defaultdict
from django.db import transaction
from django.db.models import Sum, Exists, OuterRef
from rest_framework.exceptions import ValidationError, NotFound
from rest_framework.response import Response
from rest_framework import serializers
from .views import InternalAPI
from .permissions import VIEW, internal_orders
from .shipment_sources import accessible_shipments
from .models import PurchaseOrder, InboundLine, InboundExtraLine, ReceiptDifferenceDecision, SettlementRecord, SupplierShipment, InboundOrder
from . import services

ZERO = Decimal('0')
OPTIONS = {'wrong_item_net_settlement', 'supplier_waived', 'historical_paid', 'pending_review'}


class DecisionInput(serializers.Serializer):
    keys=serializers.ListField(child=serializers.CharField(max_length=100),allow_empty=False,max_length=1000)
    option=serializers.ChoiceField(choices=sorted(OPTIONS))
    reason=serializers.CharField(max_length=2000,allow_blank=True,default='')
    expected_versions=serializers.DictField(child=serializers.IntegerField(min_value=0))
    adjust_previous=serializers.BooleanField(default=False)
    preview_token=serializers.CharField(required=False,max_length=64)


def input_data(data):
    serializer=DecisionInput(data=data);serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def payable_delta(shipment):
    return ReceiptDifferenceDecision.objects.filter(tenant_id=shipment.tenant_id, shipment=shipment).aggregate(total=Sum('payable_delta'))['total'] or ZERO


def _shipment_currencies(actor,sources):
    from .cost_models import PaymentPlanRecord,PayableClassificationRecord
    codes=defaultdict(set)
    for model in (PaymentPlanRecord,PayableClassificationRecord):
        seen=set()
        for sid,currency in model.objects.filter(tenant_id=actor.tenant_id,kind='shipment',shipment_id__in=sources).order_by('pk').values_list('shipment_id','currency'):
            if sid not in seen:
                seen.add(sid)
                if currency:codes[sid].add(currency)
    return {sid:next(iter(codes[sid])) if len(codes[sid])==1 else None for sid in sources}


def rows_for(actor,keys=None):
    shipments = accessible_shipments(internal_orders(actor, PurchaseOrder.objects.all(), VIEW)).filter(tenant_id=actor.tenant_id).select_related('order__supplier')
    if keys:
        line_ids=[int(k.split(':')[1]) for k in keys if k.startswith('line:') and k.split(':')[1].isdigit()]
        extra_ids=[int(k.split(':')[1]) for k in keys if k.startswith('extra:') and k.split(':')[1].isdigit()]
        extra_inbounds=InboundExtraLine.objects.filter(tenant_id=actor.tenant_id,pk__in=extra_ids).values_list('inbound_id',flat=True)
        from django.db.models import Q
        ids=InboundLine.objects.filter(tenant_id=actor.tenant_id).filter(Q(pk__in=line_ids)|Q(inbound_id__in=extra_inbounds)).values_list('shipment_line__shipment_id',flat=True)
        shipments=shipments.filter(pk__in=ids)
    sources = {s.pk: s for s in shipments.filter(status='submitted')}
    currencies=_shipment_currencies(actor,sources)
    decisions = list(ReceiptDifferenceDecision.objects.filter(tenant_id=actor.tenant_id).select_related('reversal').order_by('pk'))
    active = {d.source_key: d for d in decisions if d.option!='assigned' and not d.reverses_id and not hasattr(d, 'reversal')}
    assigned = {d.source_key:d for d in decisions if d.option=='assigned'}
    versions = {d.source_key: d.pk for d in decisions}
    rows = []
    from . import dispatch_allocations
    valid=dispatch_allocations.active().filter(shipment_line_id=OuterRef('shipment_line_id'),membership__batch_id=OuterRef('inbound__batch_id'))
    actual_totals = defaultdict(int)
    source_quantities = {}
    for line in InboundLine.objects.filter(tenant_id=actor.tenant_id, shipment_line__shipment_id__in=sources, inbound__status='confirmed', inbound__batch__status='active').filter(Exists(valid)).select_related('shipment_line__sku','inbound'):
        source = line.shipment_line
        if line.received_quantity is not None:
            actual_totals[source.pk] += line.received_quantity
        source_quantities[source.pk] = source.quantity
        if line.received_quantity is None or line.received_quantity == line.expected_quantity:
            continue
        shipment = sources[source.shipment_id]
        qty = line.received_quantity-line.expected_quantity
        key = 'line:'+str(line.pk)
        decision = active.get(key)
        rows.append(dict(key=key,type='over' if qty>0 else 'short',supplier_id=shipment.order.supplier_id,supplier_name=shipment.order.supplier.name,currency='CNY',shipment_id=shipment.pk,shipment_number=shipment.number,inbound_id=line.inbound_id,inbound_number=line.inbound.number,sku=source.sku_code_snapshot,new_sku=source.sku.sku_code or source.sku_code_snapshot,old_sku=source.sku.legacy_sku_code or '',expected_quantity=line.expected_quantity,received_quantity=line.received_quantity,difference_quantity=qty,unit_price=str(source.unit_price) if source.unit_price is not None else None,amount=str(abs(qty)*source.unit_price) if source.unit_price is not None else None,status='processed' if decision else 'pending',decision_id=decision.pk if decision else None,version=versions.get(key,0)))
    inbound_ids = InboundLine.objects.filter(shipment_line__shipment_id__in=sources,tenant_id=actor.tenant_id).values_list('inbound_id',flat=True)
    inbound_shipments=defaultdict(set)
    for inbound_id,shipment_id in InboundLine.objects.filter(tenant_id=actor.tenant_id,inbound_id__in=inbound_ids).values_list('inbound_id','shipment_line__shipment_id'):
        inbound_shipments[inbound_id].add(shipment_id)
    for extra in InboundExtraLine.objects.filter(tenant_id=actor.tenant_id,inbound_id__in=inbound_ids,inbound__status='confirmed',inbound__batch__status='active',is_active=True).select_related('inbound','sku'):
        key='extra:'+str(extra.pk)
        ids=inbound_shipments[extra.inbound_id]
        candidates=[dict(shipment_id=s.pk,shipment_number=s.number,supplier_id=s.order.supplier_id,supplier_name=s.order.supplier.name) for s in sources.values() if s.pk in ids]
        assignment=assigned.get(key)
        chosen=sources.get(assignment.shipment_id) if assignment and assignment.shipment_id in ids else None
        if not chosen and len(ids)==1 and len(candidates)==1:chosen=sources[candidates[0]['shipment_id']]
        decision=active.get(key)
        rows.append(dict(key=key,type='over',supplier_id=chosen.order.supplier_id if chosen else None,supplier_name=chosen.order.supplier.name if chosen else '待归属',currency='CNY',shipment_id=chosen.pk if chosen else None,shipment_number=chosen.number if chosen else '',inbound_id=extra.inbound_id,inbound_number=extra.inbound.number,sku=extra.sku_code_snapshot,new_sku=extra.sku.sku_code or extra.sku_code_snapshot,old_sku=extra.legacy_sku_code_snapshot or extra.sku.legacy_sku_code or '',expected_quantity=0,received_quantity=extra.received_quantity,difference_quantity=extra.received_quantity,unit_price=str(extra.unit_price) if extra.unit_price is not None else None,amount=str(extra.received_quantity*extra.unit_price) if extra.unit_price is not None else None,status='unassigned' if not chosen else ('processed' if decision else 'pending'),decision_id=decision.pk if decision else None,version=versions.get(key,0),assignment_candidates=candidates))
    # The existing payable projection already nets receipt quantities for the
    # same shipment line. Only net surplus may add to the payable a second time.
    line_sources={r['key']:r for r in rows if r['key'].startswith('line:')}
    ids=[int(k.split(':')[1]) for k in line_sources]
    mapping=dict(InboundLine.objects.filter(pk__in=ids,tenant_id=actor.tenant_id).values_list('pk','shipment_line_id'))
    groups=defaultdict(list)
    for row in line_sources.values():groups[mapping[int(row['key'].split(':')[1])]].append(row)
    for group in groups.values():
        source_id = mapping[int(group[0]['key'].split(':')[1])]
        # Original payable already includes the entire shipped quantity. A
        # partial receipt surplus cannot charge those planned units again.
        surplus = max(actual_totals[source_id] - source_quantities[source_id], 0)
        for row in sorted(group,key=lambda r:r['key']):
            take=min(surplus,max(row['difference_quantity'],0));surplus-=take
            row['payable_increment']=str(Decimal(row['unit_price'])*take) if row['unit_price'] is not None else None
            row['shipment_line_id']=mapping[int(row['key'].split(':')[1])]
    from .document_time import document_time
    inbounds={obj.pk:obj for obj in InboundOrder.objects.filter(tenant_id=actor.tenant_id,pk__in={r['inbound_id'] for r in rows}).select_related('batch')}
    inbound_dates={pk:document_time('inbound',obj) for pk,obj in inbounds.items()}
    history_records=defaultdict(list)
    for record in SettlementRecord.objects.filter(tenant_id=actor.tenant_id,shipment_id__in=sources,current_revision__notes__startswith='HIST-PH-COUNT-20261106').select_related('current_revision'):
        history_records[record.shipment_id].append(record)
    for row in rows:
        row['document_date']=inbound_dates.get(row['inbound_id'])
        row['currency']=currencies.get(row['shipment_id'])
        row['country_id']=inbounds[row['inbound_id']].batch.country_id
        row.setdefault('payable_increment',row['amount'] if row['type']=='over' else '0')
        records=history_records.get(row['shipment_id'],[])
        row['history_candidates']=[dict(revision_id=r.current_revision_id,amount=str(r.current_revision.recorded_amount),notes=r.current_revision.notes,reference_number=r.current_revision.reference_number) for r in records]
    return rows


class ReceiptDifferences(InternalAPI):
    def get(self,request):
        rows=rows_for(request.user)
        country=request.query_params.get('country') or request.query_params.get('country_id')
        if country:
            if not country.isdigit():raise ValidationError('国家筛选无效。')
            rows=[r for r in rows if r['country_id']==int(country)]
        if request.query_params.get('supplier_id'):
            rows=[r for r in rows if str(r['supplier_id'])==request.query_params['supplier_id']]
        if request.query_params.get('status'):
            rows=[r for r in rows if r['status']==request.query_params['status']]
        for key,compare in [('start_date',lambda x,y:x>=y),('end_date',lambda x,y:x<=y)]:
            value=request.query_params.get(key)
            if value:
                from datetime import date
                try:date.fromisoformat(value)
                except (ValueError,TypeError):raise ValidationError('日期格式无效。')
                rows=[r for r in rows if r['document_date'] and compare(r['document_date'][:10],value)]
        keyword=request.query_params.get('query','').strip().casefold()
        if keyword:
            from .shipment_sources import prepare_source_orders
            shipments=list(SupplierShipment.objects.filter(tenant_id=request.user.tenant_id,pk__in={r['shipment_id'] for r in rows if r['shipment_id']}).select_related('order'))
            prepare_source_orders(shipments)
            matched=set()
            for shipment in shipments:
                documents=[shipment,*shipment._source_orders]
                if any(keyword in str(getattr(doc,field,'') or '').casefold() for doc in documents for field in ('number','notes')):
                    matched.add(shipment.pk)
            inbounds=InboundOrder.objects.filter(tenant_id=request.user.tenant_id,pk__in={r['inbound_id'] for r in rows})
            inbound_matches={doc.pk for doc in inbounds if any(keyword in str(getattr(doc,field,'') or '').casefold() for field in ('number','notes'))}
            rows=[r for r in rows if r['shipment_id'] in matched or r['inbound_id'] in inbound_matches]
        totals={}
        for r in rows:
            t=totals.setdefault((r['supplier_id'],r['currency']),dict(supplier_id=r['supplier_id'],supplier_name=r['supplier_name'],currency=r['currency'],over_amount=ZERO,short_amount=ZERO,pending_count=0))
            t[r['type']+'_amount']+=Decimal(r['amount'] or '0');t['pending_count']+=r['status']=='pending'
        return Response({'data':dict(rows=rows,suppliers=list(totals.values()))})


def preview(actor,data):
    data=input_data(data)
    keys=data.get('keys',[])
    if not isinstance(keys,list) or not keys or len(keys)!=len(set(keys)):
        raise ValidationError('请选择不重复的差异明细。')
    rows={r['key']:r for r in rows_for(actor,keys)}
    if any(k not in rows for k in keys):raise NotFound('差异明细不可访问或已变化。')
    selected=[rows[k] for k in keys]
    if any(not r['currency'] for r in selected):raise ValidationError('单据币种待确认，请先在付款安排或应付分类中维护币种。')
    if any(r['status']=='unassigned' for r in selected):raise ValidationError('额外商品需先核实供应商归属。')
    if len({(r['supplier_id'],r['currency']) for r in selected})!=1:raise ValidationError('仅可处理同供应商同币种差异。')
    if any(r['amount'] is None for r in selected):raise ValidationError('请先核实差异商品单价。')
    if any(data.get('expected_versions',{}).get(r['key'])!=r['version'] for r in selected):raise ValidationError('差异记录已变化，请刷新。')
    if data.get('option') not in OPTIONS:raise ValidationError('请选择处理方式。')
    short=sum((Decimal(r['amount']) for r in selected if r['type']=='short'),ZERO)
    over=sum((Decimal(r['amount']) for r in selected if r['type']=='over'),ZERO)
    increment=sum((Decimal(r['payable_increment']) for r in selected if r['type']=='over'),ZERO) if data['option']=='wrong_item_net_settlement' else ZERO
    from . import costs
    shipment_ids=sorted({r['shipment_id'] for r in selected})
    summaries=[costs.payment_summary(actor,'shipment',sid)['summary'] for sid in shipment_ids]
    fields={'due_before':'due_amount','cash_paid':'cash_paid_amount','historical_settled':'historical_difference_settled_amount'}
    amounts={out:str(sum((Decimal(s.get(field) or '0') for s in summaries),ZERO)) for out,field in fields.items()}
    previous_decisions=list(ReceiptDifferenceDecision.objects.filter(pk__in=[r['decision_id'] for r in selected if r['decision_id']],tenant_id=actor.tenant_id).select_related('created_by'))
    history_restorations=[]
    if data['option']!='pending_review':
        for decision in previous_decisions:
            applied=decision.source_snapshot.get('history_applied')
            if applied:
                history_restorations.append(dict(decision_id=decision.pk,shipment_id=decision.shipment_id,
                    revision_id=applied['revision_id'],amount=str(Decimal(str(applied['amount'])))))
    previous=sum((r.payable_delta for r in previous_decisions),ZERO)
    increment=increment-previous if data['option']!='pending_review' else ZERO
    amounts['due_after']=str(Decimal(amounts['due_before'])+increment)
    from .receipt_difference_history import preview_history
    history = []
    if data['option']=='wrong_item_net_settlement' or history_restorations:
        history=preview_history(actor, selected if data['option']=='wrong_item_net_settlement' else [],
            restoring=previous_decisions if data['option']!='pending_review' else ())
    balances={sid:Decimal(summary.get('due_amount') or '0')-Decimal(summary.get('paid_amount') or '0')-Decimal(summary.get('applied_amount') or '0') for sid,summary in zip(shipment_ids,summaries)}
    for row in selected:
        old=next((d.payable_delta for d in previous_decisions if d.pk==row['decision_id']),ZERO)
        delta=Decimal(row['payable_increment']) if row['type']=='over' and data['option']=='wrong_item_net_settlement' else ZERO
        balances[row['shipment_id']]+=delta-old if data['option']!='pending_review' else ZERO
    for restore in history_restorations:
        # Restoring a prior historical settlement increases the historical
        # settled amount, reducing the supplier balance by this exact amount.
        balances[restore['shipment_id']]-=Decimal(restore['amount'])
    for plan in history:
        for row in selected:
            if row['key'] in plan.get('allocations',{}):balances[row['shipment_id']]+=Decimal(plan['allocations'][row['key']])
    amounts.update(remaining_after=str(sum((max(x,ZERO) for x in balances.values()),ZERO)),prepaid_balance_after=str(sum((max(-x,ZERO) for x in balances.values()),ZERO)))
    details=[dict(id=d.pk,option=d.option,reason=d.reason,amount=str(d.payable_delta),created_at=d.created_at,created_by=d.created_by.full_name or d.created_by.username) for d in previous_decisions]
    token=hashlib.sha256(json.dumps(dict(rows=selected,history=history,history_restorations=history_restorations,amounts=amounts,option=data['option']),sort_keys=True,default=str).encode()).hexdigest()
    return dict(preview_token=token,rows=selected,short_amount=str(short),over_amount=str(over),net_difference_amount=str(over-short),incremental_adjustment=str(increment),requires_adjust_previous=any(r['status']=='processed' for r in selected) or bool(history),history_adjustments=history,history_restorations=history_restorations,previous_decisions=details,**amounts)


class ReceiptDifferencePreview(InternalAPI):
    def post(self,request):
        services._internal(request.user)
        return Response({'data':preview(request.user,request.data)})


class ReceiptDifferenceSettle(InternalAPI):
    @transaction.atomic
    def post(self,request):
        services._internal(request.user);services._tenant_lock(request.user)
        data=input_data(request.data)
        request_key=request.headers.get('Idempotency-Key','')
        if not request_key or len(request_key)>128:raise ValidationError('缺少有效操作标识。')
        prior=list(ReceiptDifferenceDecision.objects.filter(tenant_id=request.user.tenant_id,request_key=request_key))
        if prior:
            if set(d.source_key for d in prior)!=set(data.get('keys',[])) or any(d.option!=data.get('option') or d.reason!=data.get('reason','').strip() for d in prior):raise ValidationError('操作标识已被其他请求使用。')
            return Response({'data':dict(decision_ids=[d.pk for d in prior],replayed=True)})
        result=preview(request.user,data)
        if data.get('preview_token')!=result['preview_token']:raise ValidationError('预览金额或来源已变化，请重新预览后确认。')
        reason=data.get('reason','').strip()
        if not reason:raise ValidationError('请填写处理依据。')
        if result['requires_adjust_previous'] and not data.get('adjust_previous'):raise ValidationError('请确认调整原处理。')
        from .payment_request_models import SupplyPaymentRequest
        ids={r['shipment_id'] for r in result['rows']}
        if set(services._internal_shipments(request.user).filter(pk__in=ids).values_list('pk',flat=True))!=ids:raise NotFound('发货单不在可管理范围。')
        if SupplyPaymentRequest.objects.filter(tenant_id=request.user.tenant_id,kind='shipment',source_id__in=ids,status__in=['submitted','pending','approved']).exists():raise ValidationError('存在进行中的付款申请，请先处理申请。')
        from .receipt_difference_history import confirm_history, restore_history
        created=[]
        if data['option']=='pending_review':return Response({'data':result})
        with services.domain_write():
            if data.get('adjust_previous'):
                for row in result['rows']:
                    if row['decision_id']:
                        old=ReceiptDifferenceDecision.objects.get(pk=row['decision_id'],tenant_id=request.user.tenant_id)
                        restore_history(request.user,old,reason)
                        import hashlib
                        reverse_key='previous:'+hashlib.sha256(request_key.encode()).hexdigest()
                        ReceiptDifferenceDecision.objects.create(tenant_id=request.user.tenant_id,created_by=request.user,shipment=old.shipment,source_key=old.source_key,option='reversed',payable_delta=-old.payable_delta,source_snapshot=old.source_snapshot,reason=reason,request_key=reverse_key,reverses=old)
            plans=confirm_history(request.user,result['rows'],reason,request_key) if data.get('adjust_previous') and data['option']=='wrong_item_net_settlement' else []
            def financial_plan_signature(items):
                return sorted((item['record_id'], Decimal(item['reduction']),
                    tuple(sorted((key, Decimal(value)) for key, value in item['allocations'].items()))) for item in items)
            if financial_plan_signature(plans) != financial_plan_signature(result['history_adjustments']):
                raise ValidationError('历史款调整与预览不一致，请刷新后重新核实。')
            for row in result['rows']:
                snapshot=dict(row)
                for plan in plans:
                    if row['key'] in plan['allocations']:
                        snapshot['history_applied']=dict(revision_id=plan['revision_id'],amount=plan['allocations'][row['key']])
                delta=Decimal(row['payable_increment']) if row['type']=='over' and data['option']=='wrong_item_net_settlement' else ZERO
                item=ReceiptDifferenceDecision.objects.create(tenant_id=request.user.tenant_id,created_by=request.user,shipment_id=row['shipment_id'],source_key=row['key'],option=data['option'],payable_delta=delta,source_snapshot=snapshot,reason=reason,request_key=request_key)
                created.append(item.pk)
        return Response({'data':dict(result,decision_ids=created)},status=201)


class ReceiptDifferenceReverse(InternalAPI):
    @transaction.atomic
    def post(self,request,pk):
        services._internal(request.user);services._tenant_lock(request.user)
        visible={r['shipment_id'] for r in rows_for(request.user)}
        original=ReceiptDifferenceDecision.objects.filter(pk=pk,tenant_id=request.user.tenant_id,shipment_id__in=visible,reverses__isnull=True).first()
        if not original:raise NotFound('原处理记录不可访问。')
        if not services._internal_shipments(request.user).filter(pk=original.shipment_id).exists():raise NotFound('发货单不在可管理范围。')
        if hasattr(original,'reversal'):raise ValidationError('该处理已撤销，请刷新。')
        from .payment_request_models import SupplyPaymentRequest
        if SupplyPaymentRequest.objects.filter(tenant_id=request.user.tenant_id,kind='shipment',source_id=original.shipment_id,status='submitted').exists():raise ValidationError('存在进行中的付款申请，请先处理申请。')
        reason=request.data.get('reason','').strip()
        if not reason:raise ValidationError('请填写调整原因。')
        with services.domain_write():
            from .receipt_difference_history import restore_history
            restore_history(request.user,original,reason)
            item=ReceiptDifferenceDecision.objects.create(tenant_id=request.user.tenant_id,created_by=request.user,shipment=original.shipment,source_key=original.source_key,option='reversed',payable_delta=-original.payable_delta,source_snapshot=original.source_snapshot,reason=reason,request_key='reverse:'+str(pk),reverses=original)
        return Response({'data':{'id':item.pk}})


class ReceiptDifferenceAssign(InternalAPI):
    @transaction.atomic
    def post(self,request):
        services._internal(request.user);services._tenant_lock(request.user)
        row=next((r for r in rows_for(request.user) if r['key']==request.data.get('key')),None)
        if not row or not row['key'].startswith('extra:'):raise NotFound('额外商品不可访问。')
        if row['status']=='processed':raise ValidationError('请先撤销原结算处理再调整归属。')
        candidate=next((r for r in row['assignment_candidates'] if r['shipment_id']==request.data.get('shipment_id')),None)
        if not candidate:raise ValidationError('请选择同入库关联且可访问的发货单。')
        if not services._internal_shipments(request.user).filter(pk=candidate['shipment_id']).exists():raise NotFound('发货单不在可管理范围。')
        reason=request.data.get('reason','').strip()
        if not reason:raise ValidationError('请填写归属依据。')
        with services.domain_write():
            item=ReceiptDifferenceDecision.objects.create(tenant_id=request.user.tenant_id,created_by=request.user,shipment_id=candidate['shipment_id'],source_key=row['key'],option='assigned',source_snapshot=row,reason=reason,request_key='assign:'+row['key']+':'+str(row['version']))
        return Response({'data':{'id':item.pk}})


class ReceiptDifferenceHistoryBind(InternalAPI):
    @transaction.atomic
    def post(self,request):
        services._internal(request.user);services._tenant_lock(request.user)
        row=next((r for r in rows_for(request.user) if r['key']==request.data.get('key')),None)
        if not row:raise NotFound('差异明细不可访问。')
        if not services._internal_shipments(request.user).filter(pk=row['shipment_id']).exists():raise NotFound('发货单不在可管理范围。')
        request_key=request.headers.get('Idempotency-Key','')
        if not request_key or len(request_key)>128:raise ValidationError('缺少有效操作标识。')
        from .receipt_difference_history import bind_history
        try:
            amount=Decimal(str(request.data.get('amount')))
            if not amount.is_finite() or amount<=ZERO or amount!=amount.quantize(Decimal('.0001')):raise ValueError()
        except Exception:raise ValidationError('归属金额必须是四位小数以内的正数。')
        revision=bind_history(request.user,[row],request.data.get('revision_id'),{row['key']:str(amount)},request.data.get('reason',''),request_key)
        return Response({'data':{'revision_id':revision}})
