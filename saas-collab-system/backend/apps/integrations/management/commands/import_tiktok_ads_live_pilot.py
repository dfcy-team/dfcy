"""Import two explicitly approved TikTok Ads authorizations without starting sync.

Apply stdin JSON: {"app_secret":"...","shops":{"TK1PH":{"access_token":"...",
"advertiser_ids":["...", ...]},"TKKJ1PH":{...}}}. Exactly 12 IDs total.
"""

import json
import re
import sys
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.integrations.capability import approved_custody_configured, require_live_mode
from apps.integrations.custody import HttpCustodyBackend, get_custody_backend
from apps.integrations.models import PlatformIntegrationConfig, TikTokAdsAdvertiserMapping
from apps.integrations.net_guard import PlatformHttpClient
from apps.integrations.production_settings import get_runtime_platform_config
from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant


CODES = ("TK1PH", "TKKJ1PH")
HOST = "https://business-api.tiktok.com"
GET_PATH = "/open_api/v1.3/oauth2/advertiser/get/"
INFO_PATH = "/open_api/v1.3/advertiser/info/"


def _data(http, path, params, token):
    response = http.request(
        "GET", f"{HOST}{path}?{urlencode(params)}", headers={"Access-Token": token},
        retry=False, diagnostic_platform="tiktok_ads",
    )
    try:
        body = response.json()
    except (ValueError, TypeError):
        raise CommandError("Ads verification returned invalid JSON.") from None
    if not isinstance(body, dict) or body.get("code") not in (0, "0") or not isinstance(body.get("data"), dict):
        raise CommandError("Ads verification failed.")
    return body["data"]


def _ids(value):
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not re.fullmatch(r"[0-9]+", item) for item in value
    ) or len(value) != len(set(value)):
        raise CommandError("Each shop needs distinct numeric advertiser IDs.")
    return set(value)


def _verify(http, app_id, app_secret, entry, store):
    token = entry["access_token"]
    requested = set(entry["advertiser_ids"])
    authorized = _data(http, GET_PATH, {"app_id": app_id, "secret": app_secret}, token).get("list")
    if not isinstance(authorized, list):
        raise CommandError("Ads authorization list is incomplete.")
    found = []
    for row in authorized:
        if not isinstance(row, dict) or not re.fullmatch(r"[0-9]+", str(row.get("advertiser_id", ""))):
            raise CommandError("Ads authorization list is malformed.")
        found.append(str(row["advertiser_id"]))
    if len(found) != len(set(found)) or not requested.issubset(found):
        raise CommandError("Supplied advertisers are not uniquely authorized by this token.")
    accounts = _data(http, INFO_PATH, {"advertiser_ids": json.dumps(sorted(requested))}, token).get("list")
    if not isinstance(accounts, list) or len(accounts) != len(requested):
        raise CommandError("Ads advertiser info is incomplete.")
    seen = set()
    for account in accounts:
        if not isinstance(account, dict):
            raise CommandError("Ads advertiser info is malformed.")
        advertiser_id = str(account.get("advertiser_id", ""))
        if advertiser_id not in requested or advertiser_id in seen:
            raise CommandError("Ads advertiser info does not match supplied IDs.")
        seen.add(advertiser_id)
        if account.get("currency") != store.currency or account.get("timezone") != store.timezone:
            raise CommandError("Ads advertiser currency or timezone does not match the store.")
    return set(found)


class Command(BaseCommand):
    help = "Dry-run preflight or import 12 disabled TikTok Ads advertiser mappings for the two yxj pilot shops."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if options["tenant_id"] != 1:
            raise CommandError("Ads pilot is restricted to tenant id 1.")
        if options["actor"] != "yxj":
            raise CommandError("Ads pilot requires actor yxj.")
        try:
            tenant = Tenant.objects.get(pk=1, status=Tenant.Status.ACTIVE)
            actor = get_user_model().objects.get(
                username="yxj", tenant=tenant, user_type="internal", is_active=True,
                is_staff=True, is_superuser=True,
            )
            stores = {code: StoreMaster.objects.select_related("platform").get(tenant=tenant, code=code) for code in CODES}
        except (Tenant.DoesNotExist, get_user_model().DoesNotExist, StoreMaster.DoesNotExist):
            raise CommandError("Pilot tenant, staff actor, or shops are unavailable.") from None
        for code, store in stores.items():
            if store.platform.platform_type != "tiktok" or not store.currency or not store.timezone:
                raise CommandError(f"{code} is not a complete TikTok store.")
        self._check_existing(tenant, stores)
        if not options["apply"]:
            self.stdout.write("DRY RUN: local Ads pilot preflight passed; no stdin, network, custody, or database writes. Live authorization remains unverified.")
            return
        if sys.stdin.isatty():
            raise CommandError("Apply requires JSON piped through stdin.")
        require_live_mode("TikTok Ads pilot import")
        if not approved_custody_configured():
            raise CommandError("Approved HTTP custody is required.")
        custody = get_custody_backend()
        if not isinstance(custody, HttpCustodyBackend):
            raise CommandError("Independent HTTP custody is required.")
        runtime = get_runtime_platform_config("tiktok")
        ads_app_id = str(getattr(settings, "LIVE_TIKTOK_ADS_APP_ID", "") or "").strip()
        if not runtime.get("contract_approved") or not re.fullmatch(r"[0-9]+", ads_app_id):
            raise CommandError("Approved TikTok Ads app ID and contract are required.")
        try:
            payload = json.load(sys.stdin)
        except (ValueError, UnicodeError):
            raise CommandError("Invalid stdin JSON.") from None
        if not isinstance(payload, dict) or set(payload) != {"app_secret", "shops"} or not isinstance(payload["shops"], dict) or set(payload["shops"]) != set(CODES) or not isinstance(payload["app_secret"], str) or not payload["app_secret"].strip():
            raise CommandError("Apply requires app_secret and exactly two named shop entries.")
        all_ids = set()
        for code in CODES:
            entry = payload["shops"][code]
            if not isinstance(entry, dict) or set(entry) != {"access_token", "advertiser_ids"} or not isinstance(entry["access_token"], str) or not entry["access_token"].strip():
                raise CommandError(f"{code} requires an access token and advertiser ID list.")
            ids = _ids(entry["advertiser_ids"])
            expected_count = 2 if code == "TK1PH" else 10
            if len(ids) != expected_count:
                raise CommandError(f"{code} requires exactly {expected_count} approved advertisers.")
            if all_ids.intersection(ids):
                raise CommandError("Advertiser IDs must not overlap between shops.")
            all_ids.update(ids)
        if len(all_ids) != 12:
            raise CommandError("Exactly 12 advertiser IDs are required across the two shops.")
        refs = []
        cleanup_failed = False
        try:
            with transaction.atomic():
                locked = {store.code: store for store in StoreMaster.objects.select_for_update().select_related("platform").filter(pk__in=[s.pk for s in stores.values()]).order_by("pk")}
                if set(locked) != set(CODES):
                    raise CommandError("Pilot stores changed during import.")
                if any(store.platform.platform_type != "tiktok" or not store.currency or not store.timezone for store in locked.values()):
                    raise CommandError("Pilot store metadata changed during import.")
                self._check_existing(tenant, locked)
                if TikTokAdsAdvertiserMapping.objects.filter(tenant=tenant, advertiser_id__in=all_ids).exists():
                    raise CommandError("A supplied advertiser is already mapped; refusing replacement.")
                http = PlatformHttpClient()
                authorized_by_shop = {}
                for code in CODES:
                    authorized_by_shop[code] = _verify(
                        http, ads_app_id, payload["app_secret"], payload["shops"][code], locked[code],
                    )
                if authorized_by_shop[CODES[0]].intersection(authorized_by_shop[CODES[1]]):
                    raise CommandError("The two Ads authorizations overlap across shops.")
                for code in CODES:
                    store = locked[code]
                    config = PlatformIntegrationConfig.objects.create(
                        tenant=tenant, platform="tiktok", account_alias=f"live-ads-pilot-{code.lower()}",
                        environment="pilot", status="verified", created_by=actor,
                        platform_config={"api_type": "advertising", "app_key": ads_app_id},
                        network_enabled=True, sync_read_enabled=False, sync_write_enabled=False,
                    )
                    stored = custody.store_secrets(
                        credential_type="tiktok_ads", reference_version=1,
                        access_token=payload["shops"][code]["access_token"],
                        metadata={"tenant_id": tenant.pk, "integration_config_id": config.pk, "platform": "tiktok_ads"},
                    )
                    if not isinstance(stored, dict) or not stored.get("credential_id") or not stored.get("token_id"):
                        raise CommandError("Custody returned incomplete references; manual reconciliation required.")
                    refs.append((stored["credential_id"], stored["token_id"]))
                    for advertiser_id in payload["shops"][code]["advertiser_ids"]:
                        TikTokAdsAdvertiserMapping.objects.create(
                            tenant=tenant, store=store, integration_config=config,
                            advertiser_id=advertiser_id, token_id=stored["token_id"],
                            currency=store.currency, timezone=store.timezone, enabled=False,
                        )
        except Exception as exc:
            for credential_id, token_id in reversed(refs):
                try:
                    cleanup_failed |= custody.revoke(credential_id, token_id).get("status") not in {"revoked", "not_required"}
                except Exception:
                    cleanup_failed = True
            detail = "Custody cleanup requires manual reconciliation." if cleanup_failed else "New custody references revoked."
            raise CommandError(f"Ads pilot import failed ({type(exc).__name__}); database rolled back. {detail}") from None
        finally:
            payload.clear()
        self.stdout.write("Imported two separate TikTok Ads pilot configs and 12 disabled advertiser mappings. No report sync started.")

    @staticmethod
    def _check_existing(tenant, stores):
        if TikTokAdsAdvertiserMapping.objects.filter(tenant=tenant, store_id__in=[s.pk for s in stores.values()]).exists():
            raise CommandError("Ads mappings already exist for a pilot shop; refusing replacement.")
        if PlatformIntegrationConfig.objects.filter(
            tenant=tenant, platform="tiktok", environment="pilot",
            account_alias__in=[f"live-ads-pilot-{code.lower()}" for code in CODES],
        ).exists():
            raise CommandError("Ads pilot config already exists; refusing replacement.")
