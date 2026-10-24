"""Complete-day affiliate ingestion using the existing sync lease and dispatcher."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import CharField, F
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.influencers.attribution import (
    _order_values, affiliate_order_row_hash, affiliate_order_source_row_key, normalize_account,
)
from apps.influencers.models import AffiliateOrderSnapshot
from apps.influencers.tiktok_shop_dataset import (
    AFFILIATE_CONTRACT_VERSION, AFFILIATE_COUNT_UNIT, DatasetError, TikTokDatasetClient, canonical_bytes, digest_bytes,
)
from apps.tenants.models import Tenant
from .adapters import ProductionReadonlyAdapter
from .models import SyncCursor, SyncJob, SyncRawEnvelope, SyncRun
from .raw_services import load_raw_payload, payload_digest
from .readonly_clients import ReadonlyConfigurationError


VERSION = AFFILIATE_CONTRACT_VERSION
SITE_COUNTRIES = {"PH": "PH", "MY": "MY", "TH": "TH",
                  "\u83f2\u5f8b\u5bbe": "PH", "\u9a6c\u6765": "MY", "\u9a6c\u6765\u897f\u4e9a": "MY", "\u6cf0\u56fd": "TH"}
SCOPES = {"seller.authorization.info", "seller.affiliate_collaboration.read", "seller.order.info"}
MONEY_FIELDS = {"price": "product_price", "estimated_commission_base": "estimated_commission_base",
                "estimated_paid_commission": "estimated_paid_commission", "actual_paid_commission": "actual_paid_commission",
                "actual_paid_shop_ads_commission": "actual_paid_shop_ads_commission"}


def _verified_single_line_payment(order, currency):
    """Only a reconciled single-unit, single-SKU order proves a SKU payment."""
    lines = order.get("line_items")
    unknown = {"amount": None, "currency": currency}
    if not isinstance(lines, list) or len(lines) != 1 or not isinstance(lines[0], dict):
        return {"sku_id": None, "payment": unknown, "payment_status": "unknown"}
    line = lines[0]
    sku_id = line.get("sku_id")
    if not isinstance(sku_id, str) or not sku_id or len(sku_id) > 160 or type(line.get("quantity")) is not int or line["quantity"] != 1:
        return {"sku_id": None, "payment": unknown, "payment_status": "unknown"}
    payment = order.get("payment") or {}
    sale = {"amount": line.get("sale_price"), "currency": currency}
    total = {"amount": payment.get("total_amount"), "currency": payment.get("currency")}
    if _money(sale, currency) is None or _money(sale, currency) != _money(total, currency):
        return {"sku_id": sku_id, "payment": unknown, "payment_status": "unknown"}
    return {"sku_id": sku_id, "payment": sale, "payment_status": "verified_single_line"}


def _day(value):
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ReadonlyConfigurationError("AFFILIATE_INVALID_DATE") from None
    if parsed.isoformat() != value:
        raise ReadonlyConfigurationError("AFFILIATE_INVALID_DATE")
    return parsed


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ReadonlyConfigurationError("AFFILIATE_INVALID_LIMIT")
    return value


def _money(value, currency):
    if not isinstance(value, dict):
        raise DatasetError("affiliate_invalid_money")
    amount = value.get("amount")
    if amount is None:
        return None
    if value.get("currency") != currency or isinstance(amount, (float, bool)):
        raise DatasetError("affiliate_currency_or_precision_mismatch")
    try:
        number = Decimal(amount)
    except (ValueError, TypeError, ArithmeticError):
        raise DatasetError("affiliate_invalid_money") from None
    if not number.is_finite() or number < 0 or number >= Decimal("1e16") or number != number.quantize(Decimal("0.0001")):
        raise DatasetError("affiliate_invalid_money")
    return number


def _refund(value):
    if value in (None, ""):
        return ""
    if value in ("No", "NO", "False", "false", "0", "\u5426"):
        return "\u5426"
    if value in ("Yes", "YES", "True", "true", "1", "\u662f"):
        return "\u662f"
    raise DatasetError("affiliate_unknown_full_refund")


def build_plan(job, store, policy, now=None):
    """Recent-day replay plus a durable, rotating full approved history range."""
    floor = _day(policy.get("historical_start"))
    today = (now or timezone.now()).astimezone(ZoneInfo(store.timezone)).date()
    last = today - timedelta(days=1)
    if floor > last:
        raise ReadonlyConfigurationError("AFFILIATE_NO_COMPLETED_DAY")
    source = policy.get("snapshot_source")
    site = policy.get("site")
    if not isinstance(source, str) or not 1 <= len(source) <= 40 or SITE_COUNTRIES.get(site) != store.country_code.upper():
        raise ReadonlyConfigurationError("AFFILIATE_EXPLICIT_SOURCE_AND_SITE_REQUIRED")
    recent_count = _integer(policy.get("recent_days", 7), 1, 7)
    archive_count = _integer(policy.get("archive_days_per_run", 2), 1, 7)
    new_count = _integer(policy.get("new_days_per_run", 5), 1, 7)
    trial = policy.get("trial_days")
    if trial is not None:
        if not isinstance(trial, list) or not 1 <= len(trial) <= 7:
            raise ReadonlyConfigurationError("AFFILIATE_INVALID_TRIAL_DAYS")
        days = sorted({_day(value) for value in trial})
        if len(days) != len(trial) or any(day < floor or day > last for day in days):
            raise ReadonlyConfigurationError("AFFILIATE_TRIAL_OUTSIDE_APPROVED_RANGE")
        new_days, archive_next = [], None
    else:
        progress = dict(SyncCursor.objects.filter(tenant_id=job.tenant_id, sync_job=job,
                         cursor_key__in=["affiliate-next-new-day", "affiliate-history-day"])
                        .values_list("cursor_key", "cursor_value"))
        next_new = max(floor, _day(progress.get("affiliate-next-new-day", floor.isoformat())))
        new_days = [next_new + timedelta(days=i) for i in range(new_count) if next_new + timedelta(days=i) <= last]
        recent_start = max(floor, last - timedelta(days=recent_count - 1))
        recent = [recent_start + timedelta(days=i) for i in range((last - recent_start).days + 1)]
        archive_day = max(floor, _day(progress.get("affiliate-history-day", floor.isoformat())))
        if archive_day >= recent_start:
            archive_day = floor
        archive = [archive_day + timedelta(days=i) for i in range(archive_count)
                   if archive_day + timedelta(days=i) < recent_start]
        archive_next = (archive[-1] + timedelta(days=1)).isoformat() if archive else floor.isoformat()
        days = list(dict.fromkeys([*new_days, *recent, *archive]))
        if len(days) > 14:
            raise ReadonlyConfigurationError("AFFILIATE_DAILY_DAY_BUDGET_EXCEEDED")
    return {"version": VERSION, "count_unit": AFFILIATE_COUNT_UNIT, "tenant_id": job.tenant_id, "store_id": store.pk,
            "timezone": store.timezone, "snapshot_source": source, "site": site,
            "historical_start": floor.isoformat(), "days": [day.isoformat() for day in days],
            "new_days": [day.isoformat() for day in new_days], "archive_next": archive_next}


class DatabasePageJournal:
    """Projected, immutable page checkpoints; provider secrets/PII are never saved."""

    def __init__(self, job, run, scope):
        self.job, self.run, self.scope = job, run, scope

    def _endpoint(self, descriptor):
        return "checkpoint://affiliate/" + digest_bytes(canonical_bytes({"version": VERSION,
            "count_unit": AFFILIATE_COUNT_UNIT, "scope": self.scope, "query": descriptor}))

    def load(self, descriptor):
        entry = SyncRawEnvelope.objects.filter(tenant_id=self.job.tenant_id, sync_run=self.run,
            store_id=self.job.store_authorization.store_id, endpoint=self._endpoint(descriptor)).first()
        if entry is None:
            return None
        try:
            payload = load_raw_payload(entry)
        except ValidationError as exc:
            raise DatasetError("affiliate_checkpoint_storage_unavailable") from exc
        if payload_digest(payload) != entry.payload_hash:
            raise DatasetError("affiliate_checkpoint_digest_mismatch")
        if (entry.schema_version != VERSION or not isinstance(payload, dict)
                or payload.get("version") != VERSION
                or payload.get("count_unit") != AFFILIATE_COUNT_UNIT
                or payload.get("scope") != self.scope or not isinstance(payload.get("result"), dict)):
            raise DatasetError("affiliate_checkpoint_version_mismatch")
        return payload["result"]

    def save(self, descriptor, result):
        payload = {"version": VERSION, "count_unit": AFFILIATE_COUNT_UNIT, "scope": self.scope, "result": result}
        if len(canonical_bytes(payload)) > 2 * 1024 * 1024:
            raise DatasetError("affiliate_checkpoint_size_exceeded")
        with transaction.atomic():
            job = SyncJob.objects.select_for_update().get(pk=self.job.pk, tenant_id=self.job.tenant_id)
            if (job.status != "running" or job.lock_token != self.run.run_id
                    or not job.lock_expires_at or job.lock_expires_at <= timezone.now()):
                raise ReadonlyConfigurationError("AFFILIATE_LEASE_LOST")
            if self.load(descriptor) is not None:
                return
            sequence = self.run.raw_envelopes.count() + 1
            SyncRawEnvelope.objects.create(tenant_id=job.tenant_id, sync_run=self.run,
                store_id=job.store_authorization.store_id, platform="tiktok", endpoint=self._endpoint(descriptor),
                sequence=sequence, schema_version=VERSION, payload=payload, payload_hash=payload_digest(payload))


class TikTokAffiliateOrderAdapter(ProductionReadonlyAdapter):
    adapter_name = "tiktok-affiliate-daily"

    def _client(self):
        if self.client is None:
            self.client = TikTokDatasetClient(self.config, self.authorization)
        self.client.resource_type = "affiliate_order"
        self.client.strict_affiliate_money = True
        self.client.strict_affiliate_contract = True
        return self.client

    def _fence(self, sync_job):
        run = self._require_run()
        job = SyncJob.objects.select_for_update().get(pk=sync_job.pk, tenant_id=sync_job.tenant_id)
        if (job.status != "running" or job.lock_token != run.run_id
                or not job.lock_expires_at or job.lock_expires_at <= timezone.now()
                or run.sync_job_id != job.pk or run.tenant_id != job.tenant_id):
            raise ReadonlyConfigurationError("AFFILIATE_LEASE_LOST")
        return job

    def validate_configuration(self, sync_job):
        super().validate_configuration(sync_job)
        if not self.authorization or not SCOPES <= set(self.authorization.scopes or []):
            raise ReadonlyConfigurationError("AFFILIATE_REQUIRED_SCOPE_MISSING")
        self.scope["affiliate_plan"] = build_plan(sync_job, self.authorization.store,
                                                  (sync_job.sync_scope or {}).get("affiliate", {}))

    def fetch_page(self, sync_job, cursor_value=None):
        self.verified_day_digest = None
        run = self._require_run()
        plan = self.scope["affiliate_plan"]
        store = self.authorization.store
        if (plan.get("version") != VERSION or plan.get("count_unit") != AFFILIATE_COUNT_UNIT
                or plan["tenant_id"] != sync_job.tenant_id
                or plan["store_id"] != store.pk or plan["timezone"] != store.timezone):
            raise ReadonlyConfigurationError("AFFILIATE_FROZEN_SCOPE_MISMATCH")
        prefix = "a3:" + run.run_id + ":"
        if cursor_value in (None, ""):
            index = 0
        else:
            if not isinstance(cursor_value, str) or not cursor_value.startswith(prefix):
                raise ReadonlyConfigurationError("AFFILIATE_INVALID_DAY_CURSOR")
            suffix = cursor_value[len(prefix):]
            if not suffix.isascii() or not suffix.isdigit() or len(suffix) > 2:
                raise ReadonlyConfigurationError("AFFILIATE_INVALID_DAY_CURSOR")
            index = int(suffix)
            if suffix != str(index):
                raise ReadonlyConfigurationError("AFFILIATE_INVALID_DAY_CURSOR")
        if not 0 <= index < len(plan["days"]):
            raise ReadonlyConfigurationError("AFFILIATE_INVALID_DAY_CURSOR")
        day = _day(plan["days"][index])
        journal = DatabasePageJournal(sync_job, run, {"plan": plan, "day": day.isoformat(),
            "authorization_id": self.authorization.pk, "reference_version": self.authorization.credential_reference_version})
        client = self._client()
        try:
            client.verify_shop()
            rows, _ = client.affiliate_orders(day, day, ZoneInfo(store.timezone), staging=True, checkpoint=journal)
            if type(client.last_page_summary.get("expected_count")) is not int:
                raise DatasetError("affiliate_total_count_required")
            coverage = client.last_page_summary
            if (coverage.get("status") != "complete" or not coverage.get("pagination_exhausted")
                    or coverage.get("version") != VERSION or coverage.get("count_unit") != AFFILIATE_COUNT_UNIT
                    or any(type(coverage.get(key)) is not int or coverage[key] != len(rows)
                           for key in ("expected_count", "observed_count", "sku_row_count", "unique_sku_count"))):
                raise DatasetError("affiliate_sku_count_proof_required")
            ids = sorted({row["order_id"] for row in rows})
            details = {}
            for offset in range(0, len(ids), 50):
                batch = ids[offset:offset + 50]
                descriptor = {"kind": "affiliate-ordinary-order-details", "ids": batch}
                projected = journal.load(descriptor)
                if projected is None:
                    data = client._transport_request(client._runtime_path("order_detail_path", client.ORDER_DETAIL_PATH),
                        query={"shop_cipher": self.authorization.shop_cipher, "ids": ",".join(batch)})["data"]
                    observed_at = timezone.now().isoformat()
                    orders = data.get("orders")
                    if not isinstance(orders, list):
                        raise DatasetError("affiliate_order_details_missing")
                    projected = {}
                    for order in orders:
                        if not isinstance(order, dict) or str(order.get("id")) not in batch or str(order["id"]) in projected:
                            raise DatasetError("affiliate_order_detail_identity_mismatch")
                        payment = order.get("payment") or {}
                        amount = payment.get("total_amount")
                        money = {"amount": amount, "currency": payment.get("currency")}
                        _money(money, store.currency.upper())
                        status = order.get("status")
                        if not isinstance(status, str) or not status or len(status) > 40:
                            raise DatasetError("affiliate_order_status_missing")
                        projected[str(order["id"])] = {**_verified_single_line_payment(order, store.currency.upper()),
                                                      "order_status": status,
                                                      "detail_observed_at": observed_at}
                    if set(projected) != set(batch):
                        raise DatasetError("affiliate_order_details_incomplete")
                    journal.save(descriptor, projected)
                details.update(projected)
            seen = set()
            for row in rows:
                key = (row["order_id"], row["sku_id"])
                if key in seen:
                    raise DatasetError("affiliate_conflicting_order_sku")
                seen.add(key)
                detail = details[row["order_id"]]
                row.update({key: value for key, value in detail.items() if key != "sku_id"}, business_day=day.isoformat())
                if (detail.get("payment_status") != "verified_single_line" or detail.get("sku_id") != row["sku_id"]
                        or row.get("quantity") != 1):
                    row["payment"] = {"amount": None, "currency": store.currency.upper()}
                self.normalize_record(row)
            self.verified_day_digest = digest_bytes(canonical_bytes([
                _order_values(AffiliateOrderSnapshot(**self.normalize_record(row))) for row in rows]))
        except DatasetError as exc:
            raise ReadonlyConfigurationError("AFFILIATE_DATA_CONTRACT:" + str(exc)) from None
        return {"records": rows, "day": day.isoformat(), "index": index,
                "next_cursor": prefix + str(index + 1) if index + 1 < len(plan["days"]) else "",
                "raw_responses": [{"endpoint": "projected://affiliate/complete-day",
                    "payload": {"business_day": day.isoformat(), "coverage": client.last_page_summary}}]}

    def normalize_record(self, row):
        store, plan = self.authorization.store, self.scope["affiliate_plan"]
        quantity = row.get("quantity")
        if type(quantity) is not int or not 1 <= quantity <= 2147483647:
            raise DatasetError("affiliate_quantity_unknown")
        if not row.get("creator_username"):
            raise DatasetError("affiliate_creator_identity_missing")
        observations = [parse_datetime(str(row.get(field) or ""))
                        for field in ("affiliate_observed_at", "detail_observed_at")]
        if any(value is None or timezone.is_naive(value) for value in observations):
            raise DatasetError("affiliate_observation_required")
        values = {"source": plan["snapshot_source"], "shop_abbr": store.code, "shop_name": store.name,
                  "site": plan["site"], "store_id": store.pk, "data_time": datetime.combine(_day(row["business_day"]), time.min, UTC),
                  "order_id": row["order_id"], "sku_id": row["sku_id"], "product_id": row["product_id"],
                  "product_name": "", "creator_username": row["creator_username"],
                  "creator_username_normalized": normalize_account(row["creator_username"]),
                  "quantity": quantity, "currency": store.currency.upper(), "fully_returned": _refund(row.get("fully_return")),
                  "settlement_status": row.get("settlement_status"), "order_status": row["order_status"],
                  "payment_amount": _money(row["payment"], store.currency.upper()),
                  "source_updated_at": min(observations)}
        for key, field in MONEY_FIELDS.items():
            values[field] = _money(row[key], store.currency.upper())
        values["source_row_key"] = affiliate_order_source_row_key(**{key: values[key]
            for key in ("data_time", "shop_abbr", "site", "order_id", "sku_id")})
        return values

    def persist_records(self, sync_job, records):
        from apps.influencers.management.commands.import_affiliate_orders_csv import Command
        fingerprint = digest_bytes(canonical_bytes([_order_values(AffiliateOrderSnapshot(**values)) for values in records]))
        if fingerprint != getattr(self, "verified_day_digest", None):
            raise ReadonlyConfigurationError("AFFILIATE_COMPLETE_DAY_REQUIRED")
        with transaction.atomic():
            tenant = Tenant.objects.select_for_update().get(pk=sync_job.tenant_id)
            self._fence(sync_job)
            results = []
            writer = Command()
            for values in records:
                candidates = list(AffiliateOrderSnapshot.objects.select_for_update().filter(
                    tenant=tenant, shop_abbr=values["shop_abbr"], order_id=values["order_id"], sku_id=values["sku_id"]))
                if len(candidates) > 1:
                    raise ReadonlyConfigurationError("AFFILIATE_EXISTING_IDENTITY_AMBIGUOUS")
                current = candidates[0] if candidates else None
                if current:
                    if (current.store_id not in (None, values["store_id"]) or SITE_COUNTRIES.get(current.site) != SITE_COUNTRIES.get(values["site"])
                            or current.data_time.date() != values["data_time"].date() or current.product_id != values["product_id"]
                            or current.creator_username_normalized != values["creator_username_normalized"]):
                        raise ReadonlyConfigurationError("AFFILIATE_PROTECTED_IDENTITY_CONFLICT")
                    incoming = {**values, "source": current.source, "source_row_key": current.source_row_key,
                        "data_time": current.data_time, "site": current.site, "shop_name": current.shop_name,
                        "product_name": current.product_name, "creator_username": current.creator_username,
                        "store_id": current.store_id}
                    for field in (*MONEY_FIELDS.values(), "payment_amount", "settlement_status"):
                        if incoming[field] is None:
                            incoming[field] = getattr(current, field)
                    if not incoming["fully_returned"]:
                        incoming["fully_returned"] = current.fully_returned
                    proposed = AffiliateOrderSnapshot(tenant=tenant, **incoming)
                    before, after = _order_values(current), _order_values(proposed)
                    if {k: v for k, v in before.items() if k != "source_updated_at"} == {k: v for k, v in after.items() if k != "source_updated_at"}:
                        if not current.source_updated_at or incoming["source_updated_at"] > current.source_updated_at:
                            current.source_updated_at = incoming["source_updated_at"]
                            current.row_hash = affiliate_order_row_hash(_order_values(current))
                            current.save(update_fields=["source_updated_at", "row_hash", "updated_at"])
                        action, saved = "skipped", current
                    else:
                        if current.source_updated_at and current.source_updated_at >= incoming["source_updated_at"]:
                            raise ReadonlyConfigurationError("AFFILIATE_STALE_OBSERVATION")
                        incoming["row_hash"] = affiliate_order_row_hash(after)
                        action, saved = writer._update(tenant, current, incoming)
                else:
                    proposed = AffiliateOrderSnapshot(tenant=tenant, **values)
                    proposed.row_hash = affiliate_order_row_hash(_order_values(proposed))
                    proposed.full_clean()
                    proposed.save()
                    action, saved = "created", proposed
                results.append({"action": action, "idempotency_key": f"{sync_job.pk}:{saved.pk}", "order_snapshot_id": saved.pk})
            return results

    def persist_record(self, sync_job, record):
        raise ReadonlyConfigurationError("AFFILIATE_SINGLE_RECORD_REPLAY_DISABLED")

    def after_page_persist(self, sync_job, page, results):
        self._fence(sync_job)
        plan = self.scope["affiliate_plan"]
        if page["day"] in plan["new_days"]:
            SyncCursor.objects.update_or_create(tenant_id=sync_job.tenant_id, sync_job=sync_job,
                cursor_key="affiliate-next-new-day", defaults={"cursor_value": (_day(page["day"]) + timedelta(days=1)).isoformat()})
        changed = [item["order_snapshot_id"] for item in results if item["action"] in {"created", "updated"}]
        if changed:
            bound = self._require_run()
            run = SyncRun.objects.select_for_update().get(pk=bound.pk, tenant_id=sync_job.tenant_id)
            log = dict(run.masked_log or {})
            progress = dict(log.get("affiliate_refresh") or {})
            previous = progress.get(page["day"], {})
            ids = sorted(set(changed) | set(previous.get("ids", []) if previous.get("pending") else []))
            progress[page["day"]] = {"ids": ids, "pending": True,
                                     "generation": previous.get("generation", 0) + 1}
            run.masked_log = {**log, "affiliate_refresh": progress, "affiliate_refresh_pending": True}
            run.save(update_fields=["masked_log"])
        # This callback runs inside the page transaction. Any error rolls back
        # the facts, audit revisions, progress and default cursor together.

    def finalize_run(self, sync_job):
        self._fence(sync_job)
        plan = self.scope["affiliate_plan"]
        if plan["archive_next"] is not None:
            SyncCursor.objects.update_or_create(tenant_id=sync_job.tenant_id, sync_job=sync_job,
                cursor_key="affiliate-history-day", defaults={"cursor_value": plan["archive_next"]})


def dispatch_pending_affiliate_refreshes(limit=20):
    """Durable post-commit refresh outbox; duplicate deliveries are idempotent."""
    from .tasks import refresh_affiliate_ingestion_day
    submitted = 0
    runs = SyncRun.objects.filter(sync_job__resource_type="affiliate_order",
        masked_log__affiliate_refresh_pending=True).annotate(
            last_dispatch_attempt=Cast(KeyTextTransform("affiliate_dispatch_attempt_at", "masked_log"), CharField()),
        ).order_by(F("last_dispatch_attempt").asc(nulls_first=True), "id")[:max(20, limit * 4)]
    for run in runs.iterator():
        if submitted >= limit:
            break
        # Rotate even throttled/failed runs so older entries cannot starve later ones.
        with transaction.atomic():
            locked = SyncRun.objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
            log = dict(locked.masked_log or {})
            log["affiliate_dispatch_attempt_at"] = timezone.now().isoformat()
            locked.masked_log = log
            locked.save(update_fields=["masked_log"])
            run.masked_log = log
        for day, entry in (run.masked_log or {}).get("affiliate_refresh", {}).items():
            if not entry.get("pending"):
                continue
            last = parse_datetime(str(entry.get("submitted_at") or ""))
            if last and timezone.is_aware(last) and last > timezone.now() - timedelta(minutes=5):
                continue
            # An uncertain broker receipt remains pending. The existing task
            # serializes by tenant and scoped IDs, so re-delivery is safe.
            try:
                refresh_affiliate_ingestion_day.delay(run.pk, day, entry.get("generation", 0))
            except Exception:
                continue
            with transaction.atomic():
                locked = SyncRun.objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
                log = dict(locked.masked_log)
                current = (log.get("affiliate_refresh") or {}).get(day, {})
                if current.get("pending") and current.get("generation", 0) == entry.get("generation", 0):
                    log["affiliate_refresh"][day] = {**current, "submitted_at": timezone.now().isoformat()}
                locked.masked_log = log
                locked.save(update_fields=["masked_log"])
            submitted += 1
            if submitted >= limit:
                break
    return submitted
