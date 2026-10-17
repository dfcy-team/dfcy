import json
from decimal import Decimal
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings
from apps.integrations.feishu_delivery import system_url
from apps.integrations.feishu_report_cards import report_chart_card, detail_path, MAX_BYTES
from apps.integrations.feishu_reports import _sum_rows


def section(dataset='sales', rows=None, **kwargs):
    return {'dataset': dataset, 'title': '销售', 'status': 'available', 'filters': {'date_from':'2026-10-16','date_to':'2026-10-16'}, 'data_range':'2026-10-16', 'rows': rows if rows is not None else [{'country':'菲律宾 PH','currency':'PHP','gross_sales':Decimal('123.45'),'order_count':2,'valid_order_count':2}], **kwargs}


@override_settings(FEISHU_SYSTEM_BASE_URL='https://system.example.com')
class FeishuChartCardTests(SimpleTestCase):
    def card(self, sections):
        return report_chart_card({'title':'日报','generated_at':'2026-10-17T09:00:00+08:00','sections':sections}, system_url)

    def test_native_chart_with_context_and_authenticated_detail_link(self):
        card=self.card([section()]);self.assertEqual(card['schema'],'2.0')
        elements=card['body']['elements'];chart=next(e for e in elements if e['tag']=='chart')
        self.assertEqual(chart['chart_spec']['data']['values'][0]['value'],123.45)
        self.assertIn('PHP',chart['chart_spec']['title']['text'])
        url=next(e for e in elements if e['tag']=='button')['behaviors'][0]['default_url']
        self.assertEqual(urlsplit(url).netloc,'system.example.com')
        self.assertEqual(parse_qs(urlsplit(url).query)['feishu_dataset'],['sales'])
        self.assertIn('date_to=2026-10-16',url)
        self.assertNotIn('user_id',url);self.assertNotIn('token',url)
        self.assertFalse(any(e['tag']=='img' for e in elements))

    def test_currency_groups_never_mix_in_one_chart(self):
        card=self.card([section(rows=[{'country':'PH','currency':'PHP','gross_sales':'3'},{'country':'MY','currency':'MYR','gross_sales':'4'}])])
        charts=[e for e in card['body']['elements'] if e['tag']=='chart']
        self.assertEqual(len(charts),2)
        self.assertEqual([len(c['chart_spec']['data']['values']) for c in charts],[1,1])

    def test_zero_metrics_keep_values_and_units(self):
        card=self.card([section(rows=[{'country':'PH','currency':'PHP','gross_sales':Decimal('0.00'),'order_count':0,'valid_order_count':0}])])
        text=''.join(e.get('content','') for e in card['body']['elements'] if e['tag']=='markdown')
        self.assertIn('0.00 PHP',text)
        self.assertIn('0 单',text)
        self.assertEqual(next(e for e in card['body']['elements'] if e['tag']=='chart')['chart_spec']['data']['values'][0]['value'],0)

    def test_quantity_chart_uses_pieces_not_order_currency(self):
        card=self.card([section('sales_skus',rows=[{'country':'PH','currency':'PHP','units_sold':2,'gross_sales':10,'unmapped_count':0}])])
        chart=next(e for e in card['body']['elements'] if e['tag']=='chart')['chart_spec']
        self.assertIn('（件）',chart['title']['text'])
        self.assertEqual(chart['axes'][0]['title']['text'],'件')

    def test_no_permission_and_no_data_do_not_render_charts_or_disclose_rows(self):
        card=self.card([section(status='no_permission',rows=[{'gross_sales':999999}]),section(status='no_data',rows=[],source_latest_date='2026-10-10')])
        raw=json.dumps(card,ensure_ascii=False)
        self.assertNotIn('999999',raw);self.assertNotIn('"tag": "chart"',raw)
        self.assertIn('2026-10-10',raw);self.assertIn('无此数据权限',raw)
        self.assertEqual(len([e for e in card['body']['elements'] if e['tag']=='button']),1)

    def test_invalid_and_missing_numbers_are_not_plotted_as_zero(self):
        rows=[{'country':str(v),'currency':'PHP','gross_sales':v} for v in [None,'NaN','Infinity',True,'bad']]
        card=self.card([section(rows=rows)])
        self.assertFalse(any(e['tag']=='chart' for e in card['body']['elements']))
        self.assertIn('未按零补齐',json.dumps(card,ensure_ascii=False))
        total=_sum_rows('sales',[{'country_code':'PH','currency':'PHP','gross_sales':None},{'country_code':'PH','currency':'PHP','gross_sales':10}])
        self.assertIsNone(total[0]['gross_sales'])

    def test_source_labels_cannot_inject_links_or_mentions(self):
        card=self.card([section(rows=[{'country':'<at id=all>[click](https://evil.test)','currency':'PHP','gross_sales':1}])])
        markdown=''.join(e.get('content','') for e in card['body']['elements'] if e['tag']=='markdown')
        self.assertNotIn('<at',markdown);self.assertIn(r'\[click\]',markdown)

    def test_payload_is_bounded_and_truncation_visible(self):
        rows=[{'country':'国家'*40+str(n),'currency':str(n),'gross_sales':n,'order_count':n,'valid_order_count':n} for n in range(100)]
        card=self.card([section(rows=rows,truncated=True) for _ in range(6)])
        self.assertLessEqual(len(json.dumps(card,ensure_ascii=False).encode()),MAX_BYTES)
        self.assertIn('限制',json.dumps(card,ensure_ascii=False))
        self.assertLess(len(card['body']['elements']),200)

    def test_detail_filters_allowlist_and_foreign_dataset(self):
        self.assertEqual(detail_path({'dataset':'https://evil.test'}),'/reports/basic')
        self.assertNotIn('token',detail_path(section(filters={'token':'secret','date_to':'bad','date_from':'2026-10-16'})))
