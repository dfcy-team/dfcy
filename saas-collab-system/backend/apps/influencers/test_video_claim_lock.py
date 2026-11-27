from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import Mock, patch

from django.db import DatabaseError
from django.utils import timezone

from . import tiktok_video_sync as video


class VideoClaimTests(TestCase):
    def setUp(self):
        def mock(target, attribute, **kwargs):
            p = patch.object(target, attribute, **kwargs)
            self.addCleanup(p.stop)
            return p.start()

        mock(video, "resolve", return_value=NS(store=NS(timezone="UTC")))
        mock(video, "fingerprint", return_value="verified")
        mock(video.transaction, "atomic", side_effect=nullcontext)
        mock(video.Tenant.objects, "select_for_update", side_effect=AssertionError("tenant lock"))
        self.claim = mock(video.TikTokVideoSyncBatch.objects, "select_for_update").return_value.get_or_create
        self.api = Mock(side_effect=AssertionError("unexpected API call"))
        self.day = timezone.now().date() - timedelta(days=1)

    def run_claim(self):
        return video.run_day(NS(tenant_id=3), 7, self.day, apply=True, client_factory=self.api)

    def test_completed_batch_is_not_fetched_again(self):
        self.claim.return_value = (NS(status="completed", pk=17), False)
        self.assertEqual(self.run_claim()["status"], "already_completed")
        args = self.claim.call_args.kwargs
        self.assertEqual((args["tenant_id"], args["store_id"], args["window_start"],
                          args["window_end"], args["api_version"]),
                         (3, 7, self.day, self.day + timedelta(days=1), video.VERSION))

    def test_active_lease_cannot_be_taken_over(self):
        self.claim.return_value = (NS(status="running", lease_expires_at=timezone.now() + timedelta(minutes=1)), False)
        with self.assertRaisesRegex(video.DatasetError, "video_batch_busy"):
            self.run_claim()

    def test_contention_returns_to_scheduler_without_nested_retry(self):
        for code in (1205, 1213):
            with self.subTest(code=code):
                self.claim.reset_mock()
                self.claim.side_effect = DatabaseError(code, "synthetic lock contention")
                with self.assertRaises(DatabaseError):
                    self.run_claim()
                self.claim.assert_called_once()
