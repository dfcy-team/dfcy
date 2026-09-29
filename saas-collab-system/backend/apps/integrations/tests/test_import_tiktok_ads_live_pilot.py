import json
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.integrations.custody import HttpCustodyBackend
from apps.integrations.models import PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, TikTokAdsSyncLease
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


MODULE = "apps.integrations.management.commands.import_tiktok_ads_live_pilot"


class AdsPilotImportTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=1, code="tenant-1", name="YXJ")
        self.actor = CustomUser.objects.create_user(
            username="yxj", tenant=self.tenant, user_type="internal", is_staff=True,
            is_superuser=True,
        )
        platform = PlatformMaster.objects.create(
            tenant=self.tenant, code="tiktok", name="TikTok", platform_type="tiktok",
        )
        self.stores = {
            code: StoreMaster.objects.create(
                tenant=self.tenant, platform=platform, code=code, name=code,
                country_code="PH", currency="PHP", timezone="Asia/Manila",
            ) for code in ("TK1PH", "TKKJ1PH")
        }
        self.payload = {
            "app_secret": "TOP-SECRET-APP",
            "shops": {
                "TK1PH": {"access_token": "TOP-SECRET-ONE", "advertiser_ids": [str(i) for i in range(100, 102)]},
                "TKKJ1PH": {"access_token": "TOP-SECRET-TWO", "advertiser_ids": [str(i) for i in range(200, 210)]},
            },
        }

    def invoke(self, **kwargs):
        out, err = StringIO(), StringIO()
        options = {"tenant_id": 1, "actor": self.actor.username, "stdout": out, "stderr": err}
        options.update(kwargs)
        call_command("import_tiktok_ads_live_pilot", **options)
        return out.getvalue() + err.getvalue()

    def test_dry_run_never_reads_stdin_or_touches_services(self):
        with patch(f"{MODULE}.sys.stdin") as stdin, patch(f"{MODULE}.get_custody_backend") as custody, patch(f"{MODULE}.PlatformHttpClient") as http:
            assert "DRY RUN" in self.invoke()
            stdin.read.assert_not_called()
            custody.assert_not_called()
            http.assert_not_called()
        self.assertFalse(PlatformIntegrationConfig.objects.exists())

    def test_tenant_and_actor_are_strict(self):
        with self.assertRaisesMessage(CommandError, "tenant id 1"):
            self.invoke(tenant_id=2)
        with self.assertRaisesMessage(CommandError, "actor yxj"):
            self.invoke(actor="other-staff")
        self.actor.is_staff = False
        self.actor.save(update_fields=["is_staff"])
        with self.assertRaisesMessage(CommandError, "unavailable"):
            self.invoke()

    def test_rejects_wrong_advertiser_distribution(self):
        self.payload["shops"]["TK1PH"]["advertiser_ids"].append("102")
        with patch(f"{MODULE}.sys.stdin", StringIO(json.dumps(self.payload))), \
             patch(f"{MODULE}.require_live_mode"), \
             patch(f"{MODULE}.approved_custody_configured", return_value=True), \
             patch(f"{MODULE}.get_custody_backend", return_value=Mock(spec=HttpCustodyBackend)), \
             patch(f"{MODULE}.get_runtime_platform_config", return_value={"contract_approved": True, "app_id": "app-id"}):
            with self.assertRaisesMessage(CommandError, "TK1PH requires exactly 2"):
                self.invoke(apply=True)

    def test_rejects_non_tiktok_store(self):
        other = PlatformMaster.objects.create(
            tenant=self.tenant, code="shopee", name="Shopee", platform_type="shopee",
        )
        store = self.stores["TK1PH"]
        store.platform = other
        store.save(update_fields=["platform"])
        with self.assertRaisesMessage(CommandError, "not a complete TikTok store"):
            self.invoke()

    def _apply(self, custody, http):
        stdin = StringIO(json.dumps(self.payload))
        stdin.isatty = lambda: False
        with patch(f"{MODULE}.sys.stdin", stdin), patch(f"{MODULE}.require_live_mode"), \
             patch(f"{MODULE}.approved_custody_configured", return_value=True), \
             patch(f"{MODULE}.get_custody_backend", return_value=custody), \
             patch(f"{MODULE}.get_runtime_platform_config", return_value={"contract_approved": True, "app_id": "app-id"}), \
             patch(f"{MODULE}.PlatformHttpClient", return_value=http):
            return self.invoke(apply=True)

    def _services(self, *, bad_info=False, bad_auth=False, overlap=False):
        custody = object.__new__(HttpCustodyBackend)
        custody.store_secrets = Mock(side_effect=[
            {"credential_id": f"cred_{i:032x}", "token_id": f"tok_{i:032x}"} for i in (1, 2)
        ])
        custody.revoke = Mock(return_value={"status": "revoked"})

        def request(method, url, **kwargs):
            assert method == "GET" and kwargs["retry"] is False
            token = kwargs["headers"]["Access-Token"]
            code = "TK1PH" if token == "TOP-SECRET-ONE" else "TKKJ1PH"
            ids = self.payload["shops"][code]["advertiser_ids"]
            path = urlparse(url).path
            if path.endswith("/oauth2/advertiser/get/"):
                assert parse_qs(urlparse(url).query)["app_id"] == ["app-id"]
                listed = ids[:-1] if bad_auth else ids
                if overlap and code == "TKKJ1PH":
                    listed = listed + ["100"]
                data = {"list": [{"advertiser_id": i} for i in listed]}
            else:
                assert path.endswith("/advertiser/info/")
                assert set(json.loads(parse_qs(urlparse(url).query)["advertiser_ids"][0])) == set(ids)
                data = {"list": [{"advertiser_id": i, "currency": "USD" if bad_info else "PHP",
                                  "timezone": "Asia/Manila"} for i in ids]}
            return Mock(json=Mock(return_value={"code": 0, "data": data}))

        http = Mock(request=Mock(side_effect=request))
        return custody, http

    def test_apply_creates_only_distinct_ads_configs_and_disabled_mappings(self):
        shop_config = PlatformIntegrationConfig.objects.create(
            tenant=self.tenant, platform="tiktok", account_alias="live-pilot-tk1ph",
            environment="pilot", created_by=self.actor, platform_config={"api_type": "marketplace"},
        )
        custody, http = self._services()
        output = self._apply(custody, http)
        self.assertEqual(PlatformIntegrationConfig.objects.count(), 3)
        self.assertEqual(TikTokAdsAdvertiserMapping.objects.count(), 12)
        self.assertEqual(TikTokAdsAdvertiserMapping.objects.filter(enabled=False).count(), 12)
        self.assertEqual(set(PlatformIntegrationConfig.objects.exclude(pk=shop_config.pk).values_list("platform_config__api_type", flat=True)), {"advertising"})
        self.assertEqual(set(TikTokAdsAdvertiserMapping.objects.values_list("integration_config_id", flat=True)),
                         set(PlatformIntegrationConfig.objects.exclude(pk=shop_config.pk).values_list("id", flat=True)))
        self.assertEqual(custody.store_secrets.call_count, 2)
        self.assertEqual(http.request.call_count, 4)
        self.assertNotIn("TOP-SECRET", output)
        self.assertNotIn("100", output)
        run_output = StringIO()
        call_command("run_tiktok_ads_live_pilot", tenant_id=1, actor="yxj", stdout=run_output)
        self.assertIn("DRY RUN", run_output.getvalue())
        self.assertFalse(TikTokAdsAdvertiserMapping.objects.filter(enabled=True).exists())

        def sync_once(**kwargs):
            self.assertEqual(TikTokAdsAdvertiserMapping.objects.filter(enabled=True).count(), 12)
            self.assertEqual(PlatformIntegrationConfig.objects.filter(
                platform_config__api_type="advertising", sync_read_enabled=True,
            ).count(), 2)
            return [{"days_written": 0, "missing_days": []} for _ in range(12)]

        with patch("apps.integrations.management.commands.run_tiktok_ads_live_pilot.sync_seven_complete_days",
                   side_effect=sync_once):
            call_command("run_tiktok_ads_live_pilot", tenant_id=1, actor="yxj", apply=True, stdout=StringIO())
        self.assertFalse(TikTokAdsAdvertiserMapping.objects.filter(enabled=True).exists())
        self.assertFalse(PlatformIntegrationConfig.objects.filter(
            platform_config__api_type="advertising", sync_read_enabled=True,
        ).exists())
        with patch(f"{MODULE}.sys.stdin") as stdin:
            with self.assertRaisesMessage(CommandError, "already exist"):
                self.invoke(apply=True)
            stdin.read.assert_not_called()

    def test_overlap_and_duplicate_ids_are_rejected_before_network(self):
        for duplicate in (False, True):
            payload = json.loads(json.dumps(self.payload))
            if duplicate:
                payload["shops"]["TK1PH"]["advertiser_ids"][1] = "100"
            else:
                payload["shops"]["TKKJ1PH"]["advertiser_ids"][0] = "100"
            self.payload = payload
            custody, http = self._services()
            with self.assertRaises(CommandError):
                self._apply(custody, http)
            custody.store_secrets.assert_not_called()
            http.request.assert_not_called()
            self.payload = {
                "app_secret": "TOP-SECRET-APP",
                "shops": {"TK1PH": {"access_token": "TOP-SECRET-ONE", "advertiser_ids": [str(i) for i in range(100, 102)]},
                          "TKKJ1PH": {"access_token": "TOP-SECRET-TWO", "advertiser_ids": [str(i) for i in range(200, 210)]}},
            }

    def test_stale_ads_activation_can_recover_but_active_lease_cannot(self):
        custody, http = self._services()
        self._apply(custody, http)
        TikTokAdsAdvertiserMapping.objects.filter(tenant_id=1).update(enabled=True)
        PlatformIntegrationConfig.objects.filter(
            tenant_id=1, platform_config__api_type="advertising",
        ).update(sync_read_enabled=True)
        lease = TikTokAdsSyncLease.objects.create(
            tenant_id=1, owner_token="active-owner", generation=1,
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )
        with self.assertRaisesMessage(CommandError, "active Ads sync lease"):
            call_command("run_tiktok_ads_live_pilot", tenant_id=1, actor="yxj",
                         recover_stale=True, apply=True, stdout=StringIO())
        self.assertEqual(TikTokAdsAdvertiserMapping.objects.filter(enabled=True).count(), 12)
        lease.lease_expires_at = timezone.now() - timedelta(seconds=1)
        lease.save(update_fields=["lease_expires_at"])
        out = StringIO()
        call_command("run_tiktok_ads_live_pilot", tenant_id=1, actor="yxj",
                     recover_stale=True, apply=True, stdout=out)
        self.assertIn("RECOVERED", out.getvalue())
        lease.refresh_from_db()
        self.assertEqual(lease.generation, 2)
        self.assertEqual(lease.owner_token, "")
        self.assertFalse(TikTokAdsAdvertiserMapping.objects.filter(enabled=True).exists())
        self.assertFalse(PlatformIntegrationConfig.objects.filter(
            platform_config__api_type="advertising", sync_read_enabled=True,
        ).exists())

    def test_stale_recovery_closes_half_open_switches(self):
        custody, http = self._services()
        self._apply(custody, http)
        PlatformIntegrationConfig.objects.filter(
            tenant_id=1, platform_config__api_type="advertising",
        ).update(sync_read_enabled=True)
        TikTokAdsSyncLease.objects.create(
            tenant_id=1, owner_token="interrupted-owner", generation=1,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )
        call_command("run_tiktok_ads_live_pilot", tenant_id=1, actor="yxj",
                     recover_stale=True, apply=True, stdout=StringIO())
        self.assertFalse(TikTokAdsAdvertiserMapping.objects.filter(enabled=True).exists())
        self.assertFalse(PlatformIntegrationConfig.objects.filter(
            platform_config__api_type="advertising", sync_read_enabled=True,
        ).exists())
        call_command("run_tiktok_ads_live_pilot", tenant_id=1, actor="yxj", stdout=StringIO())

    def test_old_run_cannot_close_new_lease_owner_switches(self):
        custody, http = self._services()
        self._apply(custody, http)

        def overtaken(**kwargs):
            lease = TikTokAdsSyncLease.objects.create(
                tenant_id=1, owner_token="old-owner", generation=1,
                lease_expires_at=timezone.now() + timedelta(minutes=5),
            )
            kwargs["on_lease_claim"]("old-owner", 1)
            lease.owner_token = "new-owner"
            lease.generation = 2
            lease.save(update_fields=["owner_token", "generation"])
            return [{"days_written": 0, "missing_days": []} for _ in range(12)]

        with patch("apps.integrations.management.commands.run_tiktok_ads_live_pilot.sync_seven_complete_days",
                   side_effect=overtaken):
            call_command("run_tiktok_ads_live_pilot", tenant_id=1, actor="yxj",
                         apply=True, stdout=StringIO())
        self.assertEqual(TikTokAdsAdvertiserMapping.objects.filter(enabled=True).count(), 12)
        self.assertEqual(PlatformIntegrationConfig.objects.filter(
            platform_config__api_type="advertising", sync_read_enabled=True,
        ).count(), 2)

    def test_live_auth_or_metadata_mismatch_writes_nothing(self):
        for flags in ({"bad_auth": True}, {"bad_info": True}, {"overlap": True}):
            custody, http = self._services(**flags)
            with self.assertRaises(CommandError) as caught:
                self._apply(custody, http)
            self.assertNotIn("TOP-SECRET", str(caught.exception))
            self.assertFalse(PlatformIntegrationConfig.objects.exists())
            custody.store_secrets.assert_not_called()

    def test_preexisting_advertiser_in_other_store_blocks_before_network(self):
        platform = self.stores["TK1PH"].platform
        other_store = StoreMaster.objects.create(
            tenant=self.tenant, platform=platform, code="OTHER", name="Other",
            country_code="PH", currency="PHP", timezone="Asia/Manila",
        )
        config = PlatformIntegrationConfig.objects.create(
            tenant=self.tenant, platform="tiktok", account_alias="other-ads",
            environment="pilot", created_by=self.actor, platform_config={"api_type": "advertising"},
        )
        TikTokAdsAdvertiserMapping.objects.create(
            tenant=self.tenant, store=other_store, integration_config=config,
            advertiser_id="100", token_id=f"tok_{9:032x}", currency="PHP", timezone="Asia/Manila",
        )
        custody, http = self._services()
        with self.assertRaisesMessage(CommandError, "database rolled back"):
            self._apply(custody, http)
        custody.store_secrets.assert_not_called()
        http.request.assert_not_called()

    def test_second_custody_failure_revokes_first_and_rolls_back(self):
        custody, http = self._services()
        custody.store_secrets.side_effect = [
            {"credential_id": f"cred_{1:032x}", "token_id": f"tok_{1:032x}"},
            RuntimeError("TOP-SECRET-TWO"),
        ]
        with self.assertRaises(CommandError) as caught:
            self._apply(custody, http)
        self.assertNotIn("TOP-SECRET", str(caught.exception))
        custody.revoke.assert_called_once()
        self.assertFalse(PlatformIntegrationConfig.objects.exists())
        self.assertFalse(TikTokAdsAdvertiserMapping.objects.exists())
