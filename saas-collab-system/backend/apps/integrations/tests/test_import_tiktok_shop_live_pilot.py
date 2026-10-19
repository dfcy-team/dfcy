import json
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.integrations.management.commands.import_tiktok_shop_live_pilot import _complete_ph_range, _expiry
from apps.integrations.live_providers import TikTokLiveOAuthProvider
from apps.integrations.oauth_errors import OAuthFlowError
from zoneinfo import ZoneInfo
from datetime import datetime


class TikTokPilotSelectionTests(SimpleTestCase):
    def _provider(self, shops):
        provider = TikTokLiveOAuthProvider(
            {"contract_approved": True, "app_id": "app", "api_host": "https://example.invalid",
             "authorized_shops_path": "/shops"}, custody=Mock(), http_client=Mock(),
        )
        provider._signed_open_query = Mock(return_value={})
        provider._request_json = Mock(return_value={"code": 0, "data": {"shops": shops}})
        return provider

    @patch("apps.integrations.live_providers.require_live_mode")
    def test_pilot_selects_one_of_three_but_oauth_stays_single_shop(self, live_mode):
        shops = [
            {"id": "shop-1", "region": "PH", "cipher": "cipher-one"},
            {"id": "shop-th", "region": "TH", "cipher": "cipher-th"},
            {"id": "shop-my", "region": "MY", "cipher": "cipher-my"},
        ]
        provider = self._provider(shops[:1])
        self.assertEqual(provider._authorized_shops("token")["platform_store_id"], "shop-1")
        provider = self._provider(shops)
        self.assertEqual(provider.select_imported_pilot_shop(
            "token", platform_store_id="shop-1", region="PH", expected_cipher="cipher-one",
        )["platform_store_id"], "shop-1")
        with self.assertRaises(OAuthFlowError):
            provider._authorized_shops("token")
        with self.assertRaises(OAuthFlowError):
            provider.select_imported_pilot_shop(
                "token", platform_store_id="shop-1", region="PH", expected_cipher="wrong",
            )
        with self.assertRaises(OAuthFlowError):
            provider.select_imported_pilot_shop(
                "token", platform_store_id="shop-1", region="TH", expected_cipher="cipher-one",
            )
        provider = self._provider(shops + [shops[0]])
        with self.assertRaises(OAuthFlowError):
            provider.select_imported_pilot_shop(
                "token", platform_store_id="shop-1", region="PH", expected_cipher="cipher-one",
            )
from apps.integrations.models import ConnectionCapability, PlatformIntegrationConfig, MarketplaceStoreAuthorization, SyncJob, SyncRun, authorization_service_write
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


class TikTokShopLivePilotCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=1, code="tenant-1", name="YXJ")
        self.actor = CustomUser.objects.create_user(
            username="yxj", tenant=self.tenant, user_type="internal", is_staff=True,
            is_superuser=True,
        )
        platform = PlatformMaster.objects.create(
            tenant=self.tenant, code="tiktok", name="TikTok", platform_type="tiktok",
        )
        for code, shop_id in (("TK1PH", "shop-1"), ("TKKJ1PH", "shop-2")):
            StoreMaster.objects.create(
                tenant=self.tenant, platform=platform, code=code, name=code,
                external_store_id="", country_code="PH", currency="PHP",
            )

    def invoke(self, **kwargs):
        options = {"actor": self.actor.username, "tenant_id": 1, "tk1ph_id": "shop-1",
                   "tkkj1ph_id": "shop-2", "stdout": StringIO()}
        options.update(kwargs)
        return call_command("import_tiktok_shop_live_pilot", **options)

    @patch("apps.integrations.management.commands.import_tiktok_shop_live_pilot.get_custody_backend")
    @patch("apps.integrations.management.commands.import_tiktok_shop_live_pilot.require_live_mode")
    def test_dry_run_does_not_read_stdin_or_touch_custody_or_network(self, live_mode, custody):
        with patch("apps.integrations.management.commands.import_tiktok_shop_live_pilot.sys.stdin") as stdin:
            self.invoke()
            stdin.read.assert_not_called()
        live_mode.assert_not_called()
        custody.assert_not_called()
        self.assertFalse(PlatformIntegrationConfig.objects.exists())

    def test_nonblank_conflicting_store_id_is_rejected(self):
        store = StoreMaster.objects.get(code="TK1PH")
        store.external_store_id = "other-shop"
        store.save(update_fields=["external_store_id"])
        with self.assertRaisesMessage(CommandError, "conflicts"):
            call_command(
                "import_tiktok_shop_live_pilot", tenant_id=1, actor=self.actor.username,
                tk1ph_id="wrong", tkkj1ph_id="shop-2", stdout=StringIO(),
            )

    def test_wrong_tenant_is_rejected(self):
        with self.assertRaisesMessage(CommandError, "restricted to tenant id 1"):
            self.invoke(tenant_id=2)

    def test_other_staff_actor_is_rejected(self):
        CustomUser.objects.create_user(
            username="other-staff", tenant=self.tenant, user_type="internal", is_staff=True,
        )
        with self.assertRaisesMessage(CommandError, "requires actor yxj"):
            self.invoke(actor="other-staff")

    def test_existing_config_blocks_even_dry_run(self):
        PlatformIntegrationConfig.objects.create(
            tenant=self.tenant, platform="tiktok", account_alias="live-pilot-tk1ph",
            environment="pilot", created_by=self.actor,
        )
        with self.assertRaisesMessage(CommandError, "already exists"):
            self.invoke()

    @patch("apps.integrations.management.commands.import_tiktok_shop_live_pilot.get_custody_backend")
    @patch("apps.integrations.management.commands.import_tiktok_shop_live_pilot.require_live_mode", side_effect=CommandError("live blocked"))
    def test_apply_fails_before_reading_secrets_when_live_gate_closed(self, live_mode, custody):
        with patch("apps.integrations.management.commands.import_tiktok_shop_live_pilot.sys.stdin") as stdin:
            stdin.isatty.return_value = False
            with self.assertRaisesMessage(CommandError, "live blocked"):
                self.invoke(apply=True, tk1ph_business_model="local", tkkj1ph_business_model="cross_border")
            stdin.read.assert_not_called()
        custody.assert_not_called()
        self.assertFalse(PlatformIntegrationConfig.objects.exists())

    def test_expiry_only_needs_to_be_in_future(self):
        self.assertGreater(_expiry((timezone.now() + timedelta(days=6)).isoformat()), timezone.now())
        with self.assertRaises(CommandError):
            _expiry("2026-10-01T12:00:00")

    def _apply_with_verification(self, *, second_shop_id="shop-2", second_cipher="cipher-two", include_subject=True, duplicate_id=False):
        from apps.integrations.management.commands import import_tiktok_shop_live_pilot as module

        payload = {
            "app_secret": "not-printed-secret",
            "shops": {
                code: {
                    "access_token": f"access-{code}", "refresh_token": f"refresh-{code}",
                    "expires_at": (timezone.now() + timedelta(days=6)).isoformat(),
                    "merchant_subject_id": f"verified-open-id-{code}",
                    "expected_cipher": "cipher-one" if code == "TK1PH" else second_cipher,
                } for code in ("TK1PH", "TKKJ1PH")
            },
        }
        if not include_subject:
            del payload["shops"]["TK1PH"]["merchant_subject_id"]
        custody = object.__new__(module.HttpCustodyBackend)
        custody.store_secrets = Mock(side_effect=[
            {"credential_id": f"cred-shop-{index}", "token_id": f"tok-shop-{index}"}
            for index in (1, 2)
        ])
        custody.revoke = Mock(return_value={"status": "revoked"})
        provider = Mock()
        provider.select_imported_pilot_shop.side_effect = [
            {"platform_store_id": "shop-1", "region": "PH", "shop_cipher": "cipher-one"},
            (OAuthFlowError("OAUTH_CALLBACK_REJECTED", "Duplicate pilot shop identity.") if duplicate_id else
             {"platform_store_id": second_shop_id, "region": "PH", "shop_cipher": "cipher-two"}),
        ]

        def rotate(config, **kwargs):
            with authorization_service_write():
                config.credential_id = f"cred-app-{config.pk}"
                config.token_id = f"tok-app-{config.pk}"
                config.save(update_fields=["credential_id", "token_id"])
            return config, False

        with patch.object(module, "require_live_mode"), patch.object(module, "approved_custody_configured", return_value=True), \
             patch.object(module, "get_custody_backend", return_value=custody), \
             patch.object(module, "get_runtime_platform_config", return_value={
                 "contract_approved": True, "product_contract_approved": True,
                 "app_id": "app-key", "api_host": "https://example.invalid",
                 "redirect_uri": "",
             }), patch.object(module, "rotate_config_secrets", side_effect=rotate), \
             patch.object(module, "build_live_provider", return_value=provider), \
             patch.object(module.sys, "stdin", StringIO(json.dumps(payload))), \
             patch("apps.integrations.net_guard.PlatformHttpClient.request", side_effect=AssertionError("network forbidden")):
            self.invoke(apply=True, tk1ph_business_model="local", tkkj1ph_business_model="cross_border")
        return custody, provider

    def test_verified_binding_only_after_both_shops_match(self):
        custody, provider = self._apply_with_verification()
        self.assertEqual(StoreMaster.objects.get(code="TK1PH").external_store_id, "shop-1")
        self.assertEqual(StoreMaster.objects.get(code="TKKJ1PH").business_model, "cross_border")
        self.assertEqual(MarketplaceStoreAuthorization.objects.count(), 2)
        self.assertEqual(SyncJob.objects.count(), 4)
        self.assertEqual(ConnectionCapability.objects.count(), 4)
        self.assertFalse(ConnectionCapability.objects.filter(write_enabled=True).exists())
        self.assertFalse(ConnectionCapability.objects.exclude(read_enabled=True, status="active").exists())
        self.assertFalse(SyncJob.objects.filter(is_enabled=True).exists())
        self.assertFalse(SyncJob.objects.exclude(status="disabled").exists())
        self.assertFalse(PlatformIntegrationConfig.objects.exclude(status="verified", sync_read_enabled=True).exists())
        self.assertFalse(MarketplaceStoreAuthorization.objects.exclude(status="active").exists())
        self.assertFalse(PlatformIntegrationConfig.objects.exclude(callback_url="").exists())
        self.assertEqual(provider.select_imported_pilot_shop.call_count, 2)
        self.assertEqual(provider.select_imported_pilot_shop.call_args_list[1].kwargs["expected_cipher"], "cipher-two")
        start_at, end_at = _complete_ph_range()
        for job in SyncJob.objects.all():
            self.assertEqual(job.sync_scope["query"], {"mode": "range", "start_at": start_at, "end_at": end_at})
        self.assertEqual((datetime.fromisoformat(end_at).date() - datetime.fromisoformat(start_at).date()).days, 6)
        self.assertEqual(datetime.fromisoformat(end_at).date(), timezone.now().astimezone(ZoneInfo("Asia/Manila")).date() - timedelta(days=1))
        out = StringIO()
        with patch("apps.integrations.management.commands.run_tiktok_shop_live_pilot.SHOP_IDS",
                   {"TK1PH": "shop-1", "TKKJ1PH": "shop-2"}):
            call_command(
                "run_tiktok_shop_live_pilot", tenant_id=1, actor="yxj", shop="TK1PH",
                resource="sales_order", stdout=out,
            )
        self.assertIn("DRY RUN", out.getvalue())
        self.assertFalse(SyncJob.objects.filter(is_enabled=True).exists())

    def test_second_shop_mismatch_rolls_back_both_bindings(self):
        with self.assertRaisesMessage(CommandError, "token_verification"):
            self._apply_with_verification(second_shop_id="wrong-shop")
        self.assertFalse(StoreMaster.objects.exclude(external_store_id="").exists())
        self.assertFalse(PlatformIntegrationConfig.objects.exists())
        self.assertFalse(MarketplaceStoreAuthorization.objects.exists())
        self.assertFalse(SyncJob.objects.exists())

    def test_failed_shop_run_can_retry_with_next_attempt(self):
        self._apply_with_verification()
        keys = []

        def run_once(job, *, idempotency_key):
            self.assertTrue(SyncJob.objects.get(pk=job.pk).is_enabled)
            keys.append(idempotency_key)
            status = SyncRun.Status.FAILED if len(keys) == 1 else SyncRun.Status.SUCCESS
            run = SyncRun.objects.create(
                tenant_id=1, sync_job=job, run_id=f"run-{len(keys)}",
                idempotency_key=idempotency_key, status=status,
            )
            return run, True

        with patch("apps.integrations.management.commands.run_tiktok_shop_live_pilot.SHOP_IDS",
                   {"TK1PH": "shop-1", "TKKJ1PH": "shop-2"}), \
             patch("apps.integrations.management.commands.run_tiktok_shop_live_pilot.validate_manual_sync_job"), \
             patch("apps.integrations.management.commands.run_tiktok_shop_live_pilot.run_sync_job",
                   side_effect=run_once):
            kwargs = {"tenant_id": 1, "actor": "yxj", "shop": "TK1PH", "resource": "sales_order"}
            with self.assertRaisesMessage(CommandError, "ended with status failed"):
                call_command("run_tiktok_shop_live_pilot", apply=True, stdout=StringIO(), **kwargs)
            self.assertFalse(SyncJob.objects.filter(is_enabled=True).exists())
            with self.assertRaisesMessage(CommandError, "preceding attempt"):
                call_command("run_tiktok_shop_live_pilot", apply=True, attempt=3,
                             stdout=StringIO(), **kwargs)
            call_command("run_tiktok_shop_live_pilot", apply=True, attempt=2,
                         stdout=StringIO(), **kwargs)
        self.assertEqual(len(keys), 2)
        self.assertTrue(keys[0].endswith("attempt-1"))
        self.assertTrue(keys[1].endswith("attempt-2"))
        self.assertFalse(SyncJob.objects.filter(is_enabled=True).exists())

    def test_second_cipher_mismatch_rolls_back_before_db_binding(self):
        with self.assertRaisesMessage(CommandError, "token_verification"):
            self._apply_with_verification(second_cipher="wrong")
        self.assertFalse(PlatformIntegrationConfig.objects.exists())
        self.assertFalse(MarketplaceStoreAuthorization.objects.exists())

    def test_duplicate_shop_id_discovery_rolls_back(self):
        with self.assertRaisesMessage(CommandError, "token_verification"):
            self._apply_with_verification(duplicate_id=True)
        self.assertFalse(PlatformIntegrationConfig.objects.exists())
        self.assertFalse(MarketplaceStoreAuthorization.objects.exists())
        self.assertFalse(SyncJob.objects.exists())

    def test_missing_open_id_blocks_before_custody_write(self):
        with self.assertRaisesMessage(CommandError, "independently verified open_id"):
            self._apply_with_verification(include_subject=False)
        self.assertFalse(PlatformIntegrationConfig.objects.exists())
