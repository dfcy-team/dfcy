import ast,unittest
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
p=Path('backend/apps/issue_tracking/business_todos.py')
tree=ast.parse(p.read_text(encoding='utf8'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='cutoff')
ns={'datetime':datetime,'time':__import__('datetime').time,'timedelta':__import__('datetime').timedelta,'BEIJING':ZoneInfo('Asia/Shanghai')}
exec(compile(ast.Module(body=[node],type_ignores=[]),'cutoff','exec'),ns)
class TestCutoff(unittest.TestCase):
 def test_default_calendar(self):
  self.assertEqual(ns['cutoff'](datetime(2026,11,26,0,0,tzinfo=ZoneInfo('Asia/Shanghai'))).isoformat(),'2026-11-24T00:00:00+08:00')
 def test_timezone_boundary(self):
  self.assertEqual(ns['cutoff'](datetime(2026,11,25,15,59,tzinfo=timezone.utc)).day,23)
  self.assertEqual(ns['cutoff'](datetime(2026,11,25,16,0,tzinfo=timezone.utc)).day,24)
 def test_parameter(self):
  self.assertEqual(ns['cutoff'](datetime(2026,11,26,tzinfo=ZoneInfo('Asia/Shanghai')),5).day,22)
 def test_provider_contract(self):
  s=p.read_text(encoding='utf8')
  for text in ["status='confirmed'","has_confirmed=False, pending_quantity__gt=0","status='active', stage='arrived_warehouse'","batches_for(actor)","InboundShortageTermination","arrival_unreceived_reminder_days"]:self.assertIn(text,s)
if __name__=='__main__':unittest.main()
