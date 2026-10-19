"""Mapping-backed BASIC/AUCTION_CAMPAIGN spend, independent of Shop OAuth."""
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError as ModelValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from apps.common.module_gate import is_module_enabled

from .capability import require_live_mode
from .models import AdsOAuthSession, SyncJob, TikTokAdsAdvertiserMapping, TikTokAdsDailySpend, TikTokAdsSyncLease
from .oauth_state_service import configuration_digest
from .production_settings import get_runtime_platform_config, get_runtime_setting
from . import tiktok_ads_pilot as pilot
from .credential_service import validate_live_reference
from .oauth_errors import OAuthFlowError
from .retention_policy import RETENTION_START

RESOURCE = "advertising_report"
LEASE_WAIT_SECONDS = 1800


class AdsLeaseBusy(Exception):
    """Coordination contention, not a provider failure or a lost fence."""


class AdsLeaseWaitExpired(AdsLeaseBusy):
    """The original coordination deadline is never extended by a resume."""


class AdsExecutionStopped(ValidationError):
    """Approval revocation or fence loss must not become a fresh retry."""


class GuardedHttp:
    def __init__(self, client, guard):
        self.client, self.guard = client, guard

    def request(self, *args, **kwargs):
        self.guard()
        # Only framework retries may re-enter the approval guard.
        kwargs["retry"] = False
        return self.client.request(*args, **kwargs)


def lease_wait_metadata(previous=None):
    now = timezone.now()
    previous = previous or {}
    started = parse_datetime(str(previous.get("started_at") or "")) if previous.get("active") else None
    started = started or now
    if timezone.is_naive(started) or now >= started + timedelta(seconds=LEASE_WAIT_SECONDS):
        return None
    return {"active": True, "started_at": started.isoformat(),
            "deadline_at": (started + timedelta(seconds=LEASE_WAIT_SECONDS)).isoformat()}


def bound_evidence(mapping, *, lock=False):
    query = AdsOAuthSession.objects.filter(tenant_id=mapping.tenant_id, store_id=mapping.store_id,
        integration_config_id=mapping.integration_config_id, token_id=mapping.token_id, status="bound")
    if lock:
        query = query.select_for_update()
    for session in query.order_by("-created_at"):
        if (not session.credential_id or session.config_fingerprint != configuration_digest(mapping.integration_config)
                or not any(r.get("mapping_id") == mapping.pk and r.get("advertiser_id") == mapping.advertiser_id
                           for r in session.binding_results if isinstance(r, dict))):
            continue
        for candidate in session.candidates:
            if (isinstance(candidate, dict) and candidate.get("advertiser_id") == mapping.advertiser_id
                    and candidate.get("verify_state") == "verified" and candidate.get("verified_at")
                    and candidate.get("currency") == mapping.currency and candidate.get("timezone") == mapping.timezone):
                return session
    raise ValidationError("Ads mapping lacks current verified bound OAuth metadata.")


def validate_mapping(mapping, *, require_enabled=True, lock=False):
    if not is_module_enabled("api_integrations"):
        raise ValidationError("API data integration module is disabled.")
    config, store = mapping.integration_config, mapping.store
    try:
        mapping.full_clean()
        validate_live_reference(config.credential_id, "credential_id")
    except ModelValidationError:
        raise ValidationError("Ads mapping identity/configuration/custody reference is invalid.") from None
    now = timezone.now()
    if (require_enabled and not mapping.enabled or mapping.tenant.status != "active"
            or store.status != "active" or store.platform.status != "active"
            or store.platform.tenant_id != mapping.tenant_id
            or config.deleted_at or config.status not in {"verified", "active"}
            or not config.network_enabled or not config.sync_read_enabled or config.sync_write_enabled
            or config.credential_status != "configured" or not config.contract_version or config.credential_revoked_at
            or config.credential_expires_at and config.credential_expires_at <= now
            or config.regions and store.country_code.upper() not in {str(r).upper() for r in config.regions}
            or not re.fullmatch(r"[A-Z]{3}", mapping.currency)):
        raise ValidationError("Ads mapping/configuration is not approved for read-only collection.")
    try:
        ZoneInfo(mapping.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Ads advertiser timezone is invalid.") from None
    require_live_mode("TikTok Ads standard read-only sync")
    if (not get_runtime_setting("network", "readonly_sync_enabled", default=False)
            or not get_runtime_platform_config("tiktok").get("contract_approved")):
        raise ValidationError("Ads read-only runtime gates are disabled.")
    evidence = bound_evidence(mapping, lock=lock)
    try:
        validate_live_reference(evidence.credential_id, "credential_id")
    except ModelValidationError:
        raise ValidationError("Ads bound custody evidence is invalid.") from None
    return evidence


def load_mapping(job, *, lock=False):
    if (job.resource_type != RESOURCE or not job.ads_mapping_id
            or job.store_authorization_id or job.warehouse_authorization_id):
        raise ValidationError("Ads jobs require an exclusive advertiser mapping.")
    query = TikTokAdsAdvertiserMapping.objects
    if lock:
        query = query.select_for_update()
    mapping = query.select_related("store__platform", "integration_config", "tenant").filter(
        pk=job.ads_mapping_id, tenant_id=job.tenant_id, integration_config_id=job.integration_config_id).first()
    if mapping is None:
        raise ValidationError("Ads mapping no longer matches the job tenant/configuration.")
    return mapping


def lock_runtime_approval():
    # Config publication also locks the definition, including a new version.
    from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion
    from .production_settings import CONFIG_KEY, runtime_snapshot
    from .module_release import (
        MODULE_RELEASE_CONFIG_KEY, is_legacy_module_release_config, validate_module_release_config,
    )
    list(SystemConfigDefinition.objects.select_for_update().filter(
        config_key__in=[CONFIG_KEY, MODULE_RELEASE_CONFIG_KEY]).order_by("pk"))
    runtime_versions = list(TenantConfigVersion.objects.select_for_update().filter(
        config_key=CONFIG_KEY, scope_key="system", status__in=["effective", "superseded"],
        definition__scope_type="system", effective_at__lte=timezone.now()).order_by("-version", "-id"))
    runtime_version = next((row for row in runtime_versions if not is_legacy_module_release_config(row.value)), None)
    observed = runtime_snapshot()
    # Domain getters may still see a page's earlier RR snapshot. Refuse that
    # snapshot rather than committing against a newer global stop approval.
    if not observed["valid"] or observed["version_id"] != (runtime_version.pk if runtime_version else None):
        raise ValidationError("Production runtime approval changed during the page transaction.")
    # A definition lock alone does not refresh a MySQL REPEATABLE READ snapshot.
    # Select the authoritative version with a locking/current read as well.
    version = (TenantConfigVersion.objects.select_for_update().filter(
        config_key=MODULE_RELEASE_CONFIG_KEY, scope_key="system", status="effective",
        definition__scope_type="system", effective_at__lte=timezone.now())
        .order_by("-version", "-id").first())
    if version is None:
        for candidate in runtime_versions:
            if is_legacy_module_release_config(candidate.value):
                version = candidate
                break
    if version is not None:
        try:
            state = validate_module_release_config(version.value)["modules"]["api_integrations"]
        except ModelValidationError:
            raise ValidationError("Current module release approval is invalid.") from None
        if state not in {"enabled", "pilot_readonly"}:
            raise ValidationError("API data integration module is disabled by the current approval.")


def validate_atomic_policy(policy):
    schedule = (policy or {}).get("schedule") or {}
    if schedule.get("execution_budget_seconds", 0) != 0 or (policy or {}).get("execution_budget_seconds", 0) != 0:
        raise ValidationError("Ads reports require an atomic complete window; execution budget must be zero.")


def resolve_scope(mapping, policy=None, *, now=None):
    query = (policy or {}).get("query") or {}
    if not isinstance(query, dict):
        raise ValidationError("Ads query policy must be an object.")
    if "lookback_days" in query and (type(query["lookback_days"]) is not int or not 1 <= query["lookback_days"] <= 7):
        raise ValidationError("Ads lookback_days must be an integer from 1 to 7.")
    try:
        today = (now or timezone.now()).astimezone(ZoneInfo(mapping.timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Ads advertiser timezone is invalid.") from None
    mode = query.get("mode", "incremental")
    if mode == "incremental":
        days = query.get("lookback_days", 7)
        if type(days) is not int or not 1 <= days <= 7:
            raise ValidationError("Ads lookback_days must be an integer from 1 to 7.")
        end = today - timedelta(days=1)
        start = end - timedelta(days=days - 1)
    elif mode == "range":
        try:
            start, end = (date.fromisoformat(query[k]) for k in ("start_at", "end_at"))
            if any(query[k] != d.isoformat() for k, d in (("start_at", start), ("end_at", end))):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ValidationError("Ads ranges require advertiser-local YYYY-MM-DD dates.") from None
    else:
        raise ValidationError("Ads query mode must be incremental or range.")
    if not 1 <= (end - start).days + 1 <= 7 or end >= today:
        raise ValidationError("Ads collection requires 1-7 completed advertiser-local days.")
    if start < RETENTION_START:
        raise ValidationError("Ads advertiser-local dates cannot precede the retention floor.")
    return {"ads_mapping_id": mapping.pk, "advertiser_id": mapping.advertiser_id,
            "advertiser_timezone": mapping.timezone, "time_from": start.isoformat(),
            "time_to": end.isoformat(), "start_date": start.isoformat(), "end_date": end.isoformat(),
            "report_scope": "AUCTION_CAMPAIGN"}


def snapshot(mapping, evidence):
    return (mapping.pk, mapping.tenant_id, mapping.store_id, mapping.integration_config_id,
            mapping.advertiser_id, mapping.token_id, mapping.currency, mapping.timezone, mapping.enabled,
            mapping.updated_at, configuration_digest(mapping.integration_config), mapping.integration_config.updated_at,
            mapping.integration_config.sync_read_enabled, mapping.integration_config.sync_write_enabled,
            mapping.store.updated_at, mapping.store.platform.status, evidence.pk, evidence.token_id,
            evidence.credential_id, evidence.candidates, evidence.binding_results)


def _explicit_advertiser_zero(http, mapping, token, day, renew):
    renew()
    data = pilot._get(http, pilot.REPORT_PATH, {
        "advertiser_id": mapping.advertiser_id, "report_type": "BASIC", "service_type": "AUCTION",
        "data_level": "AUCTION_ADVERTISER", "dimensions": json.dumps(["advertiser_id", "stat_time_day"]),
        "metrics": json.dumps(["spend"]), "start_date": day.isoformat(), "end_date": day.isoformat(),
        "enable_total_metrics": "true", "page": 1, "page_size": pilot.REPORT_PAGE_SIZE}, token)
    info, totals = data.get("page_info"), data.get("total_metrics")
    if (not isinstance(info, dict) or not isinstance(totals, dict) or data.get("list") != []
            or any(type(info.get(key)) is not int or info[key] != expected
                   for key, expected in (("page", 1), ("total_page", 0), ("total_number", 0)))):
        return None
    raw = totals.get("spend")
    if isinstance(raw, (bool, float)) or not re.fullmatch(r"\d+(?:\.\d{1,6})?", str(raw)):
        return None
    # Only an explicit same-day BASIC advertiser total proves an empty day is
    # zero. Empty campaign lists, '-' and GMV Max totals never provide proof.
    return Decimal("0") if Decimal(str(raw)) == 0 else None


def collect_day(http, mapping, token, day, renew, *, proof=None):
    campaigns, total, expected_pages, expected_total = set(), Decimal("0"), None, None
    for page in range(1, pilot.MAX_REPORT_PAGES + 1):
        renew()
        data = pilot._get(http, pilot.REPORT_PATH, {
            "advertiser_id": mapping.advertiser_id, "report_type": "BASIC", "service_type": "AUCTION",
            "data_level": "AUCTION_CAMPAIGN", "dimensions": json.dumps(["campaign_id"]),
            "metrics": json.dumps(["spend"]), "start_date": day.isoformat(), "end_date": day.isoformat(),
            "page": page, "page_size": pilot.REPORT_PAGE_SIZE}, token)
        info = data.get("page_info")
        if not isinstance(info, dict) or type(info.get("total_page")) is not int:
            raise ValidationError("Ads pagination requires an integer total_page.")
        if type(info.get("page")) is not int or info["page"] != page:
            raise ValidationError("Ads returned a different report page.")
        count = info.get("total_number")
        if type(count) is not int or count < 0 or expected_total is not None and count != expected_total:
            raise ValidationError("Ads report row count changed or is invalid.")
        expected_total = count
        expected_pages, rows = pilot._parse_campaign_page(data, page, expected_pages)
        if campaigns.intersection(rows) or len(rows) > pilot.REPORT_PAGE_SIZE:
            raise ValidationError("Ads campaign report is duplicated or oversized.")
        if page < expected_pages and len(rows) != pilot.REPORT_PAGE_SIZE:
            raise ValidationError("Ads non-final report page is truncated.")
        campaigns.update(rows)
        total += sum(rows.values(), Decimal("0"))
        if page >= expected_pages:
            if len(campaigns) != expected_total:
                raise ValidationError("Ads report row count is incomplete.")
            if campaigns:
                if proof is not None:
                    proof.update(source="campaign_rows", campaign_count=len(campaigns))
                return total
            if expected_total == 0:
                explicit = _explicit_advertiser_zero(http, mapping, token, day, renew)
                if explicit is not None and proof is not None:
                    proof.update(source="explicit_advertiser_total_zero", data_level="AUCTION_ADVERTISER")
                return explicit
            return None
    raise ValidationError("Ads report exceeded the bounded page limit.")


class AdsSpendAdapter:
    adapter_name = "tiktok_ads_campaign_spend"
    execution_mode = "live_readonly"

    def __init__(self, config):
        self.config = config
        self.scope = {}
        self.lease = None

    def validate_configuration(self, job):
        validate_atomic_policy(job.sync_scope)
        mapping = load_mapping(job)
        validate_mapping(mapping)
        self.scope = resolve_scope(mapping, job.sync_scope)

    def bind_run(self, run):
        self.source_run = run

    def release(self):
        if self.lease:
            pilot._release_lease(self.mapping.tenant_id, *self.lease)

    def before_request(self, job):
        current_job = SyncJob.objects.get(pk=job.pk, tenant_id=job.tenant_id)
        if (not current_job.is_enabled or current_job.status != "running"
                or current_job.lock_token != self.source_run.run_id or not current_job.lock_expires_at
                or current_job.lock_expires_at <= timezone.now()):
            raise AdsExecutionStopped("Ads job lease lost before request.")
        try:
            validate_atomic_policy(current_job.sync_scope)
            mapping = load_mapping(current_job)
            evidence = validate_mapping(mapping)
        except (ValidationError, OAuthFlowError):
            raise AdsExecutionStopped("Ads read approvals were revoked before request.") from None
        if snapshot(mapping, evidence) != self.approval_snapshot:
            raise AdsExecutionStopped("Ads approvals changed before request.")
        try:
            pilot._renew_lease(job.tenant_id, *self.lease)
        except ModelValidationError:
            raise AdsExecutionStopped("Ads tenant lease lost before request.") from None

    def fetch_page(self, job, cursor_value=None):
        self.release()
        mapping = load_mapping(job)
        evidence = validate_mapping(mapping)
        expected = resolve_scope(mapping, {"query": {"mode": "range", "start_at": self.scope.get("time_from"),
                                                     "end_at": self.scope.get("time_to")}})
        if expected != self.scope:
            raise ValidationError("Frozen Ads account scope changed.")
        self.mapping = mapping
        self.approval_snapshot = snapshot(mapping, evidence)
        previous_wait = (self.source_run.masked_log or {}).get("ads_lease_wait") or {}
        if previous_wait.get("active") and lease_wait_metadata(previous_wait) is None:
            raise AdsLeaseWaitExpired("Ads tenant lease wait deadline expired.")
        try:
            self.lease = pilot._claim_lease(job.tenant_id)
        except ModelValidationError:
            raise AdsLeaseBusy("Ads tenant lease is busy; the frozen window is waiting.") from None
        try:
            if (self.source_run.masked_log or {}).get("ads_lease_wait", {}).get("active"):
                self.source_run.masked_log = {**self.source_run.masked_log, "ads_lease_wait": {
                    **self.source_run.masked_log["ads_lease_wait"], "active": False, "acquired_at": timezone.now().isoformat()}}
                from .sync_services import _save_run
                _save_run(self.source_run, update_fields=["masked_log"])
            self.before_request(job)
            token = pilot.get_custody_backend().retrieve_access_token(mapping.token_id)
            http = GuardedHttp(pilot.PlatformHttpClient(), lambda: self.before_request(job))
            self.before_request(job)
            # Current API metadata must include the exact timezone, not an absent value.
            data = pilot._get(http, pilot.INFO_PATH, {"advertiser_ids": json.dumps([mapping.advertiser_id])}, token)
            accounts = data.get("list")
            from .tiktok_ads_oauth import account_timezone
            if (not isinstance(accounts, list) or len(accounts) != 1 or not isinstance(accounts[0], dict)
                    or str(accounts[0].get("advertiser_id")) != mapping.advertiser_id
                    or accounts[0].get("currency") != mapping.currency
                    or account_timezone(accounts[0]) != mapping.timezone):
                raise ValidationError("Current Ads account identity/currency/timezone could not be verified.")
            records = []
            start, end = date.fromisoformat(self.scope["time_from"]), date.fromisoformat(self.scope["time_to"])
            for offset in range((end - start).days + 1):
                day = start + timedelta(days=offset)
                proof = {}
                spend = collect_day(http, mapping, token, day,
                    lambda: self.before_request(job), proof=proof)
                if spend is None:
                    raise ValidationError("Ads day has no verified spend evidence; complete window not committed.")
                if spend >= 10 ** 14:
                    raise ValidationError("Ads spend exceeds storage precision.")
                records.append({"date": day.isoformat(), "spend": str(spend), "currency": mapping.currency,
                                "evidence": proof})
            return {"records": records, "next_cursor": "", "report_scope": "AUCTION_CAMPAIGN"}
        except BaseException:
            self.release()
            raise

    def normalize_record(self, record):
        return record

    def validate_record(self, record):
        return True  # Complete records are strictly parsed before returning the single page.

    def persist_records(self, job, records):
        expected = resolve_scope(self.mapping, {"query": {"mode": "range",
            "start_at": self.scope.get("time_from"), "end_at": self.scope.get("time_to")}})
        if expected != self.scope:
            raise ValidationError("Frozen Ads account scope changed before commit.")
        # Validate the entire batch before the first upsert, including bypass callers.
        records = list(records)
        for record in records:
            try:
                day = date.fromisoformat(record["date"])
                if (record["date"] != day.isoformat() or day < RETENTION_START
                        or not self.scope["time_from"] <= day.isoformat() <= self.scope["time_to"]):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise ValidationError("Ads record date is outside the frozen retained window.") from None
        # Called inside the framework's page transaction. Hold every approval row
        # until spend, checkpoint, run success and job release commit together.
        locked_job = SyncJob.objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if (not locked_job.is_enabled or locked_job.status != "running"
                or locked_job.lock_token != self.source_run.run_id
                or not locked_job.lock_expires_at or locked_job.lock_expires_at <= timezone.now()):
            raise AdsExecutionStopped("Ads job lease lost before commit.")
        lease = TikTokAdsSyncLease.objects.select_for_update().get(tenant_id=job.tenant_id)
        if (not self.lease or (lease.owner_token, lease.generation) != self.lease
                or lease.lease_expires_at <= timezone.now()):
            raise AdsExecutionStopped("Ads tenant lease lost before commit.")
        mapping = load_mapping(locked_job, lock=True)
        try:
            lock_runtime_approval()
            evidence = validate_mapping(mapping, lock=True)
        except (ValidationError, OAuthFlowError):
            raise AdsExecutionStopped("Ads read approvals were revoked before commit.") from None
        if snapshot(mapping, evidence) != self.approval_snapshot:
            raise AdsExecutionStopped("Ads approvals changed during collection.")
        results = []
        for record in records:
            _, created = TikTokAdsDailySpend.objects.update_or_create(mapping=mapping, date=record["date"],
                defaults={"tenant_id": job.tenant_id, "spend": record["spend"], "currency": mapping.currency})
            results.append({"action": "created" if created else "updated"})
        return results

    def finalize_run(self, job):
        try:
            validate_mapping(load_mapping(job))
        except (ValidationError, OAuthFlowError):
            raise AdsExecutionStopped("Ads read approvals were revoked before finalization.") from None
        now = timezone.now()
        if (not SyncJob.objects.filter(pk=job.pk, tenant_id=job.tenant_id, is_enabled=True,
                    status="running", lock_token=self.source_run.run_id, lock_expires_at__gt=now).exists()
                or not TikTokAdsSyncLease.objects.filter(tenant_id=job.tenant_id,
                    owner_token=self.lease[0], generation=self.lease[1], lease_expires_at__gt=now).exists()):
            raise AdsExecutionStopped("Ads lease expired before window finalization.")
        self.source_run.masked_log = {**self.source_run.masked_log, "ads_report": {
            "report_type": "BASIC", "report_scope": "AUCTION_CAMPAIGN", "metric": "spend",
            "mapping_id": self.mapping.pk, "time_from": self.scope["time_from"], "time_to": self.scope["time_to"],
            "currency": self.mapping.currency, "timezone": self.mapping.timezone, "complete_window": True}}

    def get_next_cursor(self, page):
        return ""

    def should_continue(self, page, previous_cursor):
        return False
