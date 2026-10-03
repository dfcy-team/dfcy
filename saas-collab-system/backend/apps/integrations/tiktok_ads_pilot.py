"""Read-only TikTok Auction Campaign spend pilot; not all Ads spend."""

import json
import re
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant

from .capability import require_live_mode
from .custody import get_custody_backend
from .models import TikTokAdsAdvertiserMapping, TikTokAdsDailySpend, TikTokAdsSyncLease
from .net_guard import PlatformHttpClient


HOST = "https://business-api.tiktok.com"
REPORT_PATH = "/open_api/v1.3/report/integrated/get/"
INFO_PATH = "/open_api/v1.3/advertiser/info/"
REPORT_PAGE_SIZE = 1000
MAX_REPORT_PAGES = 100
PILOT_TENANT_ID = 1
PILOT_TENANT_CODE = "tenant-1"
PILOT_ACCOUNT_COUNTS = {"TK1PH": 2, "TKKJ1PH": 10}
LEASE_DURATION = timedelta(minutes=15)


def _get(http, path, params, token):
    response = http.request(
        "GET", f"{HOST}{path}?{urlencode(params)}",
        headers={"Access-Token": token}, retry=False,
        diagnostic_platform="tiktok_ads",
    )
    try:
        payload = response.json()
    except (ValueError, TypeError):
        raise ValidationError("TikTok Ads returned invalid JSON.") from None
    if not isinstance(payload, dict) or payload.get("code") not in (0, "0"):
        raise ValidationError("TikTok Ads rejected the read-only request.")
    if not isinstance(payload.get("data"), dict):
        raise ValidationError("TikTok Ads response has no data object.")
    return payload["data"]


def _validate_account(http, mapping, token):
    data = _get(http, INFO_PATH, {"advertiser_ids": json.dumps([mapping.advertiser_id])}, token)
    accounts = data.get("list")
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise ValidationError("TikTok Ads advertiser was not uniquely resolved.")
    account = accounts[0]
    if not isinstance(account, dict) or str(account.get("advertiser_id")) != mapping.advertiser_id:
        raise ValidationError("TikTok Ads advertiser identity mismatch.")
    if account.get("currency") != mapping.currency:
        raise ValidationError("TikTok Ads advertiser currency mismatch.")
    if account.get("timezone") and account["timezone"] != mapping.timezone:
        raise ValidationError("TikTok Ads advertiser timezone mismatch.")


def _parse_campaign_page(data, page, expected_pages):
    page_info = data.get("page_info")
    try:
        if not isinstance(page_info, dict) or isinstance(page_info.get("total_page"), bool):
            raise ValueError
        total_pages = int(page_info["total_page"])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("TikTok Ads report pagination is invalid.") from None
    if total_pages < 0 or total_pages > MAX_REPORT_PAGES or (expected_pages is not None and total_pages != expected_pages):
        raise ValidationError("TikTok Ads report pagination changed or exceeds the pilot limit.")
    rows = data.get("list", [] if total_pages == 0 else None)
    if not isinstance(rows, list) or (total_pages == 0 and (page != 1 or rows)) or (total_pages > 0 and not rows):
        raise ValidationError("TikTok Ads report page is incomplete.")
    parsed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("dimensions"), dict) or not isinstance(row.get("metrics"), dict):
            raise ValidationError("TikTok Ads report row is malformed.")
        campaign_id = str(row["dimensions"].get("campaign_id") or "")
        try:
            raw = row["metrics"]["spend"]
            if isinstance(raw, bool) or not re.fullmatch(r"\d+(?:\.\d{1,6})?", str(raw)):
                raise ValueError
            spend = Decimal(str(raw))
        except (ValueError, KeyError, InvalidOperation):
            raise ValidationError("TikTok Ads campaign spend is invalid.") from None
        if not re.fullmatch(r"[0-9]+", campaign_id) or campaign_id in parsed or not spend.is_finite():
            raise ValidationError("TikTok Ads campaign row is invalid or duplicated.")
        parsed[campaign_id] = spend
    return total_pages, parsed


def _campaign_spend_for_day(http, mapping, token, day):
    campaigns = set()
    total = Decimal("0")
    expected_pages = None
    page = 1
    while True:
        data = _get(http, REPORT_PATH, {
            "advertiser_id": mapping.advertiser_id,
            "report_type": "BASIC",
            "service_type": "AUCTION",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": json.dumps(["campaign_id"]),
            "metrics": json.dumps(["spend"]),
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "page": page,
            "page_size": REPORT_PAGE_SIZE,
        }, token)
        expected_pages, rows = _parse_campaign_page(data, page, expected_pages)
        if campaigns.intersection(rows):
            raise ValidationError("TikTok Ads campaign is duplicated across report pages.")
        campaigns.update(rows)
        total += sum(rows.values(), Decimal("0"))
        if page >= expected_pages:
            return total if campaigns else None
        page += 1


def _validated_scope(tenant_id, store_ids, *, lock=False):
    if tenant_id != PILOT_TENANT_ID or not Tenant.objects.filter(
        pk=tenant_id, code=PILOT_TENANT_CODE, status=Tenant.Status.ACTIVE,
    ).exists():
        raise ValidationError("TikTok Ads pilot tenant is not approved.")
    stores = list(StoreMaster.objects.filter(
        tenant_id=tenant_id, code__in=PILOT_ACCOUNT_COUNTS,
    ).only("id", "code"))
    if len(stores) != 2 or {store.id for store in stores} != set(store_ids):
        raise ValidationError("TikTok Ads pilot requires the two approved shops.")
    query = TikTokAdsAdvertiserMapping.objects.select_related(
        "store", "store__platform", "integration_config",
    ).filter(tenant_id=tenant_id).order_by("store_id", "advertiser_id")
    if lock:
        query = query.select_for_update()
    mappings = list(query)
    if len(mappings) != sum(PILOT_ACCOUNT_COUNTS.values()):
        raise ValidationError("TikTok Ads pilot account set is incomplete or expanded.")
    counts = {code: 0 for code in PILOT_ACCOUNT_COUNTS}
    configs = {code: set() for code in PILOT_ACCOUNT_COUNTS}
    account_ids = set()
    snapshot = []
    for mapping in mappings:
        code = mapping.store.code
        if code not in counts or mapping.store_id not in store_ids or not mapping.enabled:
            raise ValidationError("TikTok Ads pilot mapping is outside the approved enabled set.")
        mapping.full_clean()
        config = mapping.integration_config
        if (config.deleted_at or config.status not in {config.Status.VERIFIED, config.Status.ACTIVE}
                or not config.network_enabled or not config.sync_read_enabled):
            raise ValidationError("TikTok Ads config is not approved for read-only network use.")
        if not re.fullmatch(r"[A-Z]{3}", mapping.currency):
            raise ValidationError("Ads mapping currency is invalid.")
        try:
            ZoneInfo(mapping.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError("Ads mapping timezone is invalid.") from None
        counts[code] += 1
        configs[code].add(config.pk)
        account_ids.add(mapping.advertiser_id)
        snapshot.append((
            mapping.pk, mapping.store_id, code, mapping.advertiser_id,
            mapping.integration_config_id, mapping.token_id, mapping.currency,
            mapping.timezone, mapping.updated_at, config.updated_at,
            mapping.store.updated_at,
        ))
    if (counts != PILOT_ACCOUNT_COUNTS or len(account_ids) != len(mappings)
            or any(len(ids) != 1 for ids in configs.values())
            or len(set.union(*configs.values())) != 2):
        raise ValidationError("TikTok Ads pilot must contain exactly 2 and 10 approved advertisers.")
    return mappings, tuple(snapshot)


def _claim_lease(tenant_id):
    now = timezone.now()
    owner = uuid.uuid4().hex
    with transaction.atomic():
        lease, _ = TikTokAdsSyncLease.objects.get_or_create(
            tenant_id=tenant_id,
            defaults={"lease_expires_at": now - timedelta(seconds=1)},
        )
        claimed = TikTokAdsSyncLease.objects.filter(
            pk=lease.pk, lease_expires_at__lte=now,
        ).update(
            owner_token=owner, generation=F("generation") + 1,
            lease_expires_at=now + LEASE_DURATION, updated_at=now,
        )
        if not claimed:
            raise ValidationError("TikTok Ads pilot already has an active sync lease.")
        lease.refresh_from_db(fields=["generation"])
    return owner, lease.generation


def _renew_lease(tenant_id, owner, generation):
    now = timezone.now()
    updated = TikTokAdsSyncLease.objects.filter(
        tenant_id=tenant_id, owner_token=owner, generation=generation,
        lease_expires_at__gt=now,
    ).update(lease_expires_at=now + LEASE_DURATION, updated_at=now)
    if not updated:
        raise ValidationError("TikTok Ads sync lease ownership was lost or expired.")


def _check_running_switches(tenant_id, owner, generation):
    _renew_lease(tenant_id, owner, generation)
    mappings = TikTokAdsAdvertiserMapping.objects.filter(tenant_id=tenant_id)
    active = mappings.filter(
        enabled=True,
        integration_config__status__in=("verified", "active"),
        integration_config__network_enabled=True,
        integration_config__sync_read_enabled=True,
        integration_config__sync_write_enabled=False,
        integration_config__deleted_at__isnull=True,
    )
    if mappings.count() != 12 or active.count() != 12:
        raise ValidationError("TikTok Ads pilot was disabled or its account set changed during sync.")


def _release_lease(tenant_id, owner, generation):
    now = timezone.now()
    TikTokAdsSyncLease.objects.filter(
        tenant_id=tenant_id, owner_token=owner, generation=generation,
    ).update(owner_token="", lease_expires_at=now, updated_at=now)


def sync_seven_complete_days(*, tenant_id, approved_store_ids, now=None, http=None, custody=None,
                             on_lease_claim=None):
    """Sync Auction Campaign spend for the fixed 2+10 set with a fenced lease."""
    store_ids = tuple(approved_store_ids)
    if len(store_ids) != 2 or len(set(store_ids)) != 2:
        raise ValidationError("Exactly two distinct pilot stores must be approved.")
    _validated_scope(tenant_id, store_ids)
    require_live_mode("TikTok Ads read-only pilot")
    http = http or PlatformHttpClient()
    custody = custody or get_custody_backend()
    now = now or timezone.now()
    owner, generation = _claim_lease(tenant_id)
    results = []
    pending = []
    try:
        if on_lease_claim is not None:
            on_lease_claim(owner, generation)
        mappings, snapshot = _validated_scope(tenant_id, store_ids)
        for mapping in mappings:
            today = now.astimezone(ZoneInfo(mapping.timezone)).date()
            end = today - timedelta(days=1)
            start = end - timedelta(days=6)
            token = custody.retrieve_access_token(mapping.token_id)
            _validate_account(http, mapping, token)
            _check_running_switches(tenant_id, owner, generation)
            days = {}
            for offset in range(7):
                day = start + timedelta(days=offset)
                spend = _campaign_spend_for_day(http, mapping, token, day)
                _check_running_switches(tenant_id, owner, generation)
                if spend is not None:
                    days[day] = spend
            pending.append((mapping.pk, days))
            results.append({
                "store_id": mapping.store_id, "advertiser_id": mapping.advertiser_id,
                "spend_scope": "AUCTION_CAMPAIGN",
                "days_written": len(days),
                "missing_days": [(start + timedelta(days=i)).isoformat() for i in range(7)
                                 if start + timedelta(days=i) not in days],
            })
        with transaction.atomic():
            lease = TikTokAdsSyncLease.objects.select_for_update().get(tenant_id=tenant_id)
            commit_now = timezone.now()
            if (lease.owner_token != owner or lease.generation != generation
                    or lease.lease_expires_at <= commit_now):
                raise ValidationError("TikTok Ads sync lease ownership was lost before commit.")
            _renew_lease(tenant_id, owner, generation)
            locked_mappings, current_snapshot = _validated_scope(tenant_id, store_ids, lock=True)
            if current_snapshot != snapshot:
                raise ValidationError("TikTok Ads pilot approvals changed during sync.")
            by_id = {mapping.pk: mapping for mapping in locked_mappings}
            for mapping_id, days in pending:
                mapping = by_id[mapping_id]
                for day, spend in days.items():
                    TikTokAdsDailySpend.objects.update_or_create(
                        mapping=mapping, date=day,
                        defaults={"tenant_id": tenant_id, "spend": spend, "currency": mapping.currency},
                    )
            _release_lease(tenant_id, owner, generation)
        return results
    finally:
        _release_lease(tenant_id, owner, generation)
