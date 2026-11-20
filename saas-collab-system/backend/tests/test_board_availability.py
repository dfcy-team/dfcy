import copy,json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from django.http import QueryDict
from rest_framework.exceptions import PermissionDenied
from apps.sales_management import board_availability as b

class MemoryStore:
 def __init__(self):self.values={}
 def get(self,k):return self.values.get(k)
 def set(self,k,v,nx=False,ex=None):
  if nx and k in self.values:return False
  self.values[k]=v;return True
 def delete(self,k):self.values.pop(k,None)
 def eval(self,script,count,k,token):
  if self.get(k)==token:self.values.pop(k,None);return 1
  return 0
 def scan_iter(self,match,count):return iter([k for k in self.values if k.startswith(b.PREFIX+'active:')])

@pytest.fixture
def env(monkeypatch):
 c=MemoryStore();spec={'user_id':1,'tenant_id':1,'membership_id':None,'authority':'a','params':{'date_from':'2026-11-17','date_to':'2026-11-17','defer_inventory':'1','display_currency':'CNY'}}
 monkeypatch.setattr(b,'store',lambda:c);monkeypatch.setattr(b,'specification',lambda r:copy.deepcopy(spec));sender=Mock();monkeypatch.setattr(b.current_app,'send_task',sender);monkeypatch.setattr(b.time,'time',lambda:1000)
 return c,spec,sender

def test_cold_singleflight(env):
 c,s,send=env
 assert b.snapshot_payload(None)['availability']['state']=='warming'
 assert b.snapshot_payload(None)['availability']['retry_after']==2
 assert send.call_count==1 and send.call_args.kwargs['queue']=='realtime_board'

def test_fresh_no_calculation(env):
 c,s,send=env;c.set(b.snapshot_key(s),json.dumps({'generated_at':990,'payload':{'currency_groups':[{'sales_amount':'12'}]}}))
 r=b.snapshot_payload(None);assert r['availability']['state']=='fresh' and r['currency_groups'][0]['sales_amount']=='12';assert not send.called

def test_stale_survives_broker_failure(env):
 c,s,send=env;c.set(b.snapshot_key(s),json.dumps({'generated_at':900,'payload':{'currency_groups':[]}}));send.side_effect=RuntimeError('broker down')
 assert b.snapshot_payload(None)['availability']['state']=='refreshing';assert c.get(b.snapshot_key(s)+':refresh') is None

def test_expired_inventory_or_old_sales_not_served(env):
 c,s,_=env
 for created,until in [(300,None),(990,999)]:
  c.values.clear();c.set(b.snapshot_key(s),json.dumps({'generated_at':created,'valid_until':until,'payload':{'inventory_by_currency':{'old':1}}}))
  r=b.snapshot_payload(None);assert r['availability']['state']=='warming' and 'inventory_by_currency' not in r

def test_isolated_keys(env):
 _,s,_=env;k=b.snapshot_key(s)
 for field,value in [('tenant_id',2),('user_id',2),('membership_id',2),('authority','revoked')]:
  changed=copy.deepcopy(s);changed[field]=value;assert b.snapshot_key(changed)!=k
 changed=copy.deepcopy(s);changed['params']['display_currency']='PHP';assert b.snapshot_key(changed)!=k

def test_late_worker_does_not_release_new_lease(env):
 c,s,_=env;k=b.snapshot_key(s)+':refresh';c.set(k,'new');b.release(c,k,'old');assert c.get(k)=='new'

@pytest.mark.parametrize('changed',[True,False])
def test_publish_only_when_authority_unchanged(env,monkeypatch,changed):
 c,s,_=env;k=b.snapshot_key(s);c.set(k+':refresh','token');monkeypatch.setattr(b,'actor_request',lambda s:SimpleNamespace());monkeypatch.setattr(b,'authority',Mock(side_effect=['a','revoked' if changed else 'a']))
 import apps.sales_management.realtime_board as engine
 build=Mock(return_value={'currency_groups':[{'currency':'CNY'}]});monkeypatch.setattr(engine,'realtime_board_payload',build)
 b.refresh_board_snapshot.run(s,k,'token');assert build.call_count==1;assert bool(c.get(k)) is not changed;assert c.get(k+':refresh') is None

@pytest.mark.django_db
def test_real_scope_revocation_changes_key():
 from tests.test_sales_realtime_board import _fixture
 from apps.permissions.models import DataScope
 user,tenant,platform,shop,run,client=_fixture('board-cache-auth');q=QueryDict('date_from=2026-08-17&date_to=2026-08-17&defer_inventory=1&display_currency=CNY');r=SimpleNamespace(user=user,query_params=q,_permission_resolution_cache={});before=b.specification(r)
 shop.name='Routine sync heartbeat';shop.save();r._permission_resolution_cache={}
 assert b.snapshot_key(b.specification(r))==b.snapshot_key(before)
 shop.country_code='TH';shop.save();r._permission_resolution_cache={}
 assert b.snapshot_key(b.specification(r))!=b.snapshot_key(before)
 DataScope.objects.filter(tenant=tenant).update(config={'store_ids':[999]},scope_type='custom');r._permission_resolution_cache={};after=b.specification(r)
 assert b.snapshot_key(before)!=b.snapshot_key(after)
 user.is_active=False
 with pytest.raises(PermissionDenied):b.authority(r)


def test_prewarm_skips_revoked_member_and_continues(env,monkeypatch):
 c,s,send=env
 bad=copy.deepcopy(s);bad['user_id']=9
 for key,spec in [('bad',bad),('good',s)]:c.set(b.PREFIX+'active:'+key,json.dumps({'spec':spec,'seen_at':999}))
 def actor(spec):
  if spec['user_id']==9:raise PermissionDenied()
  return SimpleNamespace()
 monkeypatch.setattr(b,'actor_request',actor)
 assert b.prewarm_recent()==1
 assert c.get(b.PREFIX+'active:bad') is None
 assert send.call_count==1

@pytest.mark.django_db
def test_async_view_returns_scope_tag_on_store_failure(monkeypatch):
 import redis
 from tests.test_sales_realtime_board import _fixture,URL,DAY
 _,_,_,_,_,client=_fixture('board-cache-store-fail')
 monkeypatch.setenv('BOARD_AVAILABILITY_ENABLED','1')
 def fail():raise redis.ConnectionError('unavailable')
 monkeypatch.setattr(b,'store',fail)
 response=client.get(URL,{'date_from':DAY,'date_to':DAY,'display_currency':'CNY','defer_inventory':'1'})
 assert response.status_code==503
 assert response.data['data']['availability']['scope_version']
 assert response.data['code']=='BOARD_UPDATE_UNAVAILABLE'


@pytest.mark.django_db
def test_warming_is_transient_for_legacy_clients_and_deduplicates(monkeypatch):
 from tests.test_sales_realtime_board import _fixture,URL,DAY
 *_,client=_fixture('board-cache-warming-protocol')
 monkeypatch.setenv('BOARD_AVAILABILITY_ENABLED','1')
 c=MemoryStore();monkeypatch.setattr(b,'store',lambda:c);sender=Mock();monkeypatch.setattr(b.current_app,'send_task',sender)
 for attempt in range(2):
  response=client.get(URL,{'date_from':DAY,'date_to':DAY,'display_currency':'CNY','defer_inventory':'1'})
  assert response.status_code==503 and response.data['code']=='BOARD_WARMING'
  assert response.data['data']['availability']['state']=='warming'
 assert sender.call_count==1
