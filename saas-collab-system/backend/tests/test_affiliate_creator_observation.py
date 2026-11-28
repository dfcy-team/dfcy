from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase

from apps.integrations.affiliate_sync import _can_replace_creator


class CreatorObservationTest(TestCase):
    def test_replacement_requires_bound_store_explicit_account_and_newer_evidence(self):
        t = datetime(2026, 1, 1, tzinfo=UTC)
        later = t + timedelta(seconds=1)
        current = SimpleNamespace(store_id=1, source_updated_at=t)
        cases = [
            (1, "new", later, later, True),
            (2, "new", later, later, False),
            (1, "", later, later, False),
            (1, "other", later, later, False),
            (1, "new", t, later, False),
            (1, "new", later, t, False),
            (1, "new", later, None, False),
        ]
        for store, account, observed, affiliate_observed, expected in cases:
            with self.subTest(store=store, account=account, observed=observed):
                values = {"store_id": store, "creator_username_normalized": "new"}
                self.assertEqual(
                    _can_replace_creator(current, values, account, observed, affiliate_observed),
                    expected,
                )
