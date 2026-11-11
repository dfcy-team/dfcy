from datetime import timedelta
from unittest.mock import Mock, patch
import pytest
from django.utils import timezone
from apps.supply_chain import inbound_notifications as n
from apps.supply_chain.inbound_notify_models import InboundNotificationConfig as Config,InboundNotificationOutbox as Outbox
from apps.integrations.models import FeishuConnection
from tests.test_supply_chain_v2_foundation import world,internal_user
from tests.test_supply_chain_v2_logistics import setup,client,create,arrive,generate,checked,write,BASE
from tests.test_supply_payment_request_evidence import _grant
pytestmark=pytest.mark.django_db

def complete(world,enabled=True):
 a,sh,_,carrier,wh=setup(world)
 FeishuConnection.objects.create(tenant=a.tenant,enabled=True,app_id='test',app_secret_ref='fake-ref',created_by=a,updated_by=a)
 if enabled:Config.objects.create(tenant=a.tenant,chat_id='oc_test',chat_name='运营群',country_codes=['US'],enabled=True)
 api=client(a);batch,_=create(api,[sh],carrier);batch=arrive(api,batch);inbound=generate(api,batch,wh);inbound,_=checked(api,inbound)
 assert Outbox.objects.count()==0
 r=write(api,f'inbound-orders/{inbound["id"]}/confirm/',{'expected_version':inbound['version']},'notify-confirm')
 assert r.status_code==200,r.data
 return a,api,inbound

def test_completion_once_source_scope_and_snapshot(world):
 a,api,inbound=complete(world);row=Outbox.objects.get();assert row.status=='pending' and row.payload['elements']
 r=write(api,f'inbound-orders/{inbound["id"]}/confirm/',{'expected_version':inbound['version']},'notify-confirm')
 assert r.status_code==200 and Outbox.objects.count()==1
 assert api.get(BASE+f'inbound-orders/{inbound["id"]}/notifications/').status_code==200
 other=client(internal_user(world,'notify-denied',scope='own'))
 assert other.get(BASE+f'inbound-orders/{inbound["id"]}/notifications/').status_code==404

def test_no_config_skips(world):
 complete(world,False);assert Outbox.objects.get().status=='skipped';assert n.dispatch_due()==0

def test_retry_uuid_receipt_and_dedup(world,monkeypatch):
 complete(world);calls=[]
 def send(connection,chat_id,payload,key):
  calls.append(key)
  if len(calls)==1:raise TimeoutError()
  return 'om_receipt'
 monkeypatch.setattr(n, 'GroupMessageService', Mock(return_value=Mock(send_group=send)))
 assert n.dispatch_due()==0
 row=Outbox.objects.get();assert row.attempts==1 and row.status=='pending'
 Outbox.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now())
 assert n.dispatch_due()==1
 row.refresh_from_db();assert row.receipt_id=='om_receipt' and calls[0]==calls[1]
 assert n.dispatch_due()==0 and len(calls)==2

def test_lease_and_expired_uncertain_result(world):
 complete(world);Outbox.objects.update(lease_until=timezone.now()+timedelta(minutes=1))
 with patch.object(n.GroupMessageService,'send_group') as send:
  assert n.dispatch_due()==0;send.assert_not_called()
  Outbox.objects.update(lease_until=None,attempts=1,created_at=timezone.now()-timedelta(hours=1))
  assert n.dispatch_due()==0;send.assert_not_called()
 assert Outbox.objects.get().status=='needs_review'

def test_config_permission_version_all_countries(world):
 a,*_=setup(world);api=client(a);path='settings/inbound-notification/'
 p={'expected_version':0,'chat_id':'oc_test','chat_name':'运营群','country_codes':[],'all_countries':True,'enabled':True}
 assert write(api,path,p,'cfg',method='put').status_code==403
 from apps.permissions.models import Permission,UserRole
 permission,_=Permission.objects.update_or_create(code='feishu.notification.manage',defaults={'name':'notify','module':'feishu','action':'notification.manage','permission_type':'action','metadata':{}})
 for binding in UserRole.objects.filter(user=a):binding.role.permissions.add(permission)
 from apps.permissions.services import INTEGRATION_ROLE_CODES
 binding=UserRole.objects.filter(user=a).first();binding.role.code=next(iter(INTEGRATION_ROLE_CODES));binding.role.save()
 from apps.permissions.services import check_user_permission,get_permission_data_scopes
 assert check_user_permission(a,'feishu.notification.manage'), 'notification permission missing'
 assert check_user_permission(a,'supply.v2.manage'), 'supply permission missing'
 assert get_permission_data_scopes(a,'supply.v2.manage'), 'scope missing'
 FeishuConnection.objects.create(tenant=a.tenant,enabled=True,app_id='test',app_secret_ref='fake-ref',created_by=a,updated_by=a)
 r=write(api,path,p,'cfg',method='put');assert r.status_code==200,r.data
 assert r.data['data']['all_countries'] is True
 assert write(api,path,p,'cfg2',method='put').status_code==400
 assert write(api,path,{**p,'expected_version':1,'country_codes':['ZZ']},'bad',method='put').status_code==400


def test_disabled_pending_or_changed_application_is_not_sent(world):
 complete(world)
 Config.objects.update(enabled=False)
 with patch.object(n.GroupMessageService,'send_group') as send:
  assert n.dispatch_due()==0;send.assert_not_called()
 assert Outbox.objects.get().status=='skipped'
 Outbox.objects.update(status='pending');Config.objects.update(enabled=True)
 FeishuConnection.objects.update(app_id='changed-app')
 with patch.object(n.GroupMessageService,'send_group') as send:
  assert n.dispatch_due()==0;send.assert_not_called()
 assert Outbox.objects.get().status=='needs_review'


def test_outer_rollback_removes_completion_and_notification(world):
 from django.db import transaction
 from apps.supply_chain.models import InboundOrder,InternalStockReceipt
 with pytest.raises(RuntimeError):
  with transaction.atomic():
   complete(world)
   assert Outbox.objects.exists()
   raise RuntimeError('rollback')
 assert not Outbox.objects.exists() and not InternalStockReceipt.objects.exists()


def test_group_send_uses_chat_target_and_uuid_no_real_network():
 import json
 from types import SimpleNamespace
 service=n.GroupMessageService.__new__(n.GroupMessageService)
 response=SimpleNamespace(json=lambda:{'code':0,'data':{'message_id':'om_test'}})
 class Http:
  def request(self,*args,**kwargs):
   assert args[1].endswith('receive_id_type=chat_id')
   assert kwargs['json_body']['receive_id']=='oc_test'
   assert kwargs['json_body']['uuid']=='stable-key'
   assert json.loads(kwargs['json_body']['content'])=={'test':'card'}
   return response
 service.http=Http();service._tenant_token=lambda connection:'fake-token'
 assert service.send_group(SimpleNamespace(domain='feishu'),'oc_test',{'test':'card'},'stable-key')=='om_test'
