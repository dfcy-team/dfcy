import hashlib
import hmac
import json
from unittest import TestCase

from apps.integrations.shopee_order_events import event_milestones, parse_status_event, verify_signature


class ShopeeEventContractTests(TestCase):
    def body(self, status='COMPLETED', scenario='NORMAL', time=1700000000, sent=1700000010):
        return json.dumps({'shop_id': 123, 'code': 3, 'timestamp': sent, 'data': {
            'ordersn': 'TEST-ORDER', 'status': status, 'completed_scenario': scenario,
            'update_time': time}}).encode()

    def test_signature_uses_exact_body_and_configured_url(self):
        url, key, body = 'https://example.com/push/', 'TEST-ONLY-KEY', self.body()
        signature = hmac.new(key.encode(), url.encode() + b'|' + body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(url, body, key, signature))
        self.assertFalse(verify_signature(url, body + b' ', key, signature))
        self.assertFalse(verify_signature(url + 'other', body, key, signature))
        self.assertFalse(verify_signature(url, body, key, ''))

    def test_retry_has_same_identity(self):
        a = parse_status_event(self.body())
        b = parse_status_event(self.body(sent=1700000099))
        self.assertEqual(a['event_key'], b['event_key'])
        self.assertNotEqual(a['body_hash'], b['body_hash'])

    def test_out_of_order_events_and_after_sale_completion(self):
        events = [parse_status_event(self.body('COMPLETED', 'RRAOC', 1700000400)),
                  parse_status_event(self.body('CANCELLED', '', 1700000300)),
                  parse_status_event(self.body('IN_CANCEL', '', 1700000200)),
                  parse_status_event(self.body(time=1700000100))]
        result = event_milestones(events)
        self.assertEqual(result['completed_at'].timestamp(), 1700000100)
        self.assertEqual(result['cancel_requested_at'].timestamp(), 1700000200)
        self.assertEqual(result['cancelled_at'].timestamp(), 1700000300)
        self.assertEqual(result, event_milestones(list(reversed(events))))

    def test_missing_history_is_not_inferred(self):
        self.assertTrue(all(v is None for v in event_milestones([]).values()))
        self.assertIsNone(event_milestones([parse_status_event(self.body(scenario=''))])['completed_at'])

    def test_invalid_event_times_and_payloads(self):
        for body in (b'[]', b'{}', b'null', self.body(time=True), self.body(time=0), self.body(time=-1), b' ' * 65537):
            with self.assertRaises(ValueError):
                parse_status_event(body)
