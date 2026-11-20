import unittest
from datetime import date, timedelta

from apps.sales_management.abc_service import _aggregate_quantity_profile, _order_spu_totals
from apps.sales_management.composite_rules import evaluate_comprehensive_abc


class CompositeQuantityProfileTests(unittest.TestCase):
    def test_bundle_sku_and_component_demand_are_separate_facts(self):
        cutoff = date(2026, 11, 20)
        facts = {(900, cutoff): 3, (100, cutoff): 6}
        result = _aggregate_quantity_profile(facts, {100: 10}, cutoff, 90)
        self.assertEqual(result["sku_units"][900], 3)
        self.assertEqual(result["sku_units"][100], 6)
        self.assertEqual(result["spu_units"][10], 6)

    def test_spu_daily_max_sums_siblings_per_day_not_each_sku_peak(self):
        cutoff = date(2026, 11, 20)
        facts = {(1, cutoff): 8, (2, cutoff - timedelta(days=1)): 7}
        result = _aggregate_quantity_profile(facts, {1: 10, 2: 10}, cutoff, 90)
        self.assertEqual(result["spu_units"][10], 15)
        self.assertEqual(result["spu_max_day"][10], 8)

    def test_7_day_rank_ignores_older_peak_but_keeps_12_week_continuity(self):
        cutoff = date(2026, 11, 20)
        facts = {
            (1, cutoff - timedelta(days=10)): 99,
            (1, cutoff - timedelta(days=2)): 2,
        }
        result = _aggregate_quantity_profile(facts, {1: 10}, cutoff, 7)
        self.assertEqual(result["sku_units"][1], 2)
        self.assertEqual(result["sku_max_day"][1], 2)
        self.assertEqual(len(result["sku_active_weeks"][1]), 2)

    def test_exact_spu_order_max_sums_sibling_skus_within_same_order(self):
        self.assertEqual(_order_spu_totals({1: 8, 2: 7}, {1: 10, 2: 10}), {10: 15})

    def test_clean_many_order_35_percent_day_is_not_marked_concentrated(self):
        result = evaluate_comprehensive_abc(
            revenue_grade="B", units_grade="A", active_weeks_last12=8,
            active_weeks_last4=4, history_complete=True, maturity="mature",
            total_units=100, max_single_order_units=10, max_single_day_units=35,
        )
        self.assertEqual(result["grade"], "A")
        self.assertFalse(result["basis"]["single_order_share_anomaly"])
        self.assertFalse(result["basis"]["single_day_share_anomaly"])

    def test_partial_snapshot_preserves_known_continuity_as_reference_only(self):
        result = evaluate_comprehensive_abc(
            revenue_grade="B", units_grade="A", active_weeks_last12=7,
            active_weeks_last4=4, history_complete=False, maturity="mature",
            total_units=100, max_single_order_units=20, max_single_day_units=20,
        )
        self.assertEqual(result["grade"], "unavailable")
        self.assertEqual(result["reference_grade"], "A")
        self.assertTrue(result["basis"]["sustained"])

