"""Grouped supplier/freight payment requests with one approval and atomic posting."""
import hashlib
from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.db.models import Sum, Prefetch, Q, Exists, OuterRef, Subquery
from django.http import FileResponse
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from . import costs, services
from .api import key
from .cost_models import PaymentRecord
from .models import domain_write, SupplierShipment, DispatchBatch, InboundOrder, PurchaseOrder
from .payment_item_models import PaymentItem
from .payment_request_models import SupplyPaymentRequest as PR, SupplyPaymentBatch as Batch, SupplyPaymentBatchVoucher as Voucher
from .payment_requests import _snap, _current, finance_allowed
from .payment_request_evidence import ConfirmInput, conflict
from .payment_vouchers import _validate_file
from .permissions import MANAGE, VIEW
from .views import InternalAPI
from apps.permissions.services import check_user_permission
from apps.workflows.permissions import scope_allows_value
from apps.workflows.models import ApprovalRequest

KINDS = ('shipment', 'domestic_freight', 'batch', 'inbound')

class CreateInput(serializers.Serializer):
    payee_account_id = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=10000)
    lines = serializers.ListField(min_length=2, max_length=20, child=serializers.DictField())

class LineInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=KINDS)
    source_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('.0001'))
    fee_item_id = serializers.IntegerField(min_value=1, required=False)

def _party(kind, obj):
    owner = costs._payee_owner(kind, obj)
    return ('supplier', owner['supplier_id']) if 'supplier_id' in owner else ('freight_company', owner['freight_company_id'])

def visible_batches(actor):
    """Require every child source in scope, before database pagination."""
    from .permissions import accessible_orders
    from .logistics import batches_for
    orders = accessible_orders(actor, PurchaseOrder.objects.all(), VIEW)
    shipments = SupplierShipment.objects.filter(tenant_id=actor.tenant_id, order__in=orders)
    dispatches = batches_for(actor, VIEW)
    inbounds = InboundOrder.objects.filter(tenant_id=actor.tenant_id, batch__in=dispatches)
    allowed = (Q(kind='shipment', source_id__in=Subquery(shipments.values('pk'))) |
        Q(kind='domestic_freight', source_id__in=Subquery(shipments.filter(domestic_carrier__isnull=False).values('pk'))) |
        Q(kind='batch', source_id__in=Subquery(dispatches.values('pk'))) |
        Q(kind='inbound', source_id__in=Subquery(inbounds.values('pk'))))
    lines = PR.objects.filter(tenant_id=actor.tenant_id, batch_id=OuterRef('pk'))
    return Batch.objects.filter(tenant_id=actor.tenant_id).annotate(
        has_lines=Exists(lines), denied_line=Exists(lines.exclude(allowed))).filter(has_lines=True, denied_line=False)


def _available_check(actor, lines, exclude_batch):
    """Revalidate the whole group under the tenant lock at submit and posting."""
    source_amounts = {}
    for r in lines:
        obj = _current(actor, r)
        source_key = (r.kind, r.source_id)
        source_amounts[source_key] = source_amounts.get(source_key, Decimal(0)) + r.amount
        active = PR.objects.filter(tenant_id=actor.tenant_id, kind=r.kind, source_id=r.source_id,
            status='submitted', payment__isnull=True).exclude(batch_id=exclude_batch).exclude(
            approval__status__in=['rejected', 'withdrawn']).exclude(batch__approval__status__in=['rejected', 'withdrawn'])
        if r.fee_item_id:
            paid = PaymentRecord.objects.filter(tenant_id=actor.tenant_id, **{r.kind:obj}, fee_item_id=r.fee_item_id,
                reverses__isnull=True, reversal__isnull=True).aggregate(v=Sum('amount'))['v'] or Decimal(0)
            reserved = active.filter(fee_item_id=r.fee_item_id).aggregate(v=Sum('amount'))['v'] or Decimal(0)
            if r.amount + paid + reserved > Decimal(r.item_snapshot['amount']):
                raise ValidationError('申请金额超过费用项目可用余额（含其他审批占用）。')
    for (kind, source_id), amount in source_amounts.items():
        remaining = costs.payment_summary(actor, kind, source_id)['summary']['remaining_amount']
        reserved = PR.objects.filter(tenant_id=actor.tenant_id, kind=kind, source_id=source_id,
            status='submitted', payment__isnull=True).exclude(batch_id=exclude_batch).exclude(
            approval__status__in=['rejected', 'withdrawn']).exclude(batch__approval__status__in=['rejected', 'withdrawn']).aggregate(v=Sum('amount'))['v'] or Decimal(0)
        if remaining is None or amount + reserved > Decimal(remaining):
            raise ValidationError('申请金额超过来源可用余额（含其他审批占用）。')


def _data(actor, b, *, compact=False):
    if compact:
        lines=list(b.lines.all())
        reversed_all=bool(lines) and all(r.payment_id and r.payment.reversal.exists() for r in lines)
        return {'id':b.pk,'version':b.version,'amount':str(sum((r.amount for r in lines),Decimal(0))),
            'status':'reversed' if reversed_all else b.status if b.status in ('paid','cancelled') else b.approval.status if b.approval_id else b.status}
    lines=[]
    for r in b.lines.select_related('payment').prefetch_related('payment__reversal').all().order_by('id'):
        source = costs._payment_owner(actor, r.kind, r.source_id, VIEW)
        lines.append({'id':r.pk,'kind':r.kind,'source_id':r.source_id,'number':getattr(source,'number',str(source.pk)),
            'amount':str(r.amount),'fee_item_id':r.fee_item_id,'fee_item_name':r.item_snapshot.get('name'),
            'payment_id':r.payment_id,
            'status':'reversed' if r.payment_id and (r.payment.reverses_id or r.payment.reversal.exists()) else 'paid' if r.payment_id else 'pending'})
    vouchers=[{'id':v.pk,'file_name':v.file_name,'media_type':v.media_type,'byte_size':v.byte_size,'sha256':v.sha256} for v in b.vouchers.defer('content').order_by('id')]
    status=b.approval.status if b.approval_id else b.status
    group_status='reversed' if lines and all(x['status']=='reversed' for x in lines) else 'paid' if b.status=='paid' else 'cancelled' if b.status=='cancelled' else status
    return {'id':b.pk,'version':b.version,'status':group_status,
        'amount':str(sum((Decimal(r['amount']) for r in lines),Decimal(0))),'reason':b.reason,'lines':lines,
        'account_snapshot':{**b.account_snapshot,'account_number':costs._mask_account_number(b.account_snapshot.get('account_number',''))},
        'approval_id':b.approval_id,'vouchers':vouchers,'notification_status':b.notification_status,'notification_error':b.notification_error,
        'can_submit':b.status=='draft' and b.created_by_id==actor.pk and check_user_permission(actor,MANAGE) and check_user_permission(actor,'workflow.approvals.submit'),
        'can_cancel':b.status not in ('cancelled','paid') and b.created_by_id==actor.pk and check_user_permission(actor,MANAGE),
        'can_upload':status=='approved' and b.status!='paid' and b.status!='cancelled' and check_user_permission(actor,MANAGE),
        'can_notify':bool(b.approval_id and b.status=='submitted' and finance_allowed(actor) and check_user_permission(actor,MANAGE)),
        'can_confirm':bool(b.approval_id and status=='approved' and vouchers and b.status=='submitted' and finance_allowed(actor) and check_user_permission(actor,MANAGE)),
        'can_reverse':b.status=='paid' and any(r['status']=='paid' for r in lines) and not any(r['status']=='reversed' for r in lines) and finance_allowed(actor)}

class BatchCollection(InternalAPI):
    def get(self, request):
        try:
            limit=int(request.query_params.get('limit',20)); offset=int(request.query_params.get('offset',0))
            if not 1<=limit<=100 or offset<0: raise ValueError
        except ValueError: raise ValidationError('limit或offset无效。')
        qs=visible_batches(request.user).select_related('approval').prefetch_related(
            Prefetch('lines',queryset=PR.objects.select_related('payment').prefetch_related('payment__reversal'))).order_by('-id')
        party_kind=request.query_params.get('party_kind'); party_id=request.query_params.get('party_id')
        if party_kind or party_id:
            if party_kind not in ('supplier','freight_company') or not party_id or not party_id.isdigit(): raise ValidationError('party_kind与party_id无效。')
            field='payee_account__supplier_id' if party_kind=='supplier' else 'payee_account__freight_company_id'
            qs=qs.filter(**{field:int(party_id)})
        total=qs.count(); rows=list(qs[offset:offset+limit])
        return Response({'data':[_data(request.user,b,compact=True) for b in rows],'count':total,'limit':limit,'offset':offset})

    @transaction.atomic
    def post(self, request):
        actor=request.user; services._internal(actor); services._tenant_lock(actor)
        data=CreateInput(data=request.data); data.is_valid(raise_exception=True); p=data.validated_data
        lines=[]
        for raw in p['lines']:
            s=LineInput(data=raw); s.is_valid(raise_exception=True); v=s.validated_data
            obj=costs._payment_owner(actor,v['kind'],v['source_id'],MANAGE)
            lines.append((v,obj))
        parties={_party(v['kind'],obj) for v,obj in lines}
        if len(parties)!=1: raise ValidationError('批次来源必须属于同一供应商或货运公司。')
        line_keys=[(v['kind'],v['source_id'],v.get('fee_item_id')) for v,obj in lines]
        if len(line_keys)!=len(set(line_keys)): raise ValidationError('同一来源及费用项目不能在批次中重复。')
        account=costs.PayeeAccount.objects.filter(tenant_id=actor.tenant_id,active=True,pk=p['payee_account_id'],**costs._payee_owner(lines[0][0]['kind'],lines[0][1])).first()
        if not account or any(costs._payee_owner(v['kind'],obj)!=costs._payee_owner(lines[0][0]['kind'],lines[0][1]) for v,obj in lines): raise ValidationError('收款账户无效或与批次对象不匹配。')
        keyval=key(request); digest=services.request_hash({'account':account.pk,'reason':p['reason'],'lines':p['lines']})
        old=Batch.objects.select_for_update().filter(tenant_id=actor.tenant_id,idempotency_key=keyval).first()
        if old:
            if old.request_hash!=digest: raise ValidationError('幂等键已用于不同内容。')
            return Response({'data':_data(actor,old)})
        with domain_write(): b=Batch.objects.create(tenant=actor.tenant,created_by=actor,payee_account=account,account_snapshot=costs._payee_data(account),reason=p['reason'],idempotency_key=keyval,request_hash=digest)
        planned_source={}; planned_item={}
        for v,obj in lines:
            fee_item=None; item={}
            if v['kind'] in ('batch','inbound'):
                fee=costs.fee_record(v['kind'],obj); breakdown=fee.current_revision.item_breakdown if fee and fee.current_revision else []
                if breakdown:
                    item=next((x for x in breakdown if str(x['fee_item_id'])==str(v.get('fee_item_id'))),None)
                    if not item or item['nature']!=account.nature: raise ValidationError('费用项目或账户性质不匹配。')
                    fee_item=PaymentItem.objects.get(tenant_id=actor.tenant_id,pk=item['fee_item_id'])
            if v.get('fee_item_id') and not item: raise ValidationError('当前来源没有此费用项目。')
            summary=costs.payment_summary(actor,v['kind'],v['source_id'])['summary']
            if summary['remaining_amount'] is None or v['amount']>Decimal(summary['remaining_amount']): raise ValidationError('申请金额超过来源应付余额。')
            current=PR.objects.filter(tenant_id=actor.tenant_id,kind=v['kind'],source_id=v['source_id'],status='submitted',payment__isnull=True)
            active=current.exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn'])
            source_key=(v['kind'],v['source_id']); reserved=active.aggregate(v=Sum('amount'))['v'] or Decimal(0)
            planned_source[source_key]=planned_source.get(source_key,Decimal(0))+v['amount']
            if planned_source[source_key]+reserved>Decimal(summary['remaining_amount']): raise ValidationError('已有未结申请占用来源余额。')
            if item:
                item_key=(v['kind'],v['source_id'],fee_item.pk)
                item_reserved=active.filter(fee_item=fee_item).aggregate(v=Sum('amount'))['v'] or Decimal(0)
                item_paid=PaymentRecord.objects.filter(tenant_id=actor.tenant_id,**{v['kind']:obj},fee_item=fee_item,reverses__isnull=True,reversal__isnull=True).aggregate(v=Sum('amount'))['v'] or Decimal(0)
                planned_item[item_key]=planned_item.get(item_key,Decimal(0))+v['amount']
                if planned_item[item_key]+item_reserved+item_paid>Decimal(item['amount']): raise ValidationError('申请金额超过费用项目剩余应付金额。')
            with domain_write(): PR.objects.create(tenant=actor.tenant,created_by=actor,kind=v['kind'],source_id=v['source_id'],amount=v['amount'],payee_account=account,account_snapshot=costs._payee_data(account),fee_item=fee_item,item_snapshot=item,reason=p['reason'],status='draft',batch=b,idempotency_key='batch-child-'+services.request_hash({'batch':b.pk,'kind':v['kind'],'source':v['source_id'],'item':fee_item.pk if fee_item else None}),request_hash=services.request_hash(v))
        return Response({'data':_data(actor,b)},status=201)

class BatchCandidates(InternalAPI):
    def get(self,request):
        actor=request.user; party_kind=request.query_params.get('party_kind'); party_id=request.query_params.get('party_id')
        if party_kind not in ('supplier','freight_company') or not party_id or not party_id.isdigit(): raise ValidationError('party_kind与party_id无效。')
        try: limit=int(request.query_params.get('limit',20)); offset=int(request.query_params.get('offset',0))
        except ValueError: raise ValidationError('limit或offset无效。')
        if not 1<=limit<=100 or offset<0: raise ValidationError('limit或offset无效。')
        search=request.query_params.get('search','').strip()[:200]
        sources=[]
        candidates=[]
        if party_kind=='supplier':
            from .models import PurchaseOrder
            from .permissions import accessible_orders
            allowed_orders=accessible_orders(actor,PurchaseOrder.objects.filter(supplier_id=party_id),'supply.v2.view')
            qs=SupplierShipment.objects.filter(tenant_id=actor.tenant_id,order__in=allowed_orders,status='submitted').order_by('-id')
            if search: qs=qs.filter(number__icontains=search)
            total=qs.count(); page=list(qs[offset:offset+limit])
            for obj in page:
                candidates.append(('shipment',obj))
        else:
            from .models import PurchaseOrder
            from .permissions import accessible_orders
            from .logistics import batches_for
            allowed_orders=accessible_orders(actor,PurchaseOrder.objects.all(),'supply.v2.view')
            allowed_batches=batches_for(actor,'supply.v2.view').filter(freight_company_id=party_id)
            qsets=[('domestic_freight',SupplierShipment.objects.filter(tenant_id=actor.tenant_id,domestic_carrier_id=party_id,order__in=allowed_orders)),('batch',allowed_batches),('inbound',InboundOrder.objects.filter(tenant_id=actor.tenant_id,batch__in=allowed_batches))]
            if search: qsets=[(kind,qs.filter(number__icontains=search)) for kind,qs in qsets]
            counts=[qs.count() for _,qs in qsets]
            total=sum(counts); skip=offset; remaining=limit
            for (kind,qs),count in zip(qsets,counts):
                if skip>=count:
                    skip-=count
                    continue
                page=list(qs.order_by('-id')[skip:skip+remaining])
                candidates.extend((kind,obj) for obj in page)
                remaining-=len(page); skip=0
                if not remaining: break
        for kind,obj in candidates:
            summary=costs.payment_summary(actor,kind,obj.pk)['summary']
            reserved=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=obj.pk,status='submitted',payment__isnull=True).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(v=Sum('amount'))['v'] or Decimal(0)
            due=Decimal(summary.get('due_amount') or 0); paid=Decimal(summary.get('paid_amount') or 0)
            breakdown=[]
            if kind in ('batch','inbound'):
                fee=costs.fee_record(kind,obj); breakdown=fee.current_revision.item_breakdown if fee and fee.current_revision else []
            base={'kind':kind,'source_id':obj.pk,'number':getattr(obj,'number',str(obj.pk)),'due_amount':str(due),'paid_amount':str(paid),'reserved_amount':str(reserved),'remaining_amount':str(summary.get('remaining_amount') or 0),'available_amount':str(max(Decimal(0),Decimal(summary.get('remaining_amount') or 0)-reserved))}
            if breakdown:
                for item in breakdown:
                    item_id=int(item['fee_item_id']); item_reserved=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=obj.pk,fee_item_id=item_id,status='submitted',payment__isnull=True).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(v=Sum('amount'))['v'] or Decimal(0)
                    item_paid=PaymentRecord.objects.filter(tenant_id=actor.tenant_id,**{kind:obj},fee_item_id=item_id,reverses__isnull=True,reversal__isnull=True).aggregate(v=Sum('amount'))['v'] or Decimal(0)
                    item_due=Decimal(item['amount'])
                    sources.append({**base,'fee_item_id':item_id,'fee_item_name':item.get('name'),'nature':item.get('nature'),'due_amount':str(item_due),'paid_amount':str(item_paid),'reserved_amount':str(item_reserved),'remaining_amount':str(max(Decimal(0),item_due-item_paid)),'available_amount':str(max(Decimal(0),min(item_due-item_paid-item_reserved,Decimal(base['available_amount']))))})
            else: sources.append(base)
        owner={'supplier_id':int(party_id)} if party_kind=='supplier' else {'freight_company_id':int(party_id)}
        accounts=[{**_snap(a),'id':a.pk,'nature':a.nature} for a in costs.PayeeAccount.objects.filter(tenant_id=actor.tenant_id,active=True,**owner).order_by('id')] if total else []
        return Response({'data':sources,'count':total,'limit':limit,'offset':offset,'accounts':accounts})

class BatchDetail(InternalAPI):
    def get(self,request,pk):
        b=Batch.objects.filter(tenant_id=request.user.tenant_id,pk=pk).first()
        if not b: raise NotFound()
        for r in b.lines.all(): costs._payment_owner(request.user,r.kind,r.source_id,VIEW)
        return Response({'data':_data(request.user,b)})

class BatchAction(InternalAPI):
    @transaction.atomic
    def post(self,request,pk,action):
        actor=request.user; services._tenant_lock(actor)
        b=Batch.objects.select_for_update().filter(tenant_id=actor.tenant_id,pk=pk).first()
        if not b: raise NotFound()
        lines=list(b.lines.select_for_update().all())
        for r in lines: costs._payment_owner(actor,r.kind,r.source_id,MANAGE)
        idem=key(request); event_payload={**request.data,'action':action,'batch_id':b.pk}
        prior=services._prior_event(actor,b,'payment_batch_'+action,idem,event_payload)
        if prior: return Response({'data':_data(actor,b)})
        if action not in ('confirm','reverse') and request.data.get('expected_version')!=b.version:
            return conflict('批次版本已变化，请刷新。')
        if action=='submit':
            if b.status!='draft' or b.created_by_id!=actor.pk: raise PermissionDenied()
            if not check_user_permission(actor,'workflow.approvals.submit') or not scope_allows_value(actor,'workflow.approvals.submit','approval_types','finance'): raise PermissionDenied()
            _available_check(actor,lines,b.pk)
            ref=','.join(str(costs._payment_owner(actor,r.kind,r.source_id,VIEW).number) for r in lines)
            approval=ApprovalRequest.objects.create(tenant=actor.tenant,approval_type='finance',title=f'批量付款申请 #{b.pk}（{len(lines)}项）',business_type='supply_payment_batch',business_id=str(b.pk),requested_by=actor,reason=f'{ref}；总额{sum((r.amount for r in lines),Decimal(0))}；{b.reason}',idempotency_key=f'paybatch:{b.pk}')
            b.approval=approval; b.status='submitted'; b.version+=1
            with domain_write():
                for r in lines: r.status='submitted'; r.save(update_fields=['status','updated_at'])
                b.save(update_fields=['approval','status','version','updated_at'])
            from apps.workflows.services import write_workflow_audit
            write_workflow_audit(approval,resource_type='approval',actor=actor,action='submit',to_status='pending',detail={'line_count':len(lines)})
            try:
                from apps.integrations.feishu_delivery import notify_approval
                with transaction.atomic(): result=notify_approval(approval.pk)
                b.notification_error=''; b.notification_status=result.get('status','queued')
            except Exception: b.notification_status='error'; b.notification_error='飞书通知入队失败，请检查通知配置后重试。'
            with domain_write(): b.save(update_fields=['notification_status','notification_error'])
        elif action=='cancel':
            if b.status=='paid' or b.created_by_id!=actor.pk: raise PermissionDenied()
            if not (request.data.get('reason') or '').strip(): raise ValidationError({'reason':'取消原因必填。'})
            if b.approval_id and b.approval.status=='pending':
                from apps.workflows.services import review_approval
                review_approval(approval=b.approval,actor=actor,action='withdraw',note=request.data.get('reason',''))
            b.status='cancelled'; b.version+=1
            with domain_write(): b.save(update_fields=['status','version','updated_at'])
            with domain_write():
                for r in lines: r.status='cancelled'; r.save(update_fields=['status','updated_at'])
        elif action=='notify':
            if not b.approval_id or b.status!='submitted' or not finance_allowed(actor): raise PermissionDenied()
            from apps.integrations.feishu_delivery import notify_approval
            try:
                with transaction.atomic(): result=notify_approval(b.approval_id)
                b.notification_status=result.get('status','queued'); b.notification_error=''
            except Exception:
                b.notification_status='error'; b.notification_error='飞书通知入队失败，请检查通知配置后重试。'
            with domain_write(): b.save(update_fields=['notification_status','notification_error','updated_at'])
        elif action=='confirm':
            if not finance_allowed(actor): raise PermissionDenied()
            data=ConfirmInput(data=request.data); data.is_valid(raise_exception=True); p=data.validated_data
            if not b.approval_id or b.approval.status!='approved' or b.status!='submitted' or any(r.payment_id for r in lines): raise ValidationError('仅审批通过的批次可入账。')
            if b.version!=p['expected_version']: return conflict('批次版本已变化，请刷新。')
            files=list(b.vouchers.order_by('id'))
            if not files: raise ValidationError('请先上传实际转账凭证。')
            _available_check(actor,lines,b.pk)
            payments=[]
            for r in lines:
                _current(actor,r)
                state=costs.payment_summary(actor,r.kind,r.source_id)
                body={'amount':r.amount,'payee_account_id':r.payee_account_id,'date':p['date'],'reference_number':p['reference_number'] or f'BP-{b.pk}-{r.pk}','notes':p['notes'],'expected_version':state['version']}
                if r.fee_item_id: body['fee_item_id']=r.fee_item_id
                pkey=f'payment-request-{r.pk}'; costs.create_payment(actor,r.kind,r.source_id,body,pkey)
                payments.append(PaymentRecord.objects.get(tenant=actor.tenant,idempotency_key=pkey))
            from .payment_voucher_models import PaymentVoucher
            with domain_write():
                for voucher in files:
                    content=bytes(voucher.content)
                    if hashlib.sha256(content).hexdigest()!=voucher.sha256: raise ValidationError('凭证完整性校验失败，未入账。')
                    for payment in payments: PaymentVoucher.objects.create(tenant=actor.tenant,created_by=actor,payment=payment,file_name=voucher.file_name,media_type=voucher.media_type,byte_size=voucher.byte_size,sha256=voucher.sha256,content=content,idempotency_key=f'paybatch-{b.pk}-voucher-{voucher.pk}-payment-{payment.pk}')
                for r,pay in zip(lines,payments): r.payment=pay; r.status='paid'; r.save(update_fields=['payment','status','updated_at'])
                b.status='paid'; b.version+=1; b.save(update_fields=['status','version','updated_at'])
        elif action=='reverse':
            if not finance_allowed(actor): raise PermissionDenied()
            if b.status!='paid' or b.version!=request.data.get('expected_version'): raise ValidationError('批次已变化或尚未付款。')
            reason=(request.data.get('reason') or '').strip()
            if not reason: raise ValidationError({'reason':'冲销原因必填。'})
            for r in lines:
                if not r.payment_id or r.payment.reversal.exists(): raise ValidationError('批次存在未入账或已冲销的付款行。')
            for r in lines:
                summary=costs.payment_summary(actor,r.kind,r.source_id)
                costs.reverse_payment(actor,r.kind,r.source_id,r.payment_id,{'reason':reason,'expected_version':summary['version']},f'paybatch-reverse-{b.pk}-{r.pk}',allow_payment_batch=True)
            b.version+=1
            with domain_write(): b.save(update_fields=['version','updated_at'])
        else: raise NotFound()
        with domain_write(): services._event(actor,b,'payment_batch_'+action,idem,event_payload)
        return Response({'data':_data(actor,b)})

class BatchVouchers(InternalAPI):
    @transaction.atomic
    def post(self,request,pk):
        b=Batch.objects.select_for_update().filter(tenant_id=request.user.tenant_id,pk=pk).first()
        if not b: raise NotFound()
        lines=list(b.lines.all())
        for line in lines: costs._payment_owner(request.user,line.kind,line.source_id,MANAGE)
        if not check_user_permission(request.user,MANAGE): raise PermissionDenied()
        idem=key(request); name,media,body,digest=_validate_file(request.FILES.get('file'))
        old=b.vouchers.filter(idempotency_key=idem).first()
        if old:
            if old.sha256!=digest or old.file_name!=name: return conflict('此上传标识已用于不同凭证。')
            return Response({'data':_data(request.user,b)})
        if not b.approval_id or b.approval.status!='approved' or b.status!='submitted': raise ValidationError('仅审批通过且未入账批次可上传凭证。')
        try: expected_version=int(request.data.get('expected_version'))
        except (TypeError,ValueError): raise ValidationError({'expected_version':'批次版本无效。'})
        if expected_version!=b.version: return conflict('批次版本已变化，请刷新。')
        if b.vouchers.count()>=5: raise ValidationError('每个付款批次最多5份凭证。')
        with domain_write():
            Voucher.objects.create(tenant=request.user.tenant,created_by=request.user,batch=b,file_name=name,media_type=media,byte_size=len(body),sha256=digest,content=body,idempotency_key=idem)
            b.version+=1; b.save(update_fields=['version','updated_at'])
        return Response({'data':_data(request.user,b)},status=201)

class BatchVoucherDownload(InternalAPI):
    def get(self,request,pk,vid):
        b=Batch.objects.filter(tenant_id=request.user.tenant_id,pk=pk).first()
        if not b: raise NotFound()
        for r in b.lines.all(): costs._payment_owner(request.user,r.kind,r.source_id,VIEW)
        v=Voucher.objects.filter(batch=b,pk=vid).first()
        if not v: raise NotFound()
        body=bytes(v.content)
        if hashlib.sha256(body).hexdigest()!=v.sha256: raise ValidationError('凭证完整性校验失败。')
        res=FileResponse(BytesIO(body),as_attachment=True,filename=v.file_name,content_type=v.media_type); res['Cache-Control']='private, no-store'; res['X-Content-Type-Options']='nosniff'; return res
