"""Atomic published-flow successor plus native finance widget mapping."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from apps.workflows.models import PaymentApprovalFlow
from apps.workflows.services import write_workflow_audit
from apps.permissions.services import check_user_permission, user_has_finance_permission
from apps.integrations.models import FeishuApprovalMapping
from apps.integrations.feishu_native_client import FeishuNativeClient
from apps.integrations.feishu_native_approval import _connection, _identity, definition_hash


class Command(BaseCommand):
    help='Prepare finance handoff configuration; dry-run unless --apply.'
    def add_arguments(self,p):
        p.add_argument('--tenant-id',type=int,required=True)
        p.add_argument('--flow-key',required=True)
        p.add_argument('--handler-id',type=int,required=True)
        p.add_argument('--approval-code',required=True)
        p.add_argument('--apply',action='store_true')
        p.add_argument('--finance-node-verified',action='store_true')
        p.add_argument('--attachment-host',action='append',default=[])
    def handle(self,*args,**o):
        tenant_id=o['tenant_id']
        current=PaymentApprovalFlow.objects.filter(tenant_id=tenant_id,flow_key=o['flow_key'],active=True,published=True).order_by('-version').first()
        handler=CustomUser.objects.filter(pk=o['handler_id'],tenant_id=tenant_id,is_active=True,user_type='internal').first()
        if not current or not handler:raise CommandError('Active flow or finance handler missing.')
        if not all(check_user_permission(handler,k) for k in ['supply.v2.view','supply.v2.manage']) or not user_has_finance_permission(handler,'finance.reconcile'):
            raise CommandError('Finance handler lacks existing business/finance permissions.')
        handler_open_id=_identity(handler)
        client=FeishuNativeClient();connection=_connection(tenant_id)
        definition=client.get_definition(connection,o['approval_code'])
        if definition.get('status')!='ACTIVE':raise CommandError('Approval template is not active.')
        widgets=definition.get('form',[])
        if isinstance(widgets,str):widgets=json.loads(widgets)
        def widget(name,kinds):
            rows=[w for w in widgets if w.get('name')==name and w.get('type') in kinds]
            if len(rows)!=1:raise CommandError('Finance field missing or ambiguous: '+name)
            if rows[0].get('required'):raise CommandError('Finance fields must not be globally required at application submission.')
            return rows[0]['id']
        date_id=widget('实际付款日期',['date'])
        voucher_id=widget('付款凭证',['attachmentV2','attachment','image','imageV2'])
        nodes=[n for n in definition.get('node_list',[]) if n.get('name')=='办理']
        if len(nodes)!=1:raise CommandError('Finance handling node is ambiguous.')
        node_id=nodes[0]['node_id'];hosts=o['attachment_host'] or ['feishu-approval-cdn']
        expected=definition_hash(definition)
        result={'status':'READY_FOR_REVIEW','write':False,'flow_id':current.pk,'reviewer_id':current.reviewer_id,'finance_handler_id':handler.pk,
            'finance_node_id':node_id,'date_widget_id':date_id,'voucher_widget_id':voucher_id,'definition_hash':expected,'attachment_hosts':hosts}
        if not o['apply']:
            self.stdout.write(json.dumps(result));return
        if not o['finance_node_verified']:raise CommandError('Finance node person and field permissions must be verified.')
        client.subscribe(connection,o['approval_code'])
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=tenant_id)
            flow=PaymentApprovalFlow.objects.select_for_update().get(pk=current.pk,active=True,published=True)
            if flow.finance_handler_id!=handler.pk:
                version=PaymentApprovalFlow.objects.filter(tenant_id=tenant_id,flow_key=flow.flow_key).aggregate(v=Max('version'))['v']+1
                fields=['tenant_id','flow_key','payment_kind','nature','department_key','payment_kinds','natures','department_keys','notify_feishu','minimum_amount','maximum_amount','reviewer_id']
                new=PaymentApprovalFlow.objects.create(**{f:getattr(flow,f) for f in fields},version=version,finance_handler=handler,published=True,active=True)
                PaymentApprovalFlow.objects.filter(pk=flow.pk).update(active=False)
                write_workflow_audit(new,resource_type='payment_flow',actor=None,action='configure_finance_handler',detail={'previous_flow_id':flow.pk,'finance_handler_id':handler.pk})
                flow=new
            for business_type in ['supply_payment_request','supply_payment_batch']:
                FeishuApprovalMapping.objects.update_or_create(tenant_id=tenant_id,flow_key=flow.flow_key,business_type=business_type,defaults={
                    'approval_code':o['approval_code'],'definition':definition,'definition_hash':expected,'reviewer_id':flow.reviewer_id,
                    'reviewer_open_id':_identity(flow.reviewer),'fixed_assignees_verified':True,'subscription_verified':True,'enabled':True,
                    'finance_node_id':node_id,'finance_date_widget_id':date_id,'finance_voucher_widget_id':voucher_id,'finance_attachment_hosts':hosts})
            result.update(status='ENABLED',write=True,flow_id=flow.pk,version=flow.version)
        self.stdout.write(json.dumps(result))
