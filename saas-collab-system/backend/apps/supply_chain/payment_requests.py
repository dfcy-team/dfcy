import hashlib
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Prefetch
from rest_framework.exceptions import ValidationError, NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework import serializers
from . import costs, services
from .cost_models import PaymentRecord
from .payment_item_models import PaymentItem
from .payment_request_models import SupplyPaymentRequest as PR
from .payment_request_models import SupplyPaymentRequestVoucher
from .permissions import MANAGE, VIEW
from .views import InternalAPI
from .api import key
from apps.workflows.models import ApprovalRequest
from apps.workflows.permissions import scope_allows_value
from apps.permissions.services import user_has_finance_permission
from apps.permissions.ui_p6_scopes import finance_values_allowed
from apps.permissions.services import check_user_permission
from .models import domain_write
from apps.common.security import sanitize_sensitive_data


def _source(actor, kind, source_id, permission=VIEW):
    try:
        return costs._payment_owner(actor, kind, source_id, permission)
    except Exception:
        raise


def _snap(account):
    from .costs import _payee_data, _mask_account_number
    d = _payee_data(account)
    d['account_number'] = _mask_account_number(d['account_number'])
    return d


def _current(actor, row):
    obj = _source(actor, row.kind, row.source_id, VIEW)
    owner = costs._payee_owner(row.kind, obj)
    account = costs.PayeeAccount.objects.filter(tenant_id=actor.tenant_id, active=True,
        pk=row.payee_account_id, **owner).first()
    if account is None or costs._payee_data(account) != row.account_snapshot:
        raise ValidationError('收款账户信息已变化，请取消后重新申请。')
    if row.kind in ('batch', 'inbound'):
        fee = costs.fee_record(row.kind, obj)
        breakdown = fee.current_revision.item_breakdown if fee and fee.current_revision else []
        match = next((i for i in breakdown if str(i['fee_item_id']) == str(row.fee_item_id)), None)
        if (breakdown and not row.fee_item_id) or (row.fee_item_id and (match is None or match != row.item_snapshot)):
            raise ValidationError('费用项目已变化，请取消后重新申请。')
    return obj


def _unpaid(actor, row):
    try: return row.approval.status
    except Exception: return 'pending'

def finance_allowed(actor):
    return user_has_finance_permission(actor, 'finance.reconcile') and finance_values_allowed(actor, 'finance.reconcile', platform='', currency='CNY')


def request_data(actor, row):
    vouchers = getattr(row, '_voucher_rows', None)
    if vouchers is None:
        vouchers = list(row.vouchers.all().defer('content').order_by('id'))
    vouchers = [{'id':v.pk,'file_name':v.file_name,'media_type':v.media_type,'byte_size':v.byte_size,'sha256':v.sha256} for v in vouchers]
    approval_status = row.batch.approval.status if row.batch_id and row.batch.approval_id else _unpaid(actor,row)
    reversed_payment = bool(row.payment_id and (row.payment.reverses_id or row.payment.reversal.exists()))
    allowed_manage = check_user_permission(actor, MANAGE)
    can_submit = row.status=='draft' and row.created_by_id==actor.pk and allowed_manage and check_user_permission(actor,'workflow.approvals.submit') and scope_allows_value(actor,'workflow.approvals.submit','approval_types','finance')
    can_cancel = not row.payment_id and row.status!='cancelled' and row.created_by_id==actor.pk and allowed_manage
    can_confirm = bool(row.approval_id and approval_status=='approved' and vouchers and not row.payment_id and row.status!='cancelled' and allowed_manage and finance_allowed(actor))
    result = {'id':row.pk,'version':row.version,'status':'reversed' if reversed_payment else 'paid' if row.payment_id else ('cancelled' if row.status=='cancelled' else approval_status if (row.approval_id or (row.batch_id and row.batch.approval_id)) else row.status),
        'amount':str(row.amount),'reason':row.reason,'item_snapshot':row.item_snapshot,'account_snapshot':{**row.account_snapshot,'account_number':costs._mask_account_number(row.account_snapshot.get('account_number',''))},'approval_id':row.approval_id,
        'payment_id':row.payment_id,'vouchers':vouchers,'notification_status':row.notification_status,'notification_error':row.notification_error,
        'can_submit':can_submit,'can_cancel':can_cancel,'can_upload':bool(row.approval_id and approval_status in ('pending','approved') and not row.payment_id and row.status!='cancelled' and allowed_manage),
        'can_notify':bool(row.approval_id and not row.payment_id and row.status!='cancelled' and finance_allowed(actor)),'can_confirm':can_confirm}
    if row.batch_id:
        result['batch_id']=row.batch_id
        result['batch_href']=f'/supply-chain/costs?tab=reconciliation&payment_batch_id={row.batch_id}'
        for name in ('submit','cancel','upload','notify','confirm'): result['can_'+name]=False
    return result


class CreateInput(serializers.Serializer):
    amount=serializers.DecimalField(max_digits=24,decimal_places=4,min_value=Decimal('.0001'))
    payee_account_id=serializers.IntegerField(min_value=1)
    fee_item_id=serializers.IntegerField(min_value=1,required=False)
    reason=serializers.CharField(max_length=10000)

class RequestAPI(InternalAPI):
    def get(self,request,kind,pk):
        _source(request.user,kind,pk,VIEW)
        qs=PR.objects.filter(tenant_id=request.user.tenant_id,kind=kind,source_id=pk).select_related('approval','payment','payee_account','batch__approval').prefetch_related('payment__reversal', Prefetch('vouchers',queryset=SupplyPaymentRequestVoucher.objects.defer('content'),to_attr='_voucher_rows'))
        rid=request.query_params.get('request_id')
        try:
            limit=int(request.query_params.get('limit',20)); offset=int(request.query_params.get('offset',0))
            if limit<1 or limit>100 or offset<0 or (rid is not None and (not rid.isdigit() or int(rid)<1)): raise ValueError
        except (ValueError,TypeError): raise ValidationError('limit、offset或request_id无效。')
        if rid: qs=qs.filter(pk=rid)
        total=qs.count(); rows=list(qs.order_by('-id')[offset:offset+limit])
        return Response({'data':[request_data(request.user,r) for r in rows],'count':total,'limit':limit,'offset':offset})
    @transaction.atomic
    def post(self,request,kind,pk):
        actor=request.user; obj=_source(actor,kind,pk,MANAGE); data=CreateInput(data=request.data); data.is_valid(raise_exception=True); p=data.validated_data
        services._tenant_lock(actor); services._internal(actor)
        keyval=key(request); digest=services.request_hash({**p,'kind':kind,'source_id':pk})
        replay=PR.objects.select_for_update().filter(tenant_id=actor.tenant_id,idempotency_key=keyval).first()
        if replay:
            if replay.request_hash!=digest: raise ValidationError('幂等键已用于不同内容。')
            return Response({'data':request_data(actor,replay)})
        account=costs.PayeeAccount.objects.filter(tenant_id=actor.tenant_id,active=True,pk=p['payee_account_id'],**costs._payee_owner(kind,obj)).first()
        if not account: raise ValidationError('收款账户无效或不属于当前业务对象。')
        fee_item=None; item={}; amt=p['amount']
        if kind in ('batch','inbound'):
            fee=costs.fee_record(kind,obj); breakdown=fee.current_revision.item_breakdown if fee and fee.current_revision else []
            if breakdown:
                item=next((i for i in breakdown if str(i['fee_item_id'])==str(p.get('fee_item_id'))),None)
                if not item or account.nature != item['nature']: raise ValidationError('费用项目或收款账户性质不匹配。')
                fee_item=PaymentItem.objects.get(tenant_id=actor.tenant_id,pk=item['fee_item_id'])
                paid=PaymentRecord.objects.filter(tenant_id=actor.tenant_id,**{kind:obj},fee_item=fee_item,reverses__isnull=True,reversal__isnull=True).aggregate(s=Sum('amount'))['s'] or Decimal(0)
                reserved=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=pk,fee_item=fee_item,status='submitted',payment__isnull=True).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(s=Sum('amount'))['s'] or Decimal(0)
                if amt + paid + reserved > Decimal(item['amount']): raise ValidationError('申请金额超过该费用项目剩余应付金额。')
        summary=costs.payment_summary(actor,kind,pk)['summary']
        if summary['remaining_amount'] is None or amt>Decimal(summary['remaining_amount']): raise ValidationError('申请金额超过当前应付余额。')
        reserved=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=pk,status='submitted',payment__isnull=True).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(s=Sum('amount'))['s'] or Decimal(0)
        if amt+reserved>Decimal(summary['remaining_amount']): raise ValidationError('已有未结申请占用余额。')
        with domain_write():
            row,created=PR.objects.get_or_create(tenant=actor.tenant,created_by=actor,idempotency_key=keyval,defaults={'kind':kind,'source_id':pk,'amount':amt,'payee_account':account,'account_snapshot':costs._payee_data(account),'fee_item':fee_item,'item_snapshot':item,'reason':p['reason'],'request_hash':digest})
        if not created and row.request_hash!=digest: raise ValidationError('幂等键已用于不同内容。')
        return Response({'data':request_data(actor,row)},status=201 if created else 200)

class RequestAction(InternalAPI):
    @transaction.atomic
    def post(self,request,kind,pk,request_id,action):
        if action not in {'submit','cancel','notify'}: raise NotFound('付款申请操作不存在。')
        actor=request.user; obj=_source(actor,kind,pk,MANAGE); services._tenant_lock(actor)
        row=PR.objects.select_for_update().filter(tenant_id=actor.tenant_id,kind=kind,source_id=pk,pk=request_id).select_related('payee_account').first()
        if not row: raise NotFound('付款申请不存在。')
        if row.batch_id: raise ValidationError('该申请属于付款批次，请在批次中操作。')
        keyval=key(request); payload={**request.data,'action':action,'request_id':row.pk}
        old=services._prior_event(actor,row,'request_'+action,keyval,payload)
        if old: return Response({'data':request_data(actor,row)})
        if request.data.get('expected_version')!=row.version: raise ValidationError('申请已变化，请刷新。')
        if action=='submit':
            if row.status!='draft': raise ValidationError('仅草稿可提交。')
            if row.created_by_id != actor.pk: raise PermissionDenied()
            if not check_user_permission(actor,'workflow.approvals.submit') or not scope_allows_value(actor,'workflow.approvals.submit','approval_types','finance'): raise PermissionDenied()
            _current(actor,row)
            if row.fee_item_id:
                item_amount=Decimal(str(row.item_snapshot.get('amount','0')))
                paid=PaymentRecord.objects.filter(tenant_id=actor.tenant_id,**{kind:obj},fee_item_id=row.fee_item_id,reverses__isnull=True,reversal__isnull=True).aggregate(s=Sum('amount'))['s'] or Decimal(0)
                reserved_item=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=pk,fee_item_id=row.fee_item_id,status='submitted',payment__isnull=True).exclude(pk=row.pk).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(s=Sum('amount'))['s'] or Decimal(0)
                if row.amount+paid+reserved_item>item_amount: raise ValidationError('申请金额超过该费用项目剩余应付金额。')
            summary=costs.payment_summary(actor,kind,pk)['summary']
            reserved=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=pk,status='submitted',payment__isnull=True).exclude(pk=row.pk).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(s=Sum('amount'))['s'] or Decimal(0)
            if summary['remaining_amount'] is None or row.amount+reserved>Decimal(summary['remaining_amount']): raise ValidationError('申请金额超过可用余额（含其他未结申请）。')
            number=obj.number; suffix=row.account_snapshot.get('account_number','')[-4:]
            approval=ApprovalRequest.objects.create(tenant=actor.tenant,approval_type='finance',title=f'付款申请 {number}',business_type='supply_payment_request',business_id=str(row.pk),requested_by=actor,reason=f'{number} {row.amount} {row.account_snapshot.get("nature","")} 尾号{suffix}；项目：{row.item_snapshot.get("name", "整单款项")}；申请理由：{row.reason} /supply-chain/costs?kind={kind}&id={pk}&payment_request_id={row.pk}',idempotency_key=f'payreq:{row.pk}')
            row.approval=approval; row.status='submitted'; row.version+=1
            with domain_write(): row.save(update_fields=['approval','status','version'])
            from apps.workflows.services import write_workflow_audit
            write_workflow_audit(approval,resource_type='approval',actor=actor,action='submit',to_status='pending',detail={})
            try:
                from apps.integrations.feishu_delivery import notify_approval
                with transaction.atomic(): result=notify_approval(approval.pk)
                row.notification_status=result.get('status','queued'); row.notification_error=''
            except Exception as exc:
                row.notification_status='error'; row.notification_error='飞书通知入队失败，请检查通知配置后重试。'
            with domain_write(): row.save(update_fields=['notification_status','notification_error'])
        elif action=='cancel':
            reason=request.data.get('reason','').strip()
            if not reason: raise ValidationError({'reason':'取消原因必填。'})
            if row.payment_id: raise ValidationError('已付款申请不能取消。')
            if row.approval_id and row.approval.status=='pending':
                from apps.workflows.services import review_approval
                review_approval(approval=row.approval,actor=actor,action='withdraw',note=request.data.get('reason',''))
            elif row.approval_id and row.approval.status=='approved' and row.created_by_id!=actor.pk: raise PermissionDenied()
            elif row.created_by_id!=actor.pk: raise PermissionDenied()
            row.status='cancelled'; row.version+=1
            with domain_write(): row.save(update_fields=['status','version'])
        elif action=='notify':
            if not row.approval_id or row.payment_id or row.status=='cancelled': raise ValidationError('当前申请不可通知。')
            if not finance_allowed(actor): raise PermissionDenied()
            from apps.integrations.feishu_delivery import notify_approval
            try:
                with transaction.atomic(): result=notify_approval(row.approval_id)
                row.notification_status=result.get('status','queued'); row.notification_error=''
            except Exception as exc:
                row.notification_status='error'; row.notification_error='飞书通知入队失败，请检查通知配置后重试。'
            with domain_write(): row.save(update_fields=['notification_status','notification_error'])
        with domain_write(): services._event(actor,row,'request_'+action,keyval,payload)
        return Response({'data':request_data(actor,row)})
