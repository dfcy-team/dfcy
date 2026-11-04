import unittest

from apps.integrations.gmv_max_campaigns import campaign_report


def day(date='2026-11-01', cost='10', revenue='30', orders=2, **identity):
    return dict(store_code='TK1PH', advertiser_id='100', advertiser_name='Test',
                platform_store_id='200', currency='USD', timezone='Asia/Manila',
                date=date, snapshot_id=1, fetched_at='2026-11-02T00:00:00Z',
                campaigns=[dict(campaign_id='300', cost=cost, gross_revenue=revenue, orders=orders)],
                **identity)


class CampaignReportTests(unittest.TestCase):
    def test_weighted_totals_and_unknown_metadata(self):
        result = campaign_report([day(), day('2026-11-02', '30', '50', 6)], 3)[0]
        self.assertEqual(result['cost'], '40')
        self.assertEqual(result['roi'], '2')
        self.assertEqual(result['cost_per_order'], '5')
        self.assertEqual(result['covered_days'], 2)
        self.assertEqual(result['expected_days'], 3)
        self.assertIsNone(result['campaign_name'])
        self.assertEqual(result['campaign_type'], 'unknown')
        self.assertEqual(len(result['days']), 2)

    def test_identity_dimensions_do_not_merge(self):
        original = day()
        variants = [dict(original, **{key: value}) for key, value in
                    [('advertiser_id', '101'), ('store_code', 'TK2PH'),
                     ('platform_store_id', '201'), ('currency', 'PHP'),
                     ('timezone', 'Asia/Bangkok')]]
        self.assertEqual(len(campaign_report([original] + variants, 1)), 6)

    def test_empty_days_are_coverage_not_fabricated_campaign_zero(self):
        result = campaign_report([day(), dict(day('2026-11-02'), campaigns=[])], 2)[0]
        self.assertEqual(result['covered_days'], 2)
        self.assertEqual(len(result['days']), 1)

    def test_zero_denominators_and_empty_input(self):
        result = campaign_report([day(cost='0', revenue='0', orders=0)], 1)[0]
        self.assertIsNone(result['roi'])
        self.assertIsNone(result['cost_per_order'])
        self.assertEqual(campaign_report([], 1), [])

    def test_validated_decimal_order_string(self):
        result = campaign_report([day(orders='2.0')], 1)[0]
        self.assertEqual(result['orders'], 2)
        self.assertEqual(result['days'][0]['orders'], 2)
