from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from apps.integrations.feishu_delivery import dispatch_feishu, validate_rule_config


class OwnerScheduleTests(SimpleTestCase):
    def run_schedule(self, minute, created_hour=0, created_minute=0):
        # UTC 01:30 is Beijing 09:30. All persistence and transports are mocked.
        rule = SimpleNamespace(
            pk=1, tenant_id=1, kind='report',
            config={'report_type': 'tiktok_owner_daily', 'schedule': 'daily',
                    'hour': 9, 'minute': 30, 'format': 'card'},
            created_at=datetime(2026, 11, 5, created_hour, created_minute, tzinfo=timezone.utc),
        )
        with patch('apps.integrations.feishu_delivery.timezone.now', return_value=datetime(2026, 11, 5, 1, minute, tzinfo=timezone.utc)), \
             patch('apps.integrations.feishu_delivery.validate_rule_config'), \
             patch('apps.integrations.feishu_delivery.FeishuConfigRule.objects.filter') as rules, \
             patch('apps.integrations.feishu_delivery.FeishuDelivery.objects.filter') as deliveries, \
             patch('apps.integrations.feishu_delivery.enqueue_rule') as enqueue, \
             patch('apps.supply_chain.payment_reminder_delivery.enqueue_due_reminders'), \
             patch('apps.integrations.feishu_delivery.execute_delivery') as send:
            rules.return_value.select_related.return_value.iterator.return_value = [rule]
            deliveries.return_value.filter.return_value.order_by.return_value.values_list.return_value = []
            result = dispatch_feishu()
            send.assert_not_called()
            self.assertEqual(result['processed'], 0)
            return enqueue.call_args_list

    def test_half_hour_not_dispatched_before_selected_minute(self):
        self.assertEqual(self.run_schedule(29), [])

    def test_half_hour_dispatch_uses_daily_idempotency_key(self):
        calls = self.run_schedule(30)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs['key'], 'scheduled:2026-11-05')

    def test_created_after_selected_occurrence_waits_until_next_day(self):
        self.assertEqual(self.run_schedule(45, created_hour=1, created_minute=31), [])

    def test_created_before_selected_occurrence_is_eligible(self):
        self.assertEqual(len(self.run_schedule(30, created_hour=1, created_minute=29)), 1)

    def test_invalid_minutes_fail_before_dispatch(self):
        with patch('apps.integrations.feishu_delivery.CustomUser.objects.filter') as users:
            users.return_value.count.return_value = 0
            for minute in (-1, 60, True, '30'):
                with self.subTest(minute=minute), self.assertRaises(ValidationError):
                    validate_rule_config('report', {'recipient_user_ids': [], 'report_type': 'tiktok_owner_daily',
                        'schedule': 'daily', 'hour': 9, 'minute': minute, 'format': 'card'}, 1)
