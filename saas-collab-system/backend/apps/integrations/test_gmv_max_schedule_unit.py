import unittest
from datetime import datetime, timezone
from apps.integrations.gmv_max_schedule import collect_days, complete_days


class ScheduleTests(unittest.TestCase):
    def test_seven_complete_local_days(self):
        now = datetime(2026, 11, 1, 18, tzinfo=timezone.utc)
        days = complete_days(now, 'Asia/Manila')
        self.assertEqual([days[0].isoformat(), days[-1].isoformat()],
                         ['2026-10-26', '2026-11-01'])
        self.assertEqual(len(set(days)), 7)
        self.assertEqual(complete_days(now, 'America/Los_Angeles')[-1].isoformat(), '2026-10-31')

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError):
            complete_days(datetime(2026, 11, 2), 'Asia/Manila')

    def test_error_is_not_zero_and_does_not_stop_other_days(self):
        days = complete_days(datetime(2026, 11, 2, tzinfo=timezone.utc), 'Asia/Manila')
        events = []
        def collect(day):
            if day == days[0]:
                raise ValueError('secret token must not be logged')
            return {'committed': True, 'created': False}
        self.assertEqual(collect_days(days, collect, events.append), {'success': 6, 'failed': 1})
        self.assertNotIn('secret', str(events))
        self.assertNotIn('result', events[0])

    def test_uncommitted_is_failure(self):
        days = complete_days(datetime(2026, 11, 2, tzinfo=timezone.utc), 'Asia/Manila')
        self.assertEqual(collect_days(days, lambda _: {'committed': False}, lambda _: None),
                         {'success': 0, 'failed': 7})
