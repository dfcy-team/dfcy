from django.test import SimpleTestCase
from apps.influencers.tiktok_product_sync import _project, DatasetError


class TikTokProductProjectionTests(SimpleTestCase):
    def test_nullable_metrics_stay_unknown_and_channel_metrics_are_whitelisted(self):
        product_id, metrics = _project({
            'id': '123', 'total_performance': {
                'product_impressions': 12, 'product_clicks': None, 'ctr': '0.25',
                'estimated_customers': None, 'unexpected': {'raw': 'discard'},
            },
            'seller_product_card_performance': {
                'product_impressions': 9, 'ctr': '0.5', 'token': 'discard',
            },
        })
        self.assertEqual(product_id, '123')
        self.assertIsNone(metrics['product_clicks'])
        self.assertIsNone(metrics['estimated_customers'])
        self.assertEqual(metrics['seller_product_card_performance']['product_impressions'], 9)
        self.assertNotIn('unexpected', metrics)
        self.assertFalse(any('token' in key for key in metrics))

    def test_invalid_product_identifiers_and_rates_are_rejected(self):
        with self.assertRaises(DatasetError):
            _project({'id': '0', 'total_performance': {}})
        with self.assertRaises(DatasetError):
            _project({'id': '12', 'total_performance': {'ctr': '-1'}})
