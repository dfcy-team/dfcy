import hashlib
from decimal import Decimal, ROUND_HALF_UP, localcontext
from django.db import transaction
from django.db.models import Sum, Prefetch
from rest_framework.exceptions import ValidationError, NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework import serializers
from . import costs, services
from .payment_fx import effective_snapshot
from .cost_models import PaymentPlanRecord, PaymentRecord
from .payment_item_models import PaymentItem
from .payment_request_models import SupplyPaymentRequest as PR
from .payment_request_models import SupplyPaymentRequestVoucher, SupplyPaymentRequestAttachment, active_vouchers
from .payment_plan_links import find_plan_line, validate_request_link
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
    if row.currency:
        costs.validate_payment_currency(actor,row.kind,obj,row.currency)
    owner = costs._payee_owner(row.kind, obj)
    account = costs.PayeeAccount.objects.filter(tenant_id=actor.tenant_id, active=True,
        pk=row.payee_account_id, **owner).first()
    if account is None or costs._payee_data(account) != row.account_snapshot:
        raise ValidationError('收款账户信息已变化，请取消后重新申请。')
    if row.kind in ('batch', 'inbound'):
        fee = costs.fee_record(row.kind, obj)
        breakdown = fee.current_revision.item_breakdown if fee and fee.current_revision else []
        match = next((i for i in breakdown if str(i['fee_item_id']) == str(row.fee_item_id)), None)
        if (breakdown and not row.fee_item_id) or (row.fee_item_id and (match is None or match != {key: value for key, value in row.item_snapshot.items() if key != "transport"})):
            raise ValidationError('费用项目已变化，请取消后重新申请。')
    validate_request_link(actor, row, obj)
    return obj


def _unpaid(actor, row):
    try: return row.approval.status
    except Exception: return 'pending'

def finance_allowed(actor, currency='', *, unknown_as_cny=True):
    value = (currency or 'CNY') if unknown_as_cny else currency
    return user_has_finance_permission(actor, 'finance.reconcile') and finance_values_allowed(actor, 'finance.reconcile', platform='', currency=value)


def request_finance_allowed(actor, row):
    if row.payment_id:
        currency = costs.recorded_payment_currency(actor, row.payment)
    else:
        source = costs._payment_owner(actor, row.kind, row.source_id, VIEW)
        try:
            costs.validate_payment_currency(actor, row.kind, source, row.currency)
        except ValidationError:
            return False
        currency = costs.source_payment_currency(actor, row.kind, source) or ''
    return finance_allowed(actor, currency, unknown_as_cny=False)


def request_data(actor, row):
    effective_rate, effective_cny = effective_snapshot(row.currency, row.amount, row.exchange_rate, row.cny_amount)
    vouchers = getattr(row, '_voucher_rows', None)
    if vouchers is None:
        vouchers = list(active_vouchers(row.vouchers.all()).defer('content').order_by('id'))
    vouchers = [{'id':v.pk,'file_name':v.file_name,'media_type':v.media_type,'byte_size':v.byte_size,'sha256':v.sha256} for v in vouchers]
    attachments = list(row.attachments.defer('content').order_by('id'))
    attachments = [{'id':f.pk,'file_name':f.file_name,'media_type':f.media_type,'byte_size':f.byte_size,'sha256':f.sha256} for f in attachments]
    approval_status = row.batch.approval.status if row.batch_id and row.batch.approval_id else _unpaid(actor,row)
    reversed_payment = bool(row.payment_id and (row.payment.reverses_id or row.payment.reversal.exists()))
    allowed_manage = check_user_permission(actor, MANAGE)
    from .payment_approval_api import approval_required
    can_submit = row.status=='draft' and row.created_by_id==actor.pk and allowed_manage and check_user_permission(actor,'workflow.approvals.submit') and scope_allows_value(actor,'workflow.approvals.submit','approval_types','finance') and approval_required(actor)
    can_cancel = not row.payment_id and row.status!='cancelled' and row.created_by_id==actor.pk and allowed_manage
    can_confirm = bool(row.approval_id and approval_status=='approved' and vouchers and not row.payment_id and row.status!='cancelled' and allowed_manage and request_finance_allowed(actor,row))
    result = {'id':row.pk,'version':row.version,'status':'reversed' if reversed_payment else 'paid' if row.payment_id else ('cancelled' if row.status=='cancelled' else approval_status if (row.approval_id or (row.batch_id and row.batch.approval_id)) else row.status),
        'amount':str(row.amount),'reason':row.reason,'item_snapshot':row.item_snapshot,'account_snapshot':{**row.account_snapshot,'account_number':costs._mask_account_number(row.account_snapshot.get('account_number',''))},'approval_id':row.approval_id,
        'currency':row.currency,'exchange_rate':str(effective_rate) if effective_rate is not None else None,'cny_amount':str(effective_cny) if effective_cny is not None else None,'corporate_tax':row.item_snapshot.get('corporate_tax') if row.kind=='shipment' else None,
        'plan_id':row.plan_id or None,'plan_line_id':row.plan_line_id or None,'plan_snapshot':row.plan_snapshot,
        'payment_id':row.payment_id,'vouchers':vouchers,'attachments':attachments,'notification_status':row.notification_status,'notification_error':row.notification_error,
        'can_attach':bool(row.created_by_id==actor.pk and allowed_manage and
            (row.status=='draft' or row.status=='submitted' and row.approval_id and approval_status=='pending')),
        'can_submit':can_submit,'can_cancel':can_cancel,'can_upload':bool(row.approval_id and approval_status in ('pending','approved') and not row.payment_id and row.status!='cancelled' and allowed_manage),
        'can_notify':bool(row.approval_id and not row.payment_id and row.status!='cancelled' and finance_allowed(actor,row.currency)),'can_confirm':can_confirm}
    if row.batch_id:
        result['batch_id']=row.batch_id
        result['batch_href']=f'/supply-chain/costs?tab=reconciliation&payment_batch_id={row.batch_id}'
        for name in ('submit','cancel','upload','notify','confirm'): result['can_'+name]=False
    from apps.integrations.feishu_native_approval import native_status, payment_form_options
    result['feishu_form'] = payment_form_options(actor, row, 'supply_payment_request') if not row.batch_id else None
    result['native_approval'] = native_status(row.approval) if row.approval_id else None
    from apps.integrations.feishu_finance_handoff import finance_data
    result['finance_handoff'] = finance_data(row.approval) if row.approval_id else None
    if result['finance_handoff']:
        result['can_upload'] = False
        if result['finance_handoff']['status'] != 'received' or row.approval.workflow_snapshot.get('finance_handler_id') != actor.pk:
            result['can_confirm'] = False
    if result['native_approval']:
        result['can_cancel'] = False
        result['can_notify'] = False
        if result['native_approval']['status'] != 'finished' or result['native_approval'].get('provider_status') != 'APPROVED':
            result['can_confirm'] = False
    return result


def corporate_request_amount(amount, summary):
    tax = summary.get('corporate_payment') or {}
    if tax.get('net_basis') is None:
        raise ValidationError({'amount': '本单尚未确认对公计税口径，请先核对税额。'})
    basis = Decimal(tax['net_basis'])
    if basis <= 0 or amount > basis:
        raise ValidationError({'amount': '未税申请金额超过本单未税应付。'})
    if tax.get('requires_full') and amount != basis:
        raise ValidationError({'amount': '部分付款前请先维护本单对公与对私的应付分类。'})
    total_tax = Decimal(tax['added_tax_amount'])
    with localcontext() as context:
        context.prec = 60
        allocated = (amount * total_tax / basis).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
    return {'net_amount': str(amount), 'tax_amount': str(allocated), 'gross_amount': str(amount + allocated),
            'source_net_basis': tax['net_basis'], 'source_tax_amount': tax['added_tax_amount'],
            **({'confirm_tax_rate': tax['supplier_tax_rate']} if tax.get('needs_confirmation') else {})}


def confirm_corporate_tax(actor, shipment, row, breakdown, summary, keyval):
    from . import payable_classifications
    from .cost_models import PayableClassificationRecord, ShipmentPayableTax

    rate = Decimal(breakdown['confirm_tax_rate'])
    basis = Decimal(breakdown['source_net_basis'])
    tax = Decimal(breakdown['source_tax_amount'])
    previous = PayableClassificationRecord.objects.filter(
        tenant_id=actor.tenant_id, kind='shipment', shipment=shipment).first()
    reason = '对公付款审批自动确认供应商税额'
    with domain_write():
        snapshot = ShipmentPayableTax.objects.create(
            tenant=actor.tenant, created_by=actor, shipment=shipment, taxable_amount=basis,
            tax_rate=rate, added_tax_amount=tax, reason=reason)
        services._event(actor, snapshot, 'shipment_payable_tax_confirmed', keyval,
            {'request_id': row.pk, 'tax_rate': str(rate), 'taxable_amount': str(basis), 'added_tax_amount': str(tax)})
    payable_classifications.save_classification(actor, 'shipment', shipment.pk, {
        'corporate_amount': basis + tax,
        'personal_amount': previous.personal_amount if previous else Decimal(0),
        'currency': row.currency or 'CNY', 'reason': reason,
        'expected_version': previous.version if previous else 0,
        'expected_source_version': shipment.version,
        'expected_payable_amount': Decimal(summary['due_amount']) + tax,
    }, keyval)


class CreateInput(serializers.Serializer):
    currency=serializers.RegexField(r'^[A-Z]{3}$',required=False)
    exchange_rate=serializers.DecimalField(max_digits=20,decimal_places=8,required=False)
    amount=serializers.DecimalField(max_digits=24,decimal_places=4,min_value=Decimal('.0001'))
    payment_nature=serializers.ChoiceField(('corporate','personal'),required=False)
    amount_basis=serializers.ChoiceField(('gross','net'),required=False)
    expected_gross_amount=serializers.DecimalField(max_digits=24,decimal_places=4,min_value=Decimal('.0001'),required=False)
    payee_account_id=serializers.IntegerField(min_value=1)
    fee_item_id=serializers.IntegerField(min_value=1,required=False)
    reason=serializers.CharField(max_length=10000)
    plan_line_id=serializers.CharField(max_length=64, required=False)
    plan_version=serializers.IntegerField(min_value=1, required=False)

class RequestAPI(InternalAPI):
    def get(self,request,kind,pk):
        _source(request.user,kind,pk,VIEW)
        qs=PR.objects.filter(tenant_id=request.user.tenant_id,kind=kind,source_id=pk).select_related('approval','payment','payee_account','batch__approval').prefetch_related('payment__reversal', Prefetch('vouchers',queryset=active_vouchers(SupplyPaymentRequestVoucher.objects.all()).defer('content'),to_attr='_voucher_rows'))
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
        actor=request.user; services._tenant_lock(actor); services._internal(actor); obj=_source(actor,kind,pk,MANAGE)
        data=CreateInput(data=request.data); data.is_valid(raise_exception=True); p=data.validated_data
        keyval=key(request); digest=services.request_hash({**p,'kind':kind,'source_id':pk})
        replay=PR.objects.select_for_update().filter(tenant_id=actor.tenant_id,idempotency_key=keyval).first()
        if replay:
            if replay.request_hash!=digest: raise ValidationError('幂等键已用于不同内容。')
            return Response({'data':request_data(actor,replay)})
        account=costs.PayeeAccount.objects.filter(tenant_id=actor.tenant_id,active=True,pk=p['payee_account_id'],**costs._payee_owner(kind,obj)).first()
        if not account: raise ValidationError('收款账户无效或不属于当前业务对象。')
        if p.get('payment_nature') and p['payment_nature'] != account.nature:
            raise ValidationError({'payee_account_id': '收款账户与选择的付款性质不一致。'})
        from .payment_approval_api import approval_required
        if not approval_required(actor):
            raise ValidationError('付款审批已关闭，请使用手工登记。')
        confirmed_currency=costs.validate_payment_currency(actor,kind,obj,p.get('currency',''))
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
        if p.get('amount_basis') == 'net':
            if kind != 'shipment' or account.nature != 'corporate':
                raise ValidationError({'amount_basis': '只有对公供应商货款可按未税金额计税申请。'})
            item['corporate_tax'] = corporate_request_amount(amt, summary)
            amt = Decimal(item['corporate_tax']['gross_amount'])
            if p.get('expected_gross_amount', amt) != amt:
                raise ValidationError('正报金额已变化，请刷新货款后重新申请。')
        remaining = Decimal(summary['remaining_amount']) if summary['remaining_amount'] is not None else None
        breakdown = item.get('corporate_tax', {})
        if remaining is not None and 'confirm_tax_rate' in breakdown:
            remaining += Decimal(breakdown['source_tax_amount'])
        if remaining is None or amt > remaining: raise ValidationError('申请金额超过当前应付余额。')
        reserved=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=pk,status='submitted',payment__isnull=True).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(s=Sum('amount'))['s'] or Decimal(0)
        if amt + reserved > remaining: raise ValidationError('已有未结申请占用余额。')
        from .payment_fx import snapshot as fx_snapshot
        exchange_rate, cny_amount = fx_snapshot(confirmed_currency, amt, p.get('exchange_rate'))
        plan = None; plan_line = None
        if p.get('plan_line_id') is not None or p.get('plan_version') is not None:
            if kind not in ('shipment', 'domestic_freight', 'batch') or not p.get('plan_line_id') or p.get('plan_version') is None:
                raise ValidationError({'plan_line_id': '须同时提供有效的付款计划明细和版本。'})
            plan, plan_line, balance = find_plan_line(actor, kind, pk, p['plan_line_id'], p['plan_version'])
            from .payment_plans import _party
            if plan.party_snapshot != _party(kind, obj): raise ValidationError('付款计划往来单位已变化。')
            expected_nature = plan_line.get('nature')
            if account.nature != expected_nature: raise ValidationError('收款账户性质与付款计划明细不匹配。')
            if confirmed_currency != (plan_line.get('currency') or plan.currency): raise ValidationError('申请币种与付款计划明细不匹配。')
            if str(plan_line.get('fee_item_id') or '') != str(p.get('fee_item_id') or ''): raise ValidationError('费用项目与付款计划明细不匹配。')
            if amt > balance['available_amount']: raise ValidationError('付款计划明细可用金额不足。')
        with domain_write():
            snapshot = {**plan_line, 'line_id': str(p['plan_line_id'])} if plan_line else {}
            row,created=PR.objects.get_or_create(tenant=actor.tenant,created_by=actor,idempotency_key=keyval,defaults={'currency':confirmed_currency,'exchange_rate':exchange_rate,'cny_amount':cny_amount,'kind':kind,'source_id':pk,'amount':amt,'payee_account':account,'account_snapshot':costs._payee_data(account),'fee_item':fee_item,'item_snapshot':item,'plan':plan,'plan_line_id':p.get('plan_line_id',''),'plan_snapshot':snapshot,'reason':p['reason'],'request_hash':digest})
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
            from .payment_approval_api import approval_required
            if not approval_required(actor):
                raise ValidationError('付款审批已关闭，请使用手工登记。')
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
            breakdown = row.item_snapshot.get('corporate_tax')
            if breakdown:
                current = corporate_request_amount(Decimal(breakdown['net_amount']), summary)
                comparable = {k: v for k, v in breakdown.items() if k != 'confirm_tax_rate'}
                if current not in (breakdown, comparable) or Decimal(current['gross_amount']) != row.amount:
                    raise ValidationError('单据计税口径已变化，请取消草稿后重新申请。')
                if 'confirm_tax_rate' in current:
                    confirm_corporate_tax(actor, obj, row, current, summary, keyval)
                    summary = costs.payment_summary(actor, kind, pk)['summary']
            reserved=PR.objects.filter(tenant_id=actor.tenant_id,kind=kind,source_id=pk,status='submitted',payment__isnull=True).exclude(pk=row.pk).exclude(approval__status__in=['rejected','withdrawn']).exclude(batch__approval__status__in=['rejected','withdrawn']).aggregate(s=Sum('amount'))['s'] or Decimal(0)
            if summary['remaining_amount'] is None or row.amount+reserved>Decimal(summary['remaining_amount']): raise ValidationError('申请金额超过可用余额（含其他未结申请）。')
            number=obj.number; suffix=row.account_snapshot.get('account_number','')[-4:]
            from apps.workflows.services import resolve_payment_flow
            nature = row.item_snapshot.get('nature') or row.account_snapshot.get('nature')
            flow, flows = resolve_payment_flow(actor=actor, sources=[(kind, pk, row.amount, nature, True)])
            snapshot = {'rule_id': flow.pk, 'flow_key': flow.flow_key, 'version': flow.version, 'payment_kind': kind, 'nature': nature, 'department_key': flow.department_key, 'notify_feishu': flow.notify_feishu, 'minimum_amount': str(flow.minimum_amount), 'maximum_amount': str(flow.maximum_amount) if flow.maximum_amount is not None else None, 'reviewer_id': flow.reviewer_id, 'finance_handler_id': flow.finance_handler_id,
                'rules': [{'rule_id': r.pk, 'flow_key': r.flow_key, 'version': r.version, 'payment_kind': r.payment_kind, 'nature': r.nature, 'department_key': r.department_key, 'minimum_amount': str(r.minimum_amount), 'maximum_amount': str(r.maximum_amount) if r.maximum_amount is not None else None} for r in flows]}
            tax_note = f'；未税 {breakdown["net_amount"]}；税额 {breakdown["tax_amount"]}；正报金额 {breakdown["gross_amount"]}' if breakdown else ''
            approval=ApprovalRequest.objects.create(tenant=actor.tenant,approval_type='finance',title=f'付款申请 {number}',business_type='supply_payment_request',business_id=str(row.pk),requested_by=actor,designated_reviewer=flow.reviewer,workflow_snapshot=snapshot,reason=f'{number} {row.amount} {row.account_snapshot.get("nature","")} 尾号{suffix}；项目：{row.item_snapshot.get("name", "整单款项")}{tax_note}；申请理由：{row.reason} /supply-chain/costs?kind={kind}&id={pk}&payment_request_id={row.pk}',idempotency_key=f'payreq:{row.pk}')
            row.approval=approval; row.status='submitted'; row.version+=1
            with domain_write(): row.save(update_fields=['approval','status','version'])
            from apps.workflows.services import write_workflow_audit
            write_workflow_audit(approval,resource_type='approval',actor=actor,action='submit',to_status='pending',detail={})
            from apps.integrations.feishu_native_approval import queue_payment_approval
            native = queue_payment_approval(approval, row, form_input=request.data.get('feishu'))
            if native:
                row.notification_status='native_queued'; row.notification_error=''
            else:
                try:
                    from apps.integrations.feishu_delivery import notify_approval
                    with transaction.atomic(): result=notify_approval(approval.pk)
                    row.notification_status=result.get('status','queued'); row.notification_error=''
                except Exception as exc:
                    row.notification_status='error'; row.notification_error='飞书通知入队失败，请检查通知配置后重试。'
            with domain_write(): row.save(update_fields=['notification_status','notification_error'])
        elif action=='cancel':
            if row.approval_id and row.approval.workflow_snapshot.get('approval_provider') == 'feishu':
                raise ValidationError('此申请由飞书统一处理，请在飞书撤回；已通过申请需由财务复核。')
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
            if not finance_allowed(actor,row.currency): raise PermissionDenied()
            if row.approval.workflow_snapshot.get('approval_provider') == 'feishu':
                raise ValidationError('飞书审批正在处理，请在飞书查看；提交异常由后台安全重试。')
            from apps.integrations.feishu_delivery import notify_approval
            try:
                with transaction.atomic(): result=notify_approval(row.approval_id)
                row.notification_status=result.get('status','queued'); row.notification_error=''
            except Exception as exc:
                row.notification_status='error'; row.notification_error='飞书通知入队失败，请检查通知配置后重试。'
            with domain_write(): row.save(update_fields=['notification_status','notification_error'])
        with domain_write(): services._event(actor,row,'request_'+action,keyval,payload)
        return Response({'data':request_data(actor,row)})
