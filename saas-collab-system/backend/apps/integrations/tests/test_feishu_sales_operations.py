from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
import json

from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.feishu_reports import build_report
from apps.integrations.feishu_report_cards import report_chart_card
from apps.integrations.feishu_sales_operations import build_operations_report


class DailySalesTests(SimpleTestCase):
    @patch('apps.integrations.feishu_reports.StoreMaster.objects.filter')
    @patch('apps.integrations.feishu_sales_operations._payload')
    @patch('apps.integrations.feishu_sales_operations.check_user_permission', return_value=True)
    def test_daily_digest_reuses_recipient_scope_and_safe_workbench_link(self, grant, query, relation):
        related = MagicMock()
        related.filter.return_value.values_list.return_value = [123]
        relation.return_value = related
        user = SimpleNamespace(pk=99, tenant_id=7)
        dates = {'date_from': '2026-10-22', 'date_to': '2026-10-22'}
        query.return_value = {'filters': {**dates, 'previous_from': '2026-10-21'}, 'generated_at': 'now',
                              'rows': [{'store_name': '[fake](https://evil.test)', 'country': 'PH', 'currency': 'PHP', 'sales_amount': '70', 'change_percent': '-30', 'roi': None, 'ad_reason': '覆盖未验证'}],
                              'currency_groups': [{'currency': 'PHP', 'sales_amount': '70', 'change_percent': '-30', 'roi': None, 'roi_delta': None}], 'has_next': True}
        report = build_report({'config': {'report_type': 'sales_daily', 'filters': dates}}, user)
        self.assertIs(query.call_args.args[0].user, user)
        self.assertEqual(query.call_args.args[0].query_params['view'], 'stores')
        self.assertEqual(query.call_args.args[0].query_params['page_size'], '20')
        self.assertEqual(query.call_args.args[0].delivery_store_ids, [123])
        card = report_chart_card(report, lambda p: 'https://example.test' + p)
        self.assertFalse(report['suppress_delivery'])
        link = next(x for x in card['body']['elements'] if x['tag'] == 'button')['behaviors'][0]['default_url']
        self.assertEqual(urlsplit(link).path, '/sales-management/overview')
        self.assertEqual(parse_qs(urlsplit(link).query), {'view': ['operations'], 'date_from': ['2026-10-22'], 'date_to': ['2026-10-22']})
        raw = json.dumps(card, ensure_ascii=False)
        self.assertIn('70.00 PHP', raw)
        self.assertNotIn('[fake](https://evil.test)', raw)
        self.assertIn('ROI 未就绪', raw)
        self.assertLess(len(raw.encode()), 28000)

    @patch('apps.integrations.feishu_sales_operations._payload')
    @patch('apps.integrations.feishu_sales_operations.check_user_permission', return_value=False)
    def test_denied_recipient_never_queries_facts(self, grant, query):
        with self.assertRaises(PermissionDenied):
            build_operations_report(object(), {'date_from': '2026-10-22', 'date_to': '2026-10-22'})
        query.assert_not_called()

    def test_multi_day_digest_is_rejected(self):
        with self.assertRaises(ValidationError):
            build_operations_report(object(), {'date_from': '2026-10-20', 'date_to': '2026-10-22'})
