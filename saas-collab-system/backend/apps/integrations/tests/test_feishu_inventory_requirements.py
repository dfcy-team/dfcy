from unittest.mock import patch
from django.test import SimpleTestCase
from apps.integrations.feishu_inventory_requirements import inventory_requirements
from apps.integrations.feishu_report_cards import report_chart_card

class InventoryRequirementsTests(SimpleTestCase):
 @patch('apps.integrations.feishu_inventory_requirements.query_dataset')
 def test_unmapped_demand_never_becomes_zero_and_original_formulas_preserved(self,q):
  q.return_value={'rows':[{'internal_sku':None,'units_sold':200,'unmapped_count':100}], 'truncated':False}
  user=object();r=inventory_requirements(user,{'date_to':'2026-10-17'},14)
  self.assertIs(q.call_args.args[0].user,user)
  self.assertEqual(q.call_args.args[1]['filters']['date_from'],'2026-10-11')
  self.assertEqual(r['sales_status'],'unmapped');self.assertFalse(r['actual_risk_evaluation_enabled'])
  self.assertEqual(r['unmapped_item_rows'],100)
  self.assertEqual(len(r['alerts']),5)
  self.assertIn('近7天总销量 × 14',r['alerts'][0]['formula'])
  self.assertIn('在生产',r['alerts'][1]['formula']);self.assertIn('最高子SKU',r['alerts'][2]['formula'])
  self.assertIn('每批次首次一次',r['alerts'][3]['frequency']);self.assertIn('第二次一次',r['alerts'][4]['frequency'])
  self.assertTrue(all(a['status']=='not_ready' for a in r['alerts']))
  card=report_chart_card({'inventory_requirements':r},lambda p:'https://example.test'+p)
  self.assertFalse(any(x['tag']=='chart' for x in card['body']['elements']))

 @patch('apps.integrations.feishu_inventory_requirements.query_dataset')
 def test_missing_sales_or_truncated_never_proves_no_risk(self,q):
  for src in [{'rows':[],'truncated':False},{'rows':[],'truncated':True}]:
   q.return_value=src;r=inventory_requirements(object(),{'date_to':'2026-10-17'})
   self.assertEqual(r['status'],'not_ready');self.assertIn('不代表当前没有',r['message'])
