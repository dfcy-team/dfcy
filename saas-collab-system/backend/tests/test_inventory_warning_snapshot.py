import unittest
from apps.alerts.warning_snapshot import spu_key_shortage_ids
class SnapshotTests(unittest.TestCase):
 def test_full_sibling_group_marks_key_sku_shortage_and_ties(self):
  rows=[{'spu_id':2,'sku_id':1,'total_demand_quantity':50,'warning':{'warnings':['forecast_stockout']}},{'spu_id':2,'sku_id':2,'total_demand_quantity':25,'warning':{'warnings':[]}},{'spu_id':2,'sku_id':3,'total_demand_quantity':25,'warning':{'warnings':[]}},{'spu_id':3,'sku_id':4,'total_demand_quantity':100,'warning':{'warnings':['forecast_stockout']}}]
  self.assertEqual(spu_key_shortage_ids(rows),{1,4})
 def test_unknown_sales_does_not_make_sku_key(self):
  rows=[{'spu_id':1,'sku_id':1,'total_demand_quantity':None,'warning':{'warnings':['forecast_stockout']}}]
  self.assertEqual(spu_key_shortage_ids(rows),set())
if __name__=='__main__':unittest.main()
