from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase

from .affiliate_sync import _can_replace_creator


class CreatorObservationTest(TestCase):
    def test_replacement_requires_bound_store_explicit_account_and_newer_evidence(self):
        t = datetime(2026, 1, 1, tzinfo=UTC)
        later = t + timedelta(seconds=1)
        current = SimpleNamespace(store_id=1, source_updated_at=t)
        for store, account, source, observed, expected in [
            (1, "new", later, later, True),
            (2, "new", later, later, False),
            (1, "", later, later, False),
            (1, "other", later, later, False),
            (1, "new", t, later, False),
            (1, "new", later, t, False),
            (1, "new", later, None, False),
        ]:
            with self.subTest(store=store, account=account, source=source, observed=observed):
                values = dict(store_id=store, creator_username_normalized="new", source_updated_at=source)
                self.assertEqual(_can_replace_creator(current, values, account, observed), expected)
