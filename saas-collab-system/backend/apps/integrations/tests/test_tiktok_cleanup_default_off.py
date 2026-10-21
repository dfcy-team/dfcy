from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.integrations.tasks import (
    cleanup_tiktok_ads_authorizations,
    cleanup_tiktok_shop_bindings,
    refresh_due_integration_credentials,
)


class TikTokCleanupDefaultOffTests(SimpleTestCase):
    def test_cleanup_is_opt_in_and_not_scheduled_by_default(self):
        self.assertFalse(settings.TIKTOK_OAUTH_CLEANUP_ENABLED)
        self.assertNotIn("cleanup-tiktok-shop-bindings", settings.CELERY_BEAT_SCHEDULE)
        self.assertNotIn("cleanup-tiktok-ads-authorizations", settings.CELERY_BEAT_SCHEDULE)

    @override_settings(TIKTOK_OAUTH_CLEANUP_ENABLED=False)
    def test_already_queued_cleanup_tasks_stop_before_service_calls(self):
        with (
            patch("apps.integrations.tiktok_shop_binding.cleanup_shop_bindings") as shop_cleanup,
            patch("apps.integrations.tiktok_shop_binding.cleanup_previous_shop_references") as prior_cleanup,
            patch("apps.integrations.tiktok_ads_oauth.cleanup_ads_authorizations") as ads_cleanup,
        ):
            self.assertEqual(cleanup_tiktok_shop_bindings(), {"status": "disabled"})
            self.assertEqual(cleanup_tiktok_ads_authorizations(), {"status": "disabled"})
        shop_cleanup.assert_not_called()
        prior_cleanup.assert_not_called()
        ads_cleanup.assert_not_called()

    @override_settings(TIKTOK_OAUTH_CLEANUP_ENABLED=True)
    def test_explicit_opt_in_preserves_cleanup_task_behavior(self):
        with (
            patch("apps.integrations.tiktok_shop_binding.cleanup_shop_bindings", return_value=2) as shop_cleanup,
            patch("apps.integrations.tiktok_shop_binding.cleanup_previous_shop_references", return_value=3) as prior_cleanup,
            patch("apps.integrations.tiktok_ads_oauth.cleanup_ads_authorizations", return_value={"cleaned": 4}) as ads_cleanup,
        ):
            self.assertEqual(cleanup_tiktok_shop_bindings(), {"staged": 2, "previous": 3})
            self.assertEqual(cleanup_tiktok_ads_authorizations(), {"cleaned": 4})
        shop_cleanup.assert_called_once_with(limit=50)
        prior_cleanup.assert_called_once_with(limit=50)
        ads_cleanup.assert_called_once_with(limit=50)

    def test_existing_credential_refresh_task_remains_unchanged(self):
        with patch("apps.integrations.automatic_refresh.refresh_due_authorizations", return_value={"refreshed": 1}) as refresh:
            self.assertEqual(refresh_due_integration_credentials(), {"refreshed": 1})
        refresh.assert_called_once_with()
