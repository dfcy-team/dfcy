from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import parse_qs, urlsplit
import json

from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied, ValidationError
from PIL import Image, ImageDraw
from io import BytesIO

from apps.integrations.feishu_reports import build_report
from apps.integrations.feishu_report_cards import report_chart_card
from apps.integrations.feishu_sales_operations import build_operations_report
from apps.integrations.feishu_sales_image import render_sales_ranking_png


class DailySalesTests(SimpleTestCase):
    def test_current_image_labels_cutoff_and_does_not_render_full_day_comparison(self):
        report = {'operations': {'period': 'current', 'generated_at': '2026-10-26T09:00:00Z', 'filters': {}, 'rows': [
            {'store_name': '今日店铺', 'country': 'PH', 'currency': 'PHP', 'sales_amount': '12.34', 'change_percent': '-99', 'roi': '2'}
        ]}}
        texts = []
        original = ImageDraw.ImageDraw.text
        def capture(draw, xy, text, *args, **kwargs):
            texts.append(str(text)); return original(draw, xy, text, *args, **kwargs)
        with patch('apps.integrations.feishu_sales_image.ImageDraw.ImageDraw.text', new=capture):
            render_sales_ranking_png(report)
        self.assertIn('今日累计 · 店铺排行榜', texts)
        self.assertTrue(any('17:00:00' in text for text in texts))
        self.assertIn('缺同点基准', texts)
        self.assertFalse(any('-99' in text for text in texts))

    @patch('apps.integrations.feishu_sales_operations.transaction.atomic')
    @patch('apps.integrations.feishu_sales_operations.check_user_permission', return_value=True)
    @patch('apps.integrations.feishu_sales_operations._payload')
    def test_current_failure_preserves_available_completed_day(self, payload, grant, atomic):
        historical = {'rows': [{'sales_amount': '1'}], 'generated_at': 'now'}
        payload.side_effect = [historical, ValidationError('unavailable')]
        report = build_operations_report(object(), {'date_from': '2026-10-25', 'date_to': '2026-10-25'}, store_ids=[12])
        self.assertIs(report['operations'], historical)
        self.assertFalse(report['suppress_delivery'])
        self.assertIn('暂不可用', report['current_error'])
    @patch('apps.integrations.feishu_sales_operations.transaction.atomic')
    @patch('apps.integrations.feishu_reports.StoreMaster.objects.filter')
    @patch('apps.integrations.feishu_sales_operations._payload')
    @patch('apps.integrations.feishu_sales_operations.check_user_permission', return_value=True)
    def test_daily_digest_reuses_recipient_scope_and_safe_workbench_link(self, grant, query, relation, atomic):
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
        self.assertEqual(query.call_args.args[0].query_params['period'], 'current')
        card = report_chart_card(report, lambda p: 'https://example.test' + p)
        self.assertFalse(report['suppress_delivery'])
        link = next(x for x in card['body']['elements'] if x['tag'] == 'button')['behaviors'][0]['default_url']
        self.assertEqual(urlsplit(link).path, '/sales-management/overview')
        self.assertEqual(parse_qs(urlsplit(link).query), {'view': ['operations'], 'date_from': ['2026-10-22'], 'date_to': ['2026-10-22']})
        raw = json.dumps(card, ensure_ascii=False)
        self.assertIn('70.00 PHP', raw)
        self.assertNotIn('[fake](https://evil.test)', raw)
        self.assertIn('覆盖未验证', raw)
        self.assertNotIn('ROI 未就绪', raw)
        self.assertLess(len(raw.encode()), 28000)

    def test_ranking_image_groups_currency_ranks_and_preserves_missing_values(self):
        report = {'operations': {'filters': {'date_from': '2026-10-22'}, 'rows': [
            {'store_name': '次名店铺', 'country': 'PH', 'currency': 'PHP', 'sales_amount': '10', 'change_percent': None, 'roi': None, 'ad_reason': '广告费未采集'},
            {'store_name': '头名店铺', 'country': 'US', 'currency': 'USD', 'sales_amount': '20', 'change_percent': '2.5', 'roi': '1.2'},
            {'store_name': '首位店铺', 'country': 'PH', 'currency': 'PHP', 'sales_amount': '1234567.89', 'change_percent': '-1.3', 'roi': None, 'ad_reason': '广告费未采集'},
        ], 'currency_groups': [
            {'currency': 'PHP', 'sales_amount': '1234577.89', 'roi': None, 'ad_reason': '广告费未采集'},
            {'currency': 'USD', 'sales_amount': '20', 'roi': '1.2'},
            {'currency': 'EUR', 'sales_amount': '999', 'roi': None, 'ad_reason': '广告费未采集'},
        ]}}
        rendered_text = []
        original_text = ImageDraw.ImageDraw.text
        def capture_text(draw, xy, text, *args, **kwargs):
            rendered_text.append(str(text))
            return original_text(draw, xy, text, *args, **kwargs)
        with patch('apps.integrations.feishu_sales_image.ImageDraw.ImageDraw.text', new=capture_text):
            content = render_sales_ranking_png(report)
        image = Image.open(BytesIO(content))
        self.assertEqual(image.format, 'PNG')
        self.assertEqual(image.width, 960)
        self.assertGreater(image.height, 500)
        self.assertIn('GMV (PHP)', rendered_text)
        self.assertIn('GMV (USD)', rendered_text)
        self.assertIn('GMV (EUR)', rendered_text)
        self.assertTrue(any('GMV 999.00 EUR' in text for text in rendered_text))
        self.assertIn('缺广告费', rendered_text)
        self.assertIn('缺基准', rendered_text)
        self.assertIn('1,234,567.89', rendered_text)
        self.assertTrue(any('1,234,577.89' in text for text in rendered_text))
        self.assertLess(rendered_text.index('首位店铺'), rendered_text.index('次名店铺'))

    def test_oversized_currency_totals_fail_before_bitmap_allocation(self):
        report = {'operations': {'rows': [], 'currency_groups': [
            {'currency': f'C{index}', 'sales_amount': '1'} for index in range(5000)
        ]}}
        with patch('apps.integrations.feishu_sales_image.Image.new') as allocate:
            with self.assertRaisesRegex(ValueError, 'pixel budget'):
                render_sales_ranking_png(report)
        allocate.assert_not_called()

    @patch('apps.integrations.feishu_sales_operations._payload')
    @patch('apps.integrations.feishu_sales_operations.check_user_permission', return_value=False)
    def test_denied_recipient_never_queries_facts(self, grant, query):
        with self.assertRaises(PermissionDenied):
            build_operations_report(object(), {'date_from': '2026-10-22', 'date_to': '2026-10-22'})
        query.assert_not_called()

    def test_multi_day_digest_is_rejected(self):
        with self.assertRaises(ValidationError):
            build_operations_report(object(), {'date_from': '2026-10-20', 'date_to': '2026-10-22'})
