from datetime import date, datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.integrations.feishu_report_cards import MAX_BYTES, report_chart_card
from apps.integrations.feishu_tiktok_owner_daily import (
    _authorized_video_stores, _change, _window_for_store, build_tiktok_owner_report,
)


class TikTokOwnerDailyTests(SimpleTestCase):
    def test_store_window_uses_store_timezone(self):
        store = SimpleNamespace(timezone="Asia/Manila")
        with patch("apps.integrations.feishu_tiktok_owner_daily.timezone.now") as now:
            now.return_value = datetime(2026, 11, 4, 9, 30, tzinfo=dt_timezone.utc)
            self.assertEqual(_window_for_store(store), (date(2026, 10, 28), date(2026, 11, 3), date(2026, 10, 21), date(2026, 10, 27)))

    def test_missing_and_zero_baselines_remain_unavailable(self):
        self.assertIsNone(_change(None, 10))
        self.assertIsNone(_change(10, None))
        self.assertIsNone(_change(10, 0))

    @patch("apps.integrations.feishu_tiktok_owner_daily.require_all_scope")
    @patch("apps.integrations.feishu_tiktok_owner_daily.check_user_permission", return_value=True)
    def test_video_read_requires_both_existing_video_actions_not_ads(self, permission, scopes):
        store = SimpleNamespace(pk=13)
        self.assertEqual(_authorized_video_stores(object(), [store]), {13})
        self.assertEqual([call.args[1] for call in scopes.call_args_list], ["influencers.outreach.view", "influencers.fulfillment.view"])
        self.assertIn("influencers.outreach.view", [call.args[1] for call in permission.call_args_list])

    @patch("apps.integrations.feishu_tiktok_owner_daily.StoreMaster.objects.filter")
    @patch("apps.integrations.feishu_tiktok_owner_daily.check_user_permission", return_value=True)
    def test_store_query_requires_direct_operator_even_if_delivery_scope_contains_leader_store(self, permission, query):
        user = SimpleNamespace(pk=55, tenant_id=1)
        query.return_value.order_by.return_value = []
        report = build_tiktok_owner_report(user, {}, delivery_store_ids=[13])
        self.assertTrue(report["suppress_delivery"])
        kwargs = query.call_args.kwargs
        self.assertEqual(kwargs["operator_id"], 55)
        self.assertEqual(kwargs["pk__in"], {13})

    def test_card_keeps_preview_text_and_all_detail_routes_within_native_limit(self):
        report = {"report_type": "tiktok_owner_daily", "title": "TikTok日报", "headline": "近7天",
                  "summary": "GMV 123.45 PHP；短视频：权限受限。",
                  "detail_links": [("/reports/basic?store_id=13", "销售详情"),
                                   ("/influencers?store_id=13", "视频详情")]}
        card = report_chart_card(report, lambda path: "https://system.example" + path)
        self.assertLessEqual(len(__import__("json").dumps(card, ensure_ascii=False).encode()), MAX_BYTES)
        text = "".join(item.get("content", "") for item in card["body"]["elements"] if item["tag"] == "markdown")
        self.assertIn("GMV 123.45 PHP", text)
        actions = [action for item in card["body"]["elements"] if item["tag"] == "action" for action in item["actions"]]
        self.assertEqual(len(actions), 2)
