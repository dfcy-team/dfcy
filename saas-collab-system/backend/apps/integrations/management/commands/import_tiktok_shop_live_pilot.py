"""Import two explicitly identified TikTok shops without enabling synchronization.

Dry run: --tenant-id 1 --actor USER --tk1ph-id ID --tkkj1ph-id ID
Apply: add --apply and pipe a JSON object on stdin:
{"app_secret":"...","shops":{"TK1PH":{"access_token":"...","refresh_token":"...",
"expires_at":"ISO-8601","merchant_subject_id":"verified open_id",
"expected_cipher":"independently verified cipher"},"TKKJ1PH":{...}}}
The existing authorized-shops API returns shop ID/cipher/region, not open_id. The
operator must supply the independently verified open_id; it is never inferred.
This imports existing tokens only. No callback is registered, and future refresh
or re-authorization continuity is not established by successful import.
"""

import json
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant
from apps.integrations.capability import approved_custody_configured, require_live_mode
from apps.integrations.credential_service import rotate_config_secrets
from apps.integrations.custody import HttpCustodyBackend, get_custody_backend
from apps.integrations.live_providers import build_live_provider
from apps.integrations.models import (
    ConnectionCapability, MarketplaceStoreAuthorization, PlatformIntegrationConfig, SyncJob,
    marketplace_active_identity_key, marketplace_store_binding_key,
)
from apps.integrations.platform_schema_service import get_platform_schema
from apps.integrations.production_settings import get_runtime_platform_config
from apps.integrations.store_authorization_service import create_store_authorization, transition_store_authorization


CODES = ("TK1PH", "TKKJ1PH")
RESOURCES = (SyncJob.ResourceType.PLATFORM_PRODUCT, SyncJob.ResourceType.SALES_ORDER)


def _complete_ph_range():
    today = timezone.now().astimezone(ZoneInfo("Asia/Manila")).date()
    zone = ZoneInfo("Asia/Manila")
    return (datetime.combine(today - timedelta(days=7), time.min, zone).isoformat(),
            datetime.combine(today - timedelta(days=1), time(23, 59, 59), zone).isoformat())


def _expiry(value):
    parsed = parse_datetime(str(value or ""))
    if not parsed or timezone.is_naive(parsed) or parsed <= timezone.now():
        raise CommandError("Each token expiry must be timezone-aware and in the future.")
    return parsed


class Command(BaseCommand):
    help = "Preflight or safely import a two-store yxj TikTok Shop pilot; jobs remain disabled."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--tk1ph-id", required=True)
        parser.add_argument("--tkkj1ph-id", required=True)
        parser.add_argument("--tk1ph-business-model", choices=["local", "cross_border", "full_managed", "semi_managed"])
        parser.add_argument("--tkkj1ph-business-model", choices=["local", "cross_border", "full_managed", "semi_managed"])
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        ids = dict(zip(CODES, (options["tk1ph_id"], options["tkkj1ph_id"])))
        business_models = dict(zip(CODES, (options["tk1ph_business_model"], options["tkkj1ph_business_model"])))
        if any(not str(value).strip() or str(value) != str(value).strip() for value in ids.values()):
            raise CommandError("Both exact shop IDs are required.")
        if len(set(ids.values())) != 2:
            raise CommandError("The two shop IDs must differ.")
        try:
            if options["tenant_id"] != 1:
                raise CommandError("This VM34 pilot is restricted to tenant id 1.")
            if options["actor"] != "yxj":
                raise CommandError("This VM34 pilot requires actor yxj.")
            tenant = Tenant.objects.get(pk=options["tenant_id"], status=Tenant.Status.ACTIVE)
            actor = get_user_model().objects.get(
                username="yxj", tenant_id=tenant.pk, is_active=True, is_staff=True,
                is_superuser=True, user_type="internal",
            )
            stores = {
                code: StoreMaster.objects.select_related("platform").get(tenant=tenant, code=code)
                for code in CODES
            }
        except (Tenant.DoesNotExist, get_user_model().DoesNotExist, StoreMaster.DoesNotExist):
            raise CommandError("Pilot tenant, staff actor, or one of the two stores is unavailable.") from None
        for code, store in stores.items():
            if store.platform.platform_type != "tiktok" or not store.country_code:
                raise CommandError(f"{code} platform or region does not match TikTok pilot requirements.")
            if store.external_store_id and store.external_store_id != ids[code]:
                raise CommandError(f"{code} nonblank external shop ID conflicts with the requested ID.")
            if business_models[code] and store.business_model not in {StoreMaster.BusinessModel.OTHER, business_models[code]}:
                raise CommandError(f"{code} nonblank business model conflicts with the requested model.")
            alias = f"live-pilot-{code.lower()}"
            if PlatformIntegrationConfig.objects.filter(tenant=tenant, platform="tiktok", account_alias=alias, environment="pilot").exists():
                raise CommandError(f"{code} live pilot config already exists; refusing replacement.")
            if MarketplaceStoreAuthorization.objects.filter(
                active_store_binding_key=marketplace_store_binding_key(tenant.id, "tiktok", store.id)
            ).exists() or MarketplaceStoreAuthorization.objects.filter(
                active_platform_identity_key=marketplace_active_identity_key("tiktok", store.country_code, ids[code])
            ).exists():
                raise CommandError(f"{code} already has an active store or shop binding.")
            if SyncJob.objects.filter(tenant=tenant, store_authorization__store=store, resource_type__in=RESOURCES).exists():
                raise CommandError(f"{code} already has a matching sync job.")
        if not options["apply"]:
            self.stdout.write("DRY RUN: two yxj stores passed local checks; blank external IDs require live authorized-shop verification. No secrets read, writes, or network calls; platform identity and cipher remain unverified.")
            return
        if any(not business_models[code] for code in CODES):
            raise CommandError("Apply requires an explicit business model for each store.")
        if sys.stdin.isatty():
            raise CommandError("Apply requires JSON secrets piped through stdin, not an interactive prompt.")
        require_live_mode("TikTok two-store pilot import")
        if not approved_custody_configured():
            raise CommandError("Approved HTTP custody is required.")
        custody = get_custody_backend()
        if not isinstance(custody, HttpCustodyBackend):
            raise CommandError("Apply requires the independent HTTP custody backend.")
        runtime = get_runtime_platform_config("tiktok")
        if (not runtime.get("contract_approved") or not runtime.get("product_contract_approved")
                or not runtime.get("app_id") or not runtime.get("api_host")):
            raise CommandError("Approved TikTok order/product contracts, app key, and API host are required.")
        try:
            payload = json.load(sys.stdin)
        except (ValueError, UnicodeError):
            raise CommandError("Invalid stdin JSON.") from None
        if not isinstance(payload, dict) or set(payload) != {"app_secret", "shops"} or not isinstance(payload["shops"], dict) or set(payload["shops"]) != set(CODES):
            raise CommandError("Stdin must contain only app_secret and exactly the two named shops.")
        if not isinstance(payload["app_secret"], str) or not payload["app_secret"].strip():
            raise CommandError("App secret is required.")
        expiries = {}
        for code in CODES:
            entry = payload["shops"][code]
            if not isinstance(entry, dict) or set(entry) != {"access_token", "refresh_token", "expires_at", "merchant_subject_id", "expected_cipher"}:
                raise CommandError(f"{code} needs access/refresh tokens, expiry, expected_cipher, and independently verified open_id as merchant_subject_id; authorized-shops does not return open_id.")
            if any(not isinstance(entry[key], str) or not entry[key].strip() for key in ("access_token", "refresh_token", "merchant_subject_id", "expected_cipher")):
                raise CommandError(f"{code} token, expected cipher, or merchant subject is missing.")
            expiries[code] = _expiry(entry["expires_at"])
        created_refs = []
        phase = "config"
        try:
            with transaction.atomic():
                # Lock both StoreMaster rows before any external mutation; recheck bindings under the lock.
                locked_stores = {
                    store.code: store for store in StoreMaster.objects.select_for_update().select_related("platform")
                    .filter(pk__in=[store.pk for store in stores.values()]).order_by("pk")
                }
                for code, store in locked_stores.items():
                    if store.platform.platform_type != "tiktok" or store.external_store_id not in {"", ids[code]} or not store.country_code:
                        raise CommandError(f"{code} store identity changed during import.")
                    if store.business_model not in {StoreMaster.BusinessModel.OTHER, business_models[code]}:
                        raise CommandError(f"{code} business model changed during import.")
                    if MarketplaceStoreAuthorization.objects.filter(tenant=tenant, store=store, platform="tiktok").exclude(status="revoked").exists():
                        raise CommandError(f"{code} has an existing authorization.")
                configs = {}
                verified = {}
                phase = "token_verification"
                for code in CODES:
                    config = PlatformIntegrationConfig.objects.create(
                        tenant=tenant, platform="tiktok", account_alias=f"live-pilot-{code.lower()}",
                        environment="pilot", status="draft", created_by=actor,
                        contract_version=get_platform_schema("tiktok", environment="pilot")["contract_versions"][0],
                        platform_config={"app_key": runtime["app_id"], "api_type": "marketplace"},
                        callback_url="", network_enabled=True,
                        sync_read_enabled=False, sync_write_enabled=False,
                    )
                    config, _ = rotate_config_secrets(
                        config, credentials={"app_secret": payload["app_secret"]}, version=1,
                        reason="two-store-live-pilot", actor=actor,
                        idempotency_key=f"tiktok-pilot-{tenant.id}-{code}-{config.pk}",
                    )
                    created_refs.append((config.credential_id, config.token_id))
                    config.sync_read_enabled = False
                    config.save(update_fields=["sync_read_enabled", "updated_at"])
                    configs[code] = config
                for code in CODES:
                    entry = payload["shops"][code]
                    stored = custody.store_secrets(
                        credential_type="tiktok", reference_version=1,
                        access_token=entry["access_token"], refresh_token=entry["refresh_token"],
                        expires_at=expiries[code].isoformat(),
                        metadata={"tenant_id": tenant.id, "integration_config_id": configs[code].pk, "platform": "tiktok"},
                    )
                    created_refs.append((stored["credential_id"], stored["token_id"]))
                    provider = build_live_provider(
                        "tiktok", app_id=runtime["app_id"], api_host=runtime["api_host"],
                        app_secret_reference=configs[code].credential_id, contract_approved=True,
                    )
                    shop = provider.select_imported_pilot_shop(
                        stored["token_id"], platform_store_id=ids[code],
                        region=locked_stores[code].country_code,
                        expected_cipher=entry["expected_cipher"],
                    )
                    if (shop["platform_store_id"] != ids[code]
                            or shop["region"] != locked_stores[code].country_code.upper()
                            or shop["shop_cipher"] != entry["expected_cipher"]):
                        raise CommandError(f"{code} platform-verified shop identity mismatch.")
                    verified[code] = (stored, shop)
                for code in CODES:
                    phase = f"store_binding_{code}"
                    store = locked_stores[code]
                    stored, shop = verified[code]
                    changed = []
                    if not store.external_store_id:
                        store.external_store_id = shop["platform_store_id"]
                        changed.append("external_store_id")
                    if store.business_model == StoreMaster.BusinessModel.OTHER:
                        store.business_model = business_models[code]
                        changed.append("business_model")
                    if changed:
                        store.full_clean()
                        store.save(update_fields=changed)
                    entry = payload["shops"][code]
                    phase = f"authorization_{code}"
                    auth = create_store_authorization(
                        tenant=tenant, integration_config=configs[code], store=store, platform="tiktok",
                        region=shop["region"], platform_store_id=shop["platform_store_id"],
                        merchant_subject_id=entry["merchant_subject_id"], shop_cipher=shop["shop_cipher"],
                        credential_id=stored["credential_id"], token_id=stored["token_id"],
                        credential_mask={"configured": "********"}, allow_live_references=True,
                        expires_at=expiries[code], scopes=[], actor=actor,
                    )
                    transition_store_authorization(
                        auth, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=actor,
                    )
                    auth.refresh_from_db()
                    configs[code].status = PlatformIntegrationConfig.Status.VERIFIED
                    configs[code].sync_read_enabled = True
                    configs[code].last_verified_at = timezone.now()
                    configs[code].save(update_fields=["status", "sync_read_enabled", "last_verified_at", "updated_at"])
                    for capability_code in (
                        ConnectionCapability.CapabilityCode.PRODUCT,
                        ConnectionCapability.CapabilityCode.ORDER,
                    ):
                        capability = ConnectionCapability(
                            authorization=auth, capability_code=capability_code,
                            read_enabled=True, write_enabled=False,
                            sync_mode=ConnectionCapability.SyncMode.MANUAL,
                            status=ConnectionCapability.Status.ACTIVE,
                        )
                        capability.full_clean()
                        capability.save()
                    start_at, end_at = _complete_ph_range()
                    for resource in RESOURCES:
                        phase = f"sync_job_{code}_{resource}"
                        job = SyncJob(
                            tenant=tenant, integration_config=configs[code], store_authorization=auth,
                            resource_type=resource, schedule_type="manual", status="disabled", is_enabled=False,
                            sync_scope={"execution_mode": "live_readonly", "product_full_sync": False,
                                        "query": {"mode": "range", "start_at": start_at, "end_at": end_at}},
                        )
                        job.full_clean()
                        job.save()
        except Exception as exc:
            failed = False
            for credential_id, token_id in reversed(created_refs):
                try:
                    failed |= custody.revoke(credential_id, token_id).get("status") not in {"revoked", "not_required"}
                except Exception:
                    failed = True
            detail = "Custody cleanup requires manual reconciliation." if failed else "New custody references revoked."
            fields = f" fields={','.join(sorted(exc.message_dict))}" if isinstance(exc, ValidationError) and hasattr(exc, "message_dict") else ""
            raise CommandError(f"Pilot import failed at {phase} ({type(exc).__name__}{fields}); DB rolled back. {detail}") from None
        finally:
            payload.clear()
        self.stdout.write("Imported two verified shops into separate read-enabled pilot configs; four manual sync jobs remain disabled. No jobs were run. OAuth callback/re-auth is not configured; refresh continuity is unverified.")
