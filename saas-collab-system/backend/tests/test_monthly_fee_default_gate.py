from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from apps.supply_chain import costs


class MissingFeeDefaultGateTests(SimpleTestCase):
    def setUp(self):
        self.owner = type("Owner", (), {"number": "IN-1", "domestic_terms_snapshot": {}})()
        self.line = type("Line", (), {"pk": 7})()

    @override_settings(MONTHLY_PRODUCT_COST_ENABLED=False)
    @patch("apps.supply_chain.costs.source_lines")
    def test_missing_non_inbound_fee_is_unknown_with_issue_by_default(self, source_lines):
        source_lines.return_value = [self.line]
        issues = []
        result = costs.fee_amounts("shipment", self.owner, None, issues)
        self.assertEqual(result, {7: None})
        self.assertEqual(len(issues), 1)

    @override_settings(MONTHLY_PRODUCT_COST_ENABLED=False)
    @patch("apps.supply_chain.costs.source_lines")
    def test_missing_inbound_fee_is_empty_by_default(self, source_lines):
        source_lines.return_value = [self.line]
        issues = []
        self.assertEqual(costs.fee_amounts("inbound", self.owner, None, issues), {})
        self.assertEqual(issues, [])

    @override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
    @patch("apps.supply_chain.costs.source_lines")
    def test_monthly_opt_in_estimates_missing_fee_as_zero(self, source_lines):
        source_lines.return_value = [self.line]
        issues = []
        self.assertEqual(costs.fee_amounts("inbound", self.owner, None, issues), {7: costs.ZERO})
        self.assertEqual(issues, [])

    @override_settings(MONTHLY_PRODUCT_COST_ENABLED=False)
    def test_partial_calculation_keeps_legacy_clearance_issue(self):
        inbound = type("Inbound", (), {"pk": 9, "number": "IN-1"})()
        inbound_qs = Mock()
        inbound_qs.order_by.return_value = [inbound]
        empty_receipts = Mock()
        empty_receipts.select_related.return_value.order_by.return_value = []
        extra = Mock()
        extra.exists.return_value = False
        version = type("Version", (), {"state": "estimated", "sequence": 1, "pk": 1})()
        manager = Mock()
        manager.filter.return_value.order_by.return_value.first.return_value = None
        with patch("apps.supply_chain.inbound_costs.InboundOrder.objects.filter", return_value=inbound_qs), \
             patch("apps.supply_chain.inbound_costs.InternalStockReceiptLine.objects.filter", side_effect=[empty_receipts, extra]), \
             patch("apps.supply_chain.inbound_costs.costs.source_lines", return_value=[]), \
             patch("apps.supply_chain.inbound_costs.CostVersion.objects", manager), \
             patch("apps.supply_chain.inbound_costs.domain_write"), \
             patch("apps.supply_chain.inbound_costs.CostVersion.objects.create", return_value=version), \
             patch("apps.supply_chain.inbound_costs.services._event"):
            issues = []
            inbound_costs_result = __import__("apps.supply_chain.inbound_costs", fromlist=["calculate_partial"])
            inbound_costs_result.calculate_partial(
                actor=type("Actor", (), {"tenant": None})(), batch=None, source={}, fingerprint="f",
                lines=[], revisions={}, batch_qty={}, goods_taxes={}, collection={}, freight={}, issues=issues,
                payload={}, key="k", digest="d")
        self.assertTrue(any("清货费用未维护" in issue for issue in issues))
