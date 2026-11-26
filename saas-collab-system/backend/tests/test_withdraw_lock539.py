import ast,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
class OperationalError(Exception):pass
class StateConflict(Exception):pass
s=(Path(__file__).parents[1] / 'apps/supply_chain/withdraw_lock.py').read_text(encoding='utf8')
t=ast.parse(s);t.body=[n for n in t.body if isinstance(n,ast.FunctionDef)]
g={'OperationalError':OperationalError,'StateConflict':StateConflict,'Tenant':SimpleNamespace(objects=Mock()),'connection':SimpleNamespace(features=SimpleNamespace(has_select_for_update_nowait=True))};exec(compile(t,'helper','exec'),g)
class Tests(unittest.TestCase):
 def test_success(self):self.assertEqual(g['withdrawal_result'](lambda:7),7)
 def test_database_busy(self):
  for c in (1205,1213,3572):
   with self.assertRaises(StateConflict):g['withdrawal_result'](Mock(side_effect=OperationalError(c,'busy')))
 def test_unrelated_error(self):
  e=OperationalError(999,'other')
  with self.assertRaises(OperationalError) as c:g['withdrawal_result'](Mock(side_effect=e))
  self.assertIs(c.exception,e)
 def test_same_lock_scope(self):
  g['connection'].features.has_select_for_update_nowait=True
  g['lock_for_withdrawal'](SimpleNamespace(tenant_id=1));g['Tenant'].objects.select_for_update.assert_called_with(nowait=True);g['Tenant'].objects.select_for_update.return_value.get.assert_called_with(pk=1)
 def test_feature_fallback(self):
  g['connection'].features.has_select_for_update_nowait=False;g['lock_for_withdrawal'](SimpleNamespace(tenant_id=1));g['Tenant'].objects.select_for_update.assert_called_with()

if __name__ == "__main__": unittest.main()

