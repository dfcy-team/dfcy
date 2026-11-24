import io,json
from unittest.mock import patch
import pytest
from django.core.management import call_command
from apps.workflows.models import PaymentApprovalFlow
from apps.integrations.models import FeishuApprovalMapping,FeishuIdentity
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_payment_request_evidence import _setup_request

@pytest.mark.django_db
def test_configure_finance_dryrun_then_versioned_apply_is_idempotent(world,monkeypatch):
    buyer,api,*_= _setup_request(world,monkeypatch)
    flow=PaymentApprovalFlow.objects.filter(tenant=buyer.tenant,active=True,published=True).first()
    assert flow
    FeishuIdentity.objects.update_or_create(tenant=buyer.tenant,user=buyer,defaults={'open_id':'finance-open','status':'active'})
    FeishuIdentity.objects.update_or_create(tenant=buyer.tenant,user=flow.reviewer,defaults={'open_id':'reviewer-open','status':'active'})
    definition={'status':'ACTIVE','form':[{'id':'actual-date','name':'实际付款日期','type':'date','required':False},{'id':'vouchers','name':'付款凭证','type':'attachmentV2','required':False}],'node_list':[{'node_id':'finance','name':'办理'}]}
    args=dict(tenant_id=buyer.tenant_id,flow_key=flow.flow_key,handler_id=buyer.pk,approval_code='template')
    with patch('apps.integrations.management.commands.configure_finance_handoff._connection',return_value=object()),patch('apps.integrations.management.commands.configure_finance_handoff.FeishuNativeClient') as cls:
        cls.return_value.get_definition.return_value=definition
        before=PaymentApprovalFlow.objects.count()
        out=io.StringIO();call_command('configure_finance_handoff',stdout=out,**args)
        assert json.loads(out.getvalue())['write'] is False
        assert PaymentApprovalFlow.objects.count()==before and not FeishuApprovalMapping.objects.exists()
        for _ in range(2):call_command('configure_finance_handoff',apply=True,finance_node_verified=True,stdout=io.StringIO(),**args)
    assert PaymentApprovalFlow.objects.count()==before+1
    flow.refresh_from_db();assert not flow.active and flow.finance_handler_id is None
    current=PaymentApprovalFlow.objects.get(tenant=buyer.tenant,flow_key=flow.flow_key,active=True,published=True)
    assert current.finance_handler_id==buyer.pk and current.reviewer_id==flow.reviewer_id
    assert FeishuApprovalMapping.objects.filter(finance_date_widget_id='actual-date',finance_voucher_widget_id='vouchers',enabled=True).count()==2
