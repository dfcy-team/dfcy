import unittest
from dataclasses import FrozenInstanceError

from apps.sales_management.composite_rules import ABCThresholds, DEFAULT_THRESHOLDS, evaluate_comprehensive_abc


def evaluate(**overrides):
    args = {
        "revenue_grade": "C",
        "units_grade": "C",
        "active_weeks_last12": 6,
        "active_weeks_last4": 3,
        "history_complete": True,
        "maturity": "mature",
        "total_units": 100,
        "max_single_order_units": 0,
        "max_single_day_units": 0,
    }
    args.update(overrides)
    return evaluate_comprehensive_abc(**args)


class ComprehensiveABCRulesTests(unittest.TestCase):
    def test_revenue_a_is_a_even_when_sales_are_concentrated(self):
        result = evaluate(revenue_grade="A", units_grade="C", max_single_order_units=50)
        self.assertEqual(result["grade"], "A")
        self.assertTrue(result["basis"]["single_order_share_anomaly"])
        self.assertIn("revenue_A", result["reason_codes"])

    def test_units_a_with_sustained_clean_sales_is_a(self):
        result = evaluate(revenue_grade="C", units_grade="A")
        self.assertEqual(result["grade"], "A")
        self.assertIn("units_A_with_sustained_sales", result["reason_codes"])

    def test_week_thresholds_are_inclusive(self):
        result = evaluate(revenue_grade="C", units_grade="A", active_weeks_last12=6, active_weeks_last4=3)
        self.assertEqual(result["grade"], "A")
        self.assertTrue(result["basis"]["sustained"])

    def test_units_a_without_continuity_is_b(self):
        result = evaluate(revenue_grade="C", units_grade="A", active_weeks_last12=5, active_weeks_last4=3)
        self.assertEqual(result["grade"], "B")
        self.assertIn("units_A_without_sufficient_clean_continuity", result["reason_codes"])

    def test_single_order_anomaly_at_exactly_30_percent_is_flagged_and_units_a_is_b(self):
        result = evaluate(revenue_grade="C", units_grade="A", max_single_order_units=30)
        self.assertEqual(result["grade"], "B")
        self.assertTrue(result["basis"]["single_order_share_anomaly"])
        self.assertIn("suspected_order_or_day_concentration", result["reason_codes"])

    def test_single_day_anomaly_at_exactly_40_percent_is_flagged(self):
        result = evaluate(revenue_grade="C", units_grade="A", max_single_day_units=40)
        self.assertEqual(result["grade"], "B")
        self.assertTrue(result["basis"]["single_day_share_anomaly"])

    def test_b_in_either_component_yields_b(self):
        self.assertEqual(evaluate(revenue_grade="B", units_grade="C")["grade"], "B")
        self.assertEqual(evaluate(revenue_grade="C", units_grade="B")["grade"], "B")

    def test_both_c_yield_c_only_with_complete_mature_history(self):
        self.assertEqual(evaluate()["grade"], "C")
        result = evaluate(history_complete=False)
        self.assertEqual(result["grade"], "unavailable")
        self.assertEqual(result["reference_grade"], "unavailable")
        self.assertIn("incomplete_history_prevents_reference_C", result["reason_codes"])

    def test_missing_sales_days_are_unavailable_and_never_c(self):
        result = evaluate(history_complete=False, revenue_grade="C", units_grade="C")
        self.assertEqual(result["grade"], "unavailable")
        self.assertNotEqual(result["reference_grade"], "C")

    def test_missing_week_counts_are_unavailable(self):
        result = evaluate(active_weeks_last4=None)
        self.assertEqual(result["grade"], "unavailable")

    def test_new_and_unknown_maturity_are_separate(self):
        self.assertEqual(evaluate(maturity="new")["grade"], "new")
        self.assertEqual(evaluate(maturity="unknown")["grade"], "unavailable")

    def test_no_sales_is_not_fabricated_as_c(self):
        result = evaluate(revenue_grade="no_sales", units_grade="no_sales")
        self.assertEqual(result["grade"], "no_sales")
        self.assertEqual(result["reference_grade"], "no_sales")

    def test_single_zero_component_preserves_positive_contribution(self):
        self.assertEqual(evaluate(revenue_grade="no_sales", units_grade="A")["grade"], "A")
        self.assertEqual(evaluate(revenue_grade="no_sales", units_grade="A", active_weeks_last12=2, active_weeks_last4=2)["grade"], "B")
        self.assertEqual(evaluate(revenue_grade="A", units_grade="no_sales")["grade"], "A")
        self.assertEqual(evaluate(revenue_grade="no_sales", units_grade="B")["grade"], "B")
        self.assertEqual(evaluate(revenue_grade="no_sales", units_grade="A", history_complete=False)["reference_grade"], "A")

    def test_unavailable_component_does_not_produce_grade(self):
        result = evaluate(revenue_grade="unavailable", units_grade="A")
        self.assertEqual(result["grade"], "unavailable")

    def test_inventory_or_supply_values_are_not_inputs(self):
        result = evaluate()
        self.assertNotIn("inventory", result["basis"])
        self.assertNotIn("supply", result["basis"])

    def test_threshold_defaults_are_frozen_and_overrideable(self):
        with self.assertRaises(FrozenInstanceError):
            DEFAULT_THRESHOLDS.active_weeks_12_min = 4
        custom = ABCThresholds(active_weeks_12_min=4, active_weeks_4_min=2)
        result = evaluate(revenue_grade="C", units_grade="A", active_weeks_last12=4, active_weeks_last4=2, thresholds=custom)
        self.assertEqual(result["grade"], "A")

    def test_invalid_counts_and_ratios_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(active_weeks_last4=7)
        with self.assertRaises(ValueError):
            evaluate(total_units=-1)
        with self.assertRaises(ValueError):
            ABCThresholds(single_order_share_anomaly=2)

