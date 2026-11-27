import os,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'saas-collab-system';sys.path.insert(0,str(root/'backend'))
os.environ['DJANGO_SETTINGS_MODULE']='config.settings.dev'
from django.conf import settings
settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}
import django;django.setup()
from django.db import connection
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from apps.issue_tracking.business_todos import pending_batches
from apps.supply_chain.models import DispatchBatch
schemas={
'supply_chain_dispatchbatch':'id integer primary key, tenant_id integer,status text,stage text,arrived_warehouse_at datetime',
'supply_chain_inboundnotificationconfig':'id integer,tenant_id integer,arrival_unreceived_reminder_days integer',
'supply_chain_inboundorder':'id integer,batch_id integer,status text',
'supply_chain_dispatchmembership':'id integer,batch_id integer,active_guard bool',
'supply_chain_dispatchallocation':'id integer,membership_id integer,shipment_line_id integer,quantity integer',
'supply_chain_shipmentline':'id integer,shipment_id integer,is_active bool',
'supply_chain_suppliershipment':'id integer,status text',
'supply_chain_inboundshortagetermination':'id integer,batch_id integer,quantity integer'}
with connection.cursor() as c:
 for table,cols in schemas.items():c.execute(f'CREATE TABLE {table} ({cols})')
 c.execute("INSERT INTO supply_chain_inboundnotificationconfig VALUES(1,1,3)")
 c.execute("INSERT INTO supply_chain_suppliershipment VALUES(1,'submitted')")
 c.execute("INSERT INTO supply_chain_shipmentline VALUES(1,1,1)")
 for i,date,stage,status,tenant in [(1,'2026-11-22 18:00:00','arrived_warehouse','active',1),(2,'2026-11-23 17:00:00','arrived_warehouse','active',1),(3,'2026-11-20','arrived_warehouse','cancelled',1),(4,'2026-11-20','departed','active',1),(5,'2026-11-20','arrived_warehouse','active',1),(6,'2026-11-20','arrived_warehouse','active',1),(7,'2026-11-20','arrived_warehouse','active',2),(8,'2026-11-20','arrived_warehouse','active',1)]:
  c.execute('INSERT INTO supply_chain_dispatchbatch VALUES(%s,%s,%s,%s,%s)',[i,tenant,status,stage,date]);c.execute('INSERT INTO supply_chain_dispatchmembership VALUES(%s,%s,1)',[i,i]);c.execute('INSERT INTO supply_chain_dispatchallocation VALUES(%s,%s,1,10)',[i,i])
 c.execute("INSERT INTO supply_chain_inboundorder VALUES(1,5,'confirmed')")
 c.execute("INSERT INTO supply_chain_inboundorder VALUES(2,1,'draft')")
 c.execute("INSERT INTO supply_chain_inboundshortagetermination VALUES(1,6,10)")
 c.execute("INSERT INTO supply_chain_inboundshortagetermination VALUES(2,8,20)")
class Tests(unittest.TestCase):
 def run_query(self,allowed=True):
  with patch('apps.permissions.services.check_user_permission',return_value=allowed),patch('apps.supply_chain.logistics.batches_for',side_effect=lambda actor:DispatchBatch.objects.filter(tenant_id=actor.tenant_id)):
   return list(pending_batches(SimpleNamespace(tenant_id=1),datetime(2026,11,26,tzinfo=ZoneInfo('Asia/Shanghai'))).values_list(*(['pk','pending_quantity'] if allowed else ['pk'])))
 def test_calendar_partial_cancelled_closed_scope(self):self.assertEqual(self.run_query(),[(1,10)])
 def test_no_permission(self):self.assertEqual(self.run_query(False),[])
 def test_configured_days(self):
  with connection.cursor() as c:c.execute('UPDATE supply_chain_inboundnotificationconfig SET arrival_unreceived_reminder_days=10')
  try:self.assertEqual(self.run_query(),[])
  finally:
   with connection.cursor() as c:c.execute('UPDATE supply_chain_inboundnotificationconfig SET arrival_unreceived_reminder_days=3')
unittest.main()

