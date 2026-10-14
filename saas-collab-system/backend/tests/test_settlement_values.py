"""Pure normalization regressions; runnable without Django or provider access."""

import unittest

from apps.influencers.settlement import (
    INELIGIBLE, NO_REFUND_MARKERS, SETTLED, TO_SETTLE,
    normalize_settlement_status, refund_marker,
)


class SettlementValuesTests(unittest.TestCase):
    def test_approved_enums(self):
        for incoming, expected in (("SETTLED", SETTLED), ("INELIGIBLE", INELIGIBLE), ("To-SETTLE", TO_SETTLE)):
            with self.subTest(incoming=incoming):
                self.assertEqual(normalize_settlement_status(incoming), expected)

    def test_canonical_values_and_whitespace(self):
        for value in (SETTLED, INELIGIBLE, TO_SETTLE):
            self.assertEqual(normalize_settlement_status(" " + value + " "), value)

    def test_csv_pending_alias_is_not_an_api_enum(self):
        self.assertEqual(normalize_settlement_status("\u5f85\u786e\u8ba4", csv=True), TO_SETTLE)
        with self.assertRaisesRegex(ValueError, "unknown_enum"):
            normalize_settlement_status("\u5f85\u786e\u8ba4")

    def test_missing_stays_null(self):
        for value in (None, "", " \t "):
            self.assertIsNone(normalize_settlement_status(value))

    def test_unknown_and_fulfillment_enums_fail_closed(self):
        for value in ("unknown", "COMPLETED", "\u5df2\u5b8c\u6210", "DELIVERED", False, 0, {}, []):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "^settlement_status: unknown_enum$"):
                normalize_settlement_status(value, csv=True)

    def test_explicit_no_refund_markers(self):
        for value in ("\u5426", "no", " No ", "FALSE", "0", "n", False, 0):
            self.assertIn(refund_marker(value), NO_REFUND_MARKERS)

    def test_missing_unknown_and_full_refunds_are_not_no(self):
        for value in (None, "", "maybe", "\u662f", "yes", True, 1):
            self.assertNotIn(refund_marker(value), NO_REFUND_MARKERS)
