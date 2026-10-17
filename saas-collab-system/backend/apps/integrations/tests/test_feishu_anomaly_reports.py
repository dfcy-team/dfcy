import json
from datetime import date,timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from django.test import SimpleTestCase
from apps.integrations.feishu_anomaly_reports import assemble_anomalies,compare,build_anomaly_report
from apps.integrations.feishu_reports import build_report
from apps.integrations.feishu_report_cards import report_chart_card

D=date(2026,10,17)
def rows(sid='1',current='70',currency='PHP',**extra):
 return [{'date':(D-timedelta(days=i)).isoformat(),'store_id':sid,'country':'PH','currency':currency,'gross_sales':current if i==0 else '100','expense':'100','broad_gmv':'500',**extra} for i in range(14)]
def source(data,**extra):return {'rows':data,'truncated':False,'dimension_labels':{'store_id':{'1':'示例店铺'},'country':{'PH':'菲律宾'}},**extra}

class AnomalyReportsTests(SimpleTestCase):
 def test_exact_positive_and_negative_thirty_percent(self):
  for value,expected in [('70',-30),('130',30)]:
   data=assemble_anomalies('sales_anomalies',source(rows(current=value)),D)
   self.assertEqual(len(data['items']),1)
   c=data['items'][0]['comparisons']['gross_sales'][0]
   self.assertEqual(c['change_percent'],expected);self.assertTrue(c['observed_threshold_met']);self.assertFalse(c['anomaly_confirmed'])
  self.assertEqual(assemble_anomalies('sales_anomalies',source(rows(current='70.01')),D)['items'],[])

 def test_rank_top_three_by_absolute_percentage_and_deduplicate_store(self):
  data=sum([rows(str(i),current=str(value)) for i,value in [(1,200),(2,50),(3,160),(4,10),(5,140)]],[])
  data+=rows('1',current='250',currency='MYR')
  report=assemble_anomalies('sales_anomalies',source(data),D)
  self.assertEqual([x['store_id'] for x in report['items']],['1','4','3'])
  self.assertEqual(report['eligible_stores'],5);self.assertEqual(report['omitted_stores'],2)
  self.assertEqual(report['items'][0]['currency'],'MYR')

 def test_one_valid_baseline_is_sufficient_and_missing_days_not_zero(self):
  sample=[r for r in rows() if r['date'] in [D.isoformat(),(D-timedelta(days=1)).isoformat()]]
  report=assemble_anomalies('sales_anomalies',source(sample),D)
  item=report['items'][0];self.assertEqual(len(report['items']),1)
  self.assertEqual(item['comparisons']['gross_sales'][1]['status'],'missing_dates')
  self.assertIsNone(item['comparisons']['gross_sales'][2]['value'])

 def test_no_current_record_or_zero_baseline_does_not_create_false_drop(self):
  self.assertEqual(assemble_anomalies('sales_anomalies',source(rows()[1:]),D)['items'],[])
  sample=rows(current='10');[r.update(gross_sales='0') for r in sample[1:]]
  self.assertEqual(assemble_anomalies('sales_anomalies',source(sample),D)['items'],[])

 def test_truncated_groups_never_become_rankings(self):
  report=assemble_anomalies('sales_anomalies',source(rows(),truncated=True),D)
  self.assertEqual(report['status'],'truncated');self.assertEqual(report['items'],[])

 def test_advertising_top_six_and_roas_week_ratio_is_weighted(self):
  data=[]
  for i in range(1,9):
   current=rows(str(i));current[0]['expense']=str(100+20*i);data+=current
  report=assemble_anomalies('advertising_anomalies',source(data),D)
  self.assertEqual(len(report['items']),6);self.assertEqual(report['items'][0]['store_id'],'8')
  sample=rows();week={d.isoformat() for d in [date(2026,10,5)+timedelta(days=i) for i in range(7)]}
  for r in sample:
   if r['date'] in week:r['expense']='10';r['broad_gmv']='100'
  next(r for r in sample if r['date']=='2026-10-05').update(expense='100',broad_gmv='100')
  _,comparisons=compare(sample,D,'roas')
  self.assertEqual(comparisons[2]['value'],Decimal(700)/Decimal(160))
  self.assertNotEqual(comparisons[2]['value'],Decimal(61)/7)

 def test_invalid_ad_metrics_are_not_zero_roas(self):
  sample=rows();sample[0].update(expense=None,broad_gmv='0')
  data=assemble_anomalies('advertising_anomalies',source(sample),D)
  self.assertEqual(data['items'],[])

 @patch('apps.integrations.feishu_anomaly_reports.query_dataset')
 def test_report_queries_recipient_scope_and_only_shop_daily_dataset(self,query):
  query.return_value=source(rows())
  user=object();report=build_report({'config':{'report_type':'sales_anomalies','format':'chart','filters':{'date_from':D.isoformat(),'date_to':D.isoformat()}}},user)
  self.assertIs(query.call_args.args[0].user,user)
  self.assertEqual(query.call_args.args[1]['dataset'],'sales')
  self.assertEqual(query.call_args.kwargs,{'use_cache':False})
  self.assertFalse(report['suppress_delivery'])
  query.return_value=source(rows(current='100'))
  self.assertTrue(build_anomaly_report('sales_anomalies',user,{'date_from':D.isoformat(),'date_to':D.isoformat()})['suppress_delivery'])

 def test_native_card_has_only_requested_metrics_and_four_bars(self):
  data=assemble_anomalies('sales_anomalies',source(rows()),D)
  card=report_chart_card({'title':'店铺GMV异常Top3','anomalies':data,'generated_at':'now'},lambda p:'https://example.test'+p)
  elements=card['body']['elements'];chart=next(e for e in elements if e['tag']=='chart')
  self.assertEqual(len(chart['chart_spec']['data']['values']),4)
  text=json.dumps(card,ensure_ascii=False)
  self.assertIn('昨日GMV',text);self.assertIn('待核验',text)
  self.assertNotIn('订单总量',text);self.assertNotIn('客单价',text)
  url=next(e for e in elements if e['tag']=='button')['behaviors'][0]['default_url'];q=parse_qs(urlsplit(url).query)
  self.assertEqual(q['store_id'],['1']);self.assertEqual(q['region'],['PH']);self.assertEqual(q['currency'],['PHP'])
  self.assertLessEqual(len(text.encode()),28000)
