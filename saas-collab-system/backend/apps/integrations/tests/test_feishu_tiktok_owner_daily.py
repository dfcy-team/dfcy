from datetime import date, datetime, timedelta, timezone as dt_timezone
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.integrations.feishu_report_cards import MAX_BYTES, report_chart_card
from apps.integrations.feishu_tiktok_owner_daily import (
    _authorized_ads_mappings, _authorized_video_stores, _ads_expected_coverage,
    _change, _window_for_store, build_tiktok_owner_report,
)


class TikTokOwnerDailyTests(SimpleTestCase):
    @patch("apps.integrations.feishu_tiktok_owner_daily.analytics_dimensions_allowed")
    @patch("apps.integrations.feishu_tiktok_owner_daily.mapping_allowed")
    @patch("apps.integrations.feishu_tiktok_owner_daily.advertising_store_scope", return_value=(None, {13}))
    @patch("apps.integrations.feishu_tiktok_owner_daily.check_user_permission", return_value=True)
    @patch("apps.integrations.feishu_tiktok_owner_daily.TikTokAdsAdvertiserMapping.objects.filter")
    def test_ads_mappings_require_dimension_and_integration_scope(self, query, permission, store_scope, mapping_scope, dimensions):
        user = SimpleNamespace(tenant_id=1)
        store = SimpleNamespace(pk=13, country_code="PH")
        allowed = SimpleNamespace(store=store, store_id=13, pk=1)
        foreign = SimpleNamespace(store=store, store_id=13, pk=2)
        query.return_value.select_related.return_value = [allowed, foreign]
        mapping_scope.side_effect = [True, False]
        dimensions.return_value = True
        self.assertEqual(_authorized_ads_mappings(user, [store]), [allowed])
        dimensions.assert_called_once_with(user, "analytics.view", {
            "platform": "tiktok", "store_id": "13", "country": "PH"})
        self.assertEqual(mapping_scope.call_count, 2)

    def test_ads_mappings_reject_denied_analytics_dimension(self):
        user = SimpleNamespace(tenant_id=1)
        store = SimpleNamespace(pk=13, country_code="PH")
        mapping = SimpleNamespace(store=store, store_id=13, pk=1)
        with ExitStack() as stack:
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.check_user_permission", return_value=True))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.advertising_store_scope", return_value=(None, {13})))
            query = stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.TikTokAdsAdvertiserMapping.objects.filter"))
            query.return_value.select_related.return_value = [mapping]
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.mapping_allowed", return_value=True))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.analytics_dimensions_allowed", return_value=False))
            self.assertEqual(_authorized_ads_mappings(user, [store]), [])

    def _render_ads_report(self, mappings, observed):
        store = SimpleNamespace(pk=13, name="店铺", country_code="PH", timezone="UTC")
        for mapping in mappings:
            mapping.store = store
            mapping.store_id = store.pk
            mapping.timezone = "UTC"
            mapping.advertiser_id = f"adv-{mapping.pk}"
            mapping.currency = getattr(mapping, "currency", "PHP")
        user = SimpleNamespace(pk=55, tenant_id=1)
        with ExitStack() as stack:
            store_query = stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.StoreMaster.objects.filter"))
            store_query.return_value.order_by.return_value = [store]
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.check_user_permission", return_value=True))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.query_dataset", return_value={"rows": []}))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily._authorized_video_stores", return_value=set()))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily._authorized_ads_mappings", return_value=mappings))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.mapping_allowed", return_value=True))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily.stored_days", return_value=observed))
            stack.enter_context(patch("apps.integrations.feishu_tiktok_owner_daily._window_for_store",
                                      return_value=(date(2026, 10, 28), date(2026, 11, 3), date(2026, 10, 21), date(2026, 10, 27))))
            return build_tiktok_owner_report(user, {}, delivery_store_ids=None)["summary"]

    def test_report_renders_missing_mapping_currency_as_unknown_coverage(self):
        mappings = [SimpleNamespace(pk=1), SimpleNamespace(pk=2)]
        observed = [{"date": (date(2026, 10, 28) + timedelta(days=i)).isoformat(), "advertiser_id": "adv-1", "currency": "PHP", "timezone": "UTC",
                     "platform_store_id": "shop-1", "relationship_verified": True, "cost": "10", "gross_revenue": "20"}
                    for i in range(7)]
        text = self._render_ads_report(mappings, observed)
        self.assertIn("映射日期覆盖 7/14", text)
        self.assertIn("已授权 GMV（部分覆盖）", text)
        self.assertIn("ROAS 未提供", text)

    def test_report_discards_conflicting_mapping_day_identities(self):
        mapping = SimpleNamespace(pk=1)
        observed = [{"date": "2026-11-01", "advertiser_id": "adv-1", "currency": "PHP", "timezone": "UTC",
                     "platform_store_id": platform_id, "relationship_verified": True, "cost": "100", "gross_revenue": "200"}
                    for platform_id in ("shop-a", "shop-b")]
        text = self._render_ads_report([mapping], observed)
        self.assertIn("映射日期覆盖 0/7", text)
        self.assertIn("花费 未提供 PHP", text)
        self.assertIn("已授权 GMV（部分覆盖） 未提供 PHP", text)
        self.assertIn("ROAS 未提供", text)

    def test_report_shows_entirely_missing_second_currency(self):
        mappings = [SimpleNamespace(pk=1, currency="USD"), SimpleNamespace(pk=2, currency="PHP")]
        observed = [{"date": (date(2026, 10, 28) + timedelta(days=i)).isoformat(),
                     "advertiser_id": "adv-1", "currency": "USD", "timezone": "UTC",
                     "platform_store_id": "shop-1", "relationship_verified": True,
                     "cost": "10", "gross_revenue": "20"} for i in range(7)]
        text = self._render_ads_report(mappings, observed)
        self.assertIn("花费 70.00 USD", text)
        self.assertIn("花费 未提供 PHP", text)
        php_line = next(line for line in text.splitlines() if "GMV Max 花费" in line and "PHP" in line)
        self.assertIn("映射日期覆盖 0/7", php_line)
        self.assertIn("ROAS 未提供", php_line)

    def test_ads_coverage_counts_mapping_days_and_missing_mapping_day_is_incomplete(self):
        start, end = date(2026, 10, 28), date(2026, 11, 3)
        maps = [SimpleNamespace(pk=1, currency="PHP"), SimpleNamespace(pk=2, currency="PHP")]
        rows = [{"mapping_id": mapping.pk, "date": (start + __import__("datetime").timedelta(days=i)).isoformat(),
                 "currency": "PHP"} for mapping in maps for i in range(7)]
        self.assertEqual(_ads_expected_coverage(maps, rows, "PHP", start, end), (14, 14))
        rows.pop()
        self.assertEqual(_ads_expected_coverage(maps, rows, "PHP", start, end), (13, 14))

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
        actions = [item for item in card["body"]["elements"] if item["tag"] == "button" and item["behaviors"][0]["type"] == "open_url"]
        self.assertEqual(len(actions), 2)
