import hashlib
import json
import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.commerce.models import InventorySnapshot, RefundReturn, SalesOrder
from apps.commerce.services import upsert_inventory_snapshot
from apps.sales_management.services import upsert_normalized_order, upsert_normalized_refund

from .inventory_snapshot_contract import normalize_inventory_snapshot_record
from .models import MarketplaceStoreAuthorization, PlatformChoices, SyncJob
from .platform_capabilities import supports_resource
from .readonly_clients import (
    JifengWmsReadonlyClient,
    LazadaReadonlyClient,
    ShopeeReadonlyClient,
    TikTokReadonlyClient,
    _draft_epoch_seconds,
    default_sync_scope,
)
from .refund_return_contract import normalize_refund_return_record
from .sales_order_contract import normalize_sales_order_record
from . import tiktok_sales_fields


def _text(*values):
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _shopee_refund_pilot_enabled(config, job, allowlisted_job_ids):
    return (
        config.platform == PlatformChoices.SHOPEE
        and job.resource_type == SyncJob.ResourceType.REFUND_RETURN
        and int(job.pk) in allowlisted_job_ids
    )


def _http_image_url(value):
    """Keep only bounded HTTP(S) URLs in the normalized contract."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or "\\" in value
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
    ):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or "@" in parsed.netloc
    ):
        return ""
    return value


def _canonical_payload_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _amount(*values):
    for value in values:
        if isinstance(value, dict):
            value = value.get("amount", value.get("value"))
        if value not in (None, ""):
            try:
                return str(Decimal(str(value)))
            except (TypeError, ValueError, ArithmeticError):
                pass
    return "0"


def _lazada_amount(value):
    """Lazada reverse-order monetary fields use the currency's minor unit."""
    try:
        return str(Decimal(str(value)) / Decimal("100"))
    except (TypeError, ValueError, ArithmeticError):
        return "0"


def _quantity(*values):
    for value in values:
        if value not in (None, ""):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass
    return 0


def _tiktok_paid_at(value):
    """Only a real provider Unix-second value proves payment time."""
    if type(value) is int:
        seconds = value
    elif isinstance(value, str) and 1 <= len(value) <= 12 and value.isascii() and value.isdecimal():
        seconds = int(value)
    else:
        return None
    if not 946684800 <= seconds <= timezone.now().timestamp() + 86400:
        return None
    return datetime.fromtimestamp(seconds, UTC).isoformat()


def _iso(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, str) and value and not value.isdigit():
        return value
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _local_date_iso(value, timezone_name):
    if isinstance(value, str):
        try:
            local_date = datetime.strptime(value.strip(), "%d %b %Y")
        except ValueError:
            pass
        else:
            return local_date.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(UTC).isoformat()
    return _iso(value)


def _boolean(value):
    if isinstance(value, bool):
        return value
    if value in {1, "1", "true", "TRUE"}:
        return True
    if value in {0, "0", "false", "FALSE"}:
        return False
    return None


def _normalized_order_status(raw_status):
    status = str(raw_status or "").upper()
    if "CANCEL" in status:
        return "cancelled"
    if status == "COMPLETED":
        return "completed"
    if status in {"DELIVERED", "FULFILLED", "READY_TO_SHIP", "SHIPPED", "AWAITING_SHIPMENT", "IN_TRANSIT"}:
        return "fulfilled"
    if status in {"CONFIRMED", "PAID", "UNPAID", "ON_HOLD"}:
        return "confirmed"
    return "pending"


class PlatformAdapter:
    adapter_name = "base"
    execution_mode = "unsupported"

    def bind_run(self, source_run):
        self.source_run = source_run

    def validate_configuration(self, sync_job):
        return None

    def fetch_page(self, sync_job, cursor_value=None):
        raise NotImplementedError

    def normalize_record(self, record):
        raise NotImplementedError

    def validate_record(self, record):
        raise NotImplementedError

    def persist_record(self, sync_job, record):
        raise NotImplementedError

    def get_next_cursor(self, page):
        raise NotImplementedError

    def should_continue(self, page, previous_cursor):
        return False


class MockPlatformAdapter(PlatformAdapter):
    adapter_name = "mock"
    execution_mode = "mock"

    def fetch_page(self, sync_job, cursor_value=None):
        records = sync_job.integration_config.account_alias
        page_records = [
            {"external_id": f"{records}-001", "name": "demo item", "api_secret": "not-a-real-secret"},
            {"external_id": f"{records}-002", "name": "placeholder item", "token": "placeholder-token"},
        ]
        if cursor_value == "done":
            page_records = []
        return {
            "records": page_records,
            "next_cursor": "done",
            "raw_responses": [{"endpoint": "mock://records", "payload": {"records": page_records}}],
        }

    def normalize_record(self, record):
        return {"external_id": record.get("external_id"), "name": record.get("name", "")}

    def validate_record(self, record):
        return bool(record.get("external_id"))

    def persist_record(self, sync_job, record):
        return {"action": "skipped", "idempotency_key": f"{sync_job.id}:{record['external_id']}"}

    def get_next_cursor(self, page):
        return page.get("next_cursor", "")


class SandboxPlaceholderAdapter(MockPlatformAdapter):
    adapter_name = "sandbox-placeholder"
    execution_mode = "sandbox"


class DisabledProductionAdapter(PlatformAdapter):
    adapter_name = "disabled-production"

    def _reject(self):
        raise ValidationError("Production readonly synchronization is not configured for this platform and resource.")

    def validate_configuration(self, sync_job):
        self._reject()

    def fetch_page(self, sync_job, cursor_value=None):
        self._reject()

    def normalize_record(self, record):
        self._reject()

    def validate_record(self, record):
        self._reject()

    def persist_record(self, sync_job, record):
        self._reject()

    def get_next_cursor(self, page):
        self._reject()


class ProductionReadonlyAdapter(PlatformAdapter):
    adapter_name = "production-readonly"
    execution_mode = "live_readonly"

    def __init_subclass__(cls, **kwargs):
        """Apply the same retention guard to every concrete API adapter."""
        super().__init_subclass__(**kwargs)
        from .retention_policy import is_legacy_fact, is_skipped_fact, skipped_fact_marker, skipped_result

        normalize = cls.__dict__.get("normalize_record")
        if normalize is not None:
            @wraps(normalize)
            def normalize_with_retention(self, record, *args, **kw):
                store = getattr(getattr(self, "authorization", None), "store", None)
                if is_legacy_fact(self.resource_type, record, store):
                    run = self.source_run
                    if run is not None:
                        log = dict(run.masked_log or {})
                        log["retention_skipped_count"] = int(log.get("retention_skipped_count") or 0) + 1
                        run.masked_log = log
                    return skipped_fact_marker()
                return normalize(self, record, *args, **kw)
            cls.normalize_record = normalize_with_retention

        validate = cls.__dict__.get("validate_record")
        if validate is not None:
            @wraps(validate)
            def validate_with_retention(self, record, *args, **kw):
                if is_skipped_fact(record):
                    return True
                return validate(self, record, *args, **kw)
            cls.validate_record = validate_with_retention

        persist = cls.__dict__.get("persist_record")
        if persist is not None:
            @wraps(persist)
            def persist_with_retention(self, sync_job, record, *args, **kw):
                if is_skipped_fact(record):
                    return skipped_result(sync_job)
                return persist(self, sync_job, record, *args, **kw)
            cls.persist_record = persist_with_retention

        batch_persist = cls.__dict__.get("persist_records")
        if batch_persist is not None:
            @wraps(batch_persist)
            def persist_batch_with_retention(self, sync_job, records, *args, **kw):
                # An empty complete-day/window still needs its adapter's proof.
                if not records:
                    return batch_persist(self, sync_job, records, *args, **kw)
                results = [skipped_result(sync_job) if is_skipped_fact(record) else None for record in records]
                active = [(index, record) for index, record in enumerate(records) if not is_skipped_fact(record)]
                if active:
                    persisted = list(batch_persist(self, sync_job, [record for _index, record in active], *args, **kw))
                    if len(persisted) != len(active):
                        raise ValidationError("Batch persistence returned an invalid result count.")
                    for (index, _record), result in zip(active, persisted):
                        results[index] = result
                return results
            cls.persist_records = persist_batch_with_retention

    def __init__(self, config, client=None):
        self.config = config
        self.scope = default_sync_scope(config)
        self.authorization = None
        self.warehouse_authorization = None
        self.resource_type = None
        self.client = client
        self.source_run = None

    def _store_authorization(self, sync_job=None):
        if sync_job is not None and sync_job.store_authorization_id:
            authorization = sync_job.store_authorization
            if (
                authorization.tenant_id != sync_job.tenant_id
                or authorization.integration_config_id != self.config.id
                or authorization.platform != self.config.platform
                or authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE
            ):
                raise ValidationError("Sync job store authorization is not active in the configured tenant scope.")
            return authorization
        authorization_id = (self.config.platform_config or {}).get("store_authorization_id")
        queryset = MarketplaceStoreAuthorization.objects.filter(
            tenant=self.config.tenant,
            integration_config=self.config,
            platform=self.config.platform,
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
        ).select_related("store", "store__platform")
        if authorization_id:
            queryset = queryset.filter(pk=authorization_id)
        records = list(queryset[:2])
        if len(records) != 1:
            raise ValidationError("Sync config must resolve exactly one active tenant-owned store authorization.")
        return records[0]

    def validate_configuration(self, sync_job):
        if sync_job.integration_config_id != self.config.id or sync_job.tenant_id != self.config.tenant_id:
            raise ValidationError("Sync job and integration config scope do not match.")
        if self.config.environment not in {"pilot", "production"}:
            raise ValidationError("Production adapter requires pilot or production environment.")
        # Query policy belongs to the concrete sync job.  Keep endpoint and
        # contract settings on the integration config, but allow the job's
        # approved scope to select a full or incremental product pass.
        from .sync_policy import resolve_job_scope
        self.scope = resolve_job_scope(sync_job)
        pilot_job_ids = getattr(settings, "SHOPEE_REFUND_DAILY_PILOT_JOB_IDS", ())
        if _shopee_refund_pilot_enabled(self.config, sync_job, pilot_job_ids):
            # Internal runtime selector only; frozen query bounds are retained.
            self.scope = {**self.scope, "_refund_daily_pilot": True}
        self.resource_type = sync_job.resource_type
        if not supports_resource(self.config.platform, sync_job.resource_type, self.execution_mode):
            raise ValidationError("Platform capability registry does not allow this resource and execution mode.")
        if self.config.platform in {PlatformChoices.LAZADA, PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
            self.authorization = self._store_authorization(sync_job)
        if sync_job.warehouse_authorization_id:
            authorization = sync_job.warehouse_authorization
            if (
                authorization.tenant_id != sync_job.tenant_id
                or authorization.integration_config_id != self.config.id
                or authorization.status != authorization.Status.ACTIVE
            ):
                raise ValidationError("Sync job warehouse authorization is not active in the configured tenant scope.")
            self.warehouse_authorization = authorization
            from .warehouse_credential_service import require_verified_warehouse
            require_verified_warehouse(authorization)
        self._client().preflight()

    def _client(self):
        if self.client is not None:
            self.client.resource_type = self.resource_type
            return self.client
        if self.config.platform == PlatformChoices.LAZADA:
            self.client = LazadaReadonlyClient(self.config, self.authorization)
        elif self.config.platform == PlatformChoices.SHOPEE:
            self.client = ShopeeReadonlyClient(self.config, self.authorization)
        elif self.config.platform == PlatformChoices.TIKTOK:
            self.client = TikTokReadonlyClient(self.config, self.authorization)
        elif self.config.platform == PlatformChoices.JIFENG_WMS:
            self.client = JifengWmsReadonlyClient(self.config, self.warehouse_authorization)
        else:
            raise ValidationError("Unsupported production readonly platform.")
        self.client.resource_type = self.resource_type
        return self.client

    def fetch_page(self, sync_job, cursor_value=None):
        client = self._client()
        if sync_job.resource_type == SyncJob.ResourceType.PLATFORM_PRODUCT:
            return client.fetch_products(cursor_value, self.scope)
        if sync_job.resource_type == SyncJob.ResourceType.SALES_ORDER:
            return client.fetch_orders(cursor_value, self.scope)
        if sync_job.resource_type == SyncJob.ResourceType.REFUND_RETURN:
            return client.fetch_returns(cursor_value, self.scope)
        if sync_job.resource_type == SyncJob.ResourceType.INVENTORY_SNAPSHOT:
            return client.fetch_inventory(cursor_value, self.scope)
        if sync_job.resource_type == SyncJob.ResourceType.SETTLEMENT_BILL:
            return client.fetch_finance_transactions(cursor_value, self.scope)
        raise ValidationError("The selected resource is not supported by the production readonly adapter.")

    def get_next_cursor(self, page):
        return str(page.get("next_cursor") or "")

    def should_continue(self, page, previous_cursor):
        next_cursor = self.get_next_cursor(page)
        return bool(next_cursor and next_cursor != str(previous_cursor or ""))

    def validate_record(self, record):
        return isinstance(record, dict)

    def _require_run(self):
        if self.source_run is None:
            raise ValidationError("Production adapter is not bound to a SyncRun.")
        return self.source_run


class MarketplaceProductAdapter(ProductionReadonlyAdapter):
    """Normalize authorized-shop product snapshots without enabling writes."""

    def fetch_page(self, sync_job, cursor_value=None):
        if self.config.platform != PlatformChoices.SHOPEE:
            return super().fetch_page(sync_job, cursor_value)
        from .order_product_gaps import (
            CURSOR_PREFIX, gap_candidates, gap_cursor, gap_summary,
            parse_gap_cursor, product_backfill_mode, source_watermark,
        )
        mode = product_backfill_mode(self.config, sync_job.resource_type, self.scope)
        cursor_value = str(cursor_value or "")
        targeted = cursor_value.startswith(CURSOR_PREFIX) or mode == "order_missing_only"
        if targeted:
            if cursor_value:
                watermark, last = parse_gap_cursor(cursor_value)
                initial = False
            else:
                watermark, last, initial = source_watermark(sync_job), "", True
            ids, more = gap_candidates(sync_job, watermark, last, limit=self.scope["page_size"])
            page = self._client().fetch_products_by_ids(ids) if ids else {
                "records": [], "raw_responses": [], "unavailable_item_ids": [],
            }
            page["records"] = [{**record, "order_identity_backfill": True} for record in page["records"]]
            page["next_cursor"] = gap_cursor(watermark, ids[-1]) if ids and more else ""
            page["order_product_reconciliation"] = {
                "watermark": watermark, "attempted_products": len(ids),
                "unavailable_products": len(page.get("unavailable_item_ids", [])),
                **({"before": gap_summary(sync_job, watermark)} if initial else {}),
            }
            return page
        page = super().fetch_page(sync_job, cursor_value)
        if not page.get("next_cursor") and mode == "catalog_and_order_missing":
            watermark = source_watermark(sync_job)
            page["order_product_reconciliation"] = {
                "watermark": watermark, "catalogue_complete": True,
            }
        return page

    def after_page_persist(self, sync_job, page, results):
        progress = page.get("order_product_reconciliation")
        if not progress:
            return
        run = self._require_run()
        prior = dict((run.masked_log or {}).get("order_product_reconciliation") or {})
        if progress.get("catalogue_complete"):
            from .order_product_gaps import gap_cursor, gap_summary
            # Run in the page-write transaction: the final normal page is
            # already persisted, so both before and target selection reflect it.
            progress["before"] = gap_summary(sync_job, progress["watermark"])
            before = progress["before"]
            # These counts exclude invalid identities and parent conflicts;
            # no second full-shop aggregate is needed merely to test existence.
            has_targets = bool(before["missing_product_ids"] or before["missing_variant_pairs"])
            page["next_cursor"] = gap_cursor(progress["watermark"]) if has_targets else ""
        prior.update({key: progress[key] for key in ("watermark", "before") if key in progress})
        for key in ("attempted_products", "unavailable_products"):
            prior[key] = int(prior.get(key, 0)) + int(progress.get(key, 0))
        prior["identity_conflicts"] = int(prior.get("identity_conflicts", 0)) + sum(
            result.get("result_code") == "ORDER_PRODUCT_IDENTITY_CONFLICT" for result in results
        )
        prior["phase"] = "order_missing" if str(page.get("next_cursor") or "").startswith("order-gap:") else "validation"
        run.masked_log = {**(run.masked_log or {}), "order_product_reconciliation": prior}
        run.save(update_fields=["masked_log"])

    def finalize_run(self, sync_job):
        progress = dict((self._require_run().masked_log or {}).get("order_product_reconciliation") or {})
        if not progress:
            return
        from .order_product_gaps import gap_summary
        progress.update({
            "after": gap_summary(sync_job, progress["watermark"]),
            "phase": "complete", "coverage_certified": False,
            "notice": "本次只读采集已结束，不代表所有历史商品均可从平台找回。剩余差集、平台未返回和身份冲突需继续核查。",
        })
        run = self._require_run()
        run.masked_log = {**(run.masked_log or {}), "order_product_reconciliation": progress}
        run.save(update_fields=["masked_log"])

    def normalize_record(self, record):
        if not isinstance(record, dict):
            return {}
        store = self.authorization.store
        platform_sku = _text(record.get("platform_sku"), record.get("seller_sku"))
        status_only = record.get("status_only", record.get("partial_snapshot", False))
        if isinstance(status_only, str):
            status_only = status_only.strip().casefold() in {"1", "true", "yes", "y", "status_only"}
        else:
            status_only = bool(status_only)
        normalized = {
            "contract_version": "platform_product.v1",
            "platform": str(self.config.platform),
            "store_id": str(store.id),
            "platform_product_id": _text(record.get("platform_product_id")),
            "platform_variant_id": _text(record.get("platform_variant_id")),
            "platform_sku": platform_sku,
            "seller_sku": platform_sku,
            # Platform/seller SKU is a provider-side identifier, not proof of
            # an internal legacy SKU.  The SKU ingestion service resolves new
            # and old codes independently and promotes only a verified match.
            "source_old_sku_code": _text(record.get("source_old_sku_code")),
            "new_sku_code": _text(record.get("new_sku_code")),
            "title": _text(record.get("title")),
            "variant": _text(record.get("variant")),
            "category_l1": _text(record.get("category_l1")),
            "category_l2": _text(record.get("category_l2")),
            "category_l3": _text(record.get("category_l3")),
            "sales_status": _text(record.get("sales_status")),
            "platform_created_at": _iso(record.get("platform_created_at")) or None,
            "platform_updated_at": (datetime.fromtimestamp(_draft_epoch_seconds(record.get("platform_updated_at")), UTC).isoformat()
                                    if record.get("draft_without_skus") is True
                                    else _iso(record.get("platform_updated_at")) or None),
            "source": "api",
            "order_identity_backfill": record.get("order_identity_backfill") is True,
            # Partial status snapshots are an explicit ingestion contract:
            # only sales_status/platform_updated_at may change an existing
            # exact variant; no title/SKU/detail is inferred from the search
            # summary.  The ingestion service audits unknown variants.
            "status_only": status_only,
            "partial_snapshot": status_only,
            "snapshot_kind": ("draft_observation" if record.get("draft_without_skus") is True
                              else "status_only" if status_only else "complete"),
            "draft_without_skus": record.get("draft_without_skus") is True,
        }
        if record.get("image_url") == "":
            normalized["image_url"] = ""
        else:
            image_url = _http_image_url(record.get("image_url"))
            if image_url:
                normalized["image_url"] = image_url
        if self.config.platform == PlatformChoices.TIKTOK:
            for field in ("title", "variant", "category_l1", "category_l2", "category_l3"):
                if field not in record:
                    normalized.pop(field, None)
        return normalized

    def validate_record(self, record):
        if not isinstance(record, dict) or not record.get("store_id") or not record.get("platform_product_id"):
            return False
        if record.get("draft_without_skus"):
            try:
                updated_at = datetime.fromisoformat(record.get("platform_updated_at"))
            except (TypeError, ValueError):
                return False
            return (self.config.platform == PlatformChoices.TIKTOK and record.get("sales_status") == "DRAFT"
                    and not record.get("platform_variant_id") and timezone.is_aware(updated_at)
                    and updated_at > datetime(1970, 1, 1, tzinfo=UTC)
                    and not record.get("status_only"))
        if record.get("status_only"):
            # A provider tombstone may contain no SKU list.  It is still a
            # valid page record: ingestion records an auditable skip rather
            # than manufacturing a variant identity.
            return bool(record.get("sales_status") and record.get("platform_updated_at"))
        return bool(record.get("platform_variant_id"))

    def persist_record(self, sync_job, record):
        run = self._require_run()
        if record.get("draft_without_skus"):
            if not self.validate_record(record):
                raise ValidationError("Invalid no-SKU draft observation.")
            from .models import IntegrationAuditLog
            actor = sync_job.integration_config.created_by
            if actor.tenant_id != sync_job.tenant_id:
                raise ValidationError("Draft observation actor must belong to the job tenant.")
            IntegrationAuditLog.objects.create(tenant_id=sync_job.tenant_id,
                integration_config_id=sync_job.integration_config_id,
                store_authorization_id=sync_job.store_authorization_id,
                actor_id=actor.pk, action="platform_product_draft_without_skus", result=IntegrationAuditLog.Result.SUCCESS,
                masked_detail={"source_run_id": run.id, "sync_job_id": sync_job.pk,
                    "platform_product_id": record["platform_product_id"], "reason": "draft_without_skus",
                    "outcome": "skipped", "observed_updated_at": record["platform_updated_at"], "canonical_variants_changed": 0})
            return {"action": "skipped", "result_code": "DRAFT_WITHOUT_SKUS",
                    "idempotency_key": f"{sync_job.pk}:draft:{record['platform_product_id']}:{record['platform_updated_at']}"}
        # Kept as a lazy import so the read adapter remains importable while
        # the listing ingestion module evolves independently.  The ingestion
        # function is the sole write boundary for PlatformProductDetail.
        from apps.integrations.platform_product_ingestion import upsert_platform_product

        payload = dict(record)
        payload["source_run_id"] = run.id
        result = upsert_platform_product(sync_job=sync_job, normalized_record=payload)
        if not isinstance(result, dict):
            raise ValidationError("Platform product ingestion returned an invalid result.")
        action = result.get("action") or "skipped"
        variant_key = record.get("platform_variant_id") or (
            f"status:{record.get('platform_product_id')}:{record.get('sales_status')}:{record.get('platform_updated_at')}"
            if record.get("status_only")
            else ""
        )
        return {
            **result,
            "action": action,
            "idempotency_key": result.get("idempotency_key") or f"{sync_job.id}:{variant_key}",
        }


class MarketplaceOrderAdapter(ProductionReadonlyAdapter):
    def normalize_record(self, record):
        store = self.authorization.store
        if self.config.platform == PlatformChoices.SHOPEE:
            items = record.get("item_list") if isinstance(record.get("item_list"), list) else []
            raw_status = _text(record.get("order_status"), "UNKNOWN")
            payload = {
                "contract_version": "sales_order.v1",
                "store_id": str(store.id),
                "source_order_id": _text(record.get("order_sn")),
                "ordered_at": _iso(record.get("create_time")),
                "source_updated_at": _iso(record.get("update_time")),
                "currency": _text(record.get("currency"), store.currency).upper(),
                "gross_amount": _amount(record.get("total_amount")),
                "shipping_amount": _amount(record.get("estimated_shipping_fee"), record.get("actual_shipping_fee")),
                "order_status": _normalized_order_status(raw_status),
                "region": self.authorization.region,
                "lines": [
                    {
                        "source_line_id": f"{record.get('order_sn')}:{item.get('item_id')}:{item.get('model_id')}:{index}",
                        "sku": _text(item.get("model_sku"), item.get("item_sku"), item.get("model_id"), item.get("item_id")),
                        "product_name": _text(item.get("item_name")),
                        "quantity": _quantity(item.get("model_quantity_purchased"), 1),
                        "unit_price": _amount(item.get("model_discounted_price"), item.get("model_original_price")),
                        "platform_product_id": _text(item.get("item_id")),
                        "platform_variant_id": _text(item.get("model_id")),
                        "raw_line_status": raw_status,
                    }
                    for index, item in enumerate(items, start=1)
                    if isinstance(item, dict)
                ],
            }
        else:
            payment = record.get("payment") if isinstance(record.get("payment"), dict) else {}
            items = record.get("line_items") if isinstance(record.get("line_items"), list) else []
            raw_status = _text(record.get("status"), "UNKNOWN")
            payload = {
                "contract_version": "sales_order.v1",
                "store_id": str(store.id),
                "source_order_id": _text(record.get("id")),
                "ordered_at": _iso(record.get("create_time")),
                "source_updated_at": _iso(record.get("update_time")),
                "currency": _text(payment.get("currency"), store.currency).upper(),
                "gross_amount": _amount(payment.get("total_amount")),
                "shipping_amount": _amount(payment.get("shipping_fee")),
                "order_status": _normalized_order_status(raw_status),
                "region": self.authorization.region,
                "lines": [
                    {
                        "source_line_id": _text(item.get("id"), f"{record.get('id')}:{index}"),
                        "sku": _text(item.get("seller_sku"), item.get("sku_id")),
                        "product_name": _text(item.get("product_name")),
                        "quantity": _quantity(item.get("quantity"), 1),
                        "unit_price": _amount(item.get("sale_price"), item.get("original_price")),
                        "platform_product_id": _text(item.get("product_id")),
                        "platform_variant_id": _text(item.get("sku_id")),
                        "raw_line_status": _text(item.get("display_status"), raw_status),
                    }
                    for index, item in enumerate(items, start=1)
                    if isinstance(item, dict)
                ],
            }
        if self.config.platform == PlatformChoices.TIKTOK:
            payload.update(tiktok_sales_fields.order_fields(record, store))
            for line, item in zip(payload["lines"], (item for item in items if isinstance(item, dict))):
                line.update(tiktok_sales_fields.order_line_fields(item, payload["currency"]))
            paid_at = _tiktok_paid_at(record.get("paid_time"))
            if paid_at is not None:
                payload["paid_at_utc"] = paid_at
        return normalize_sales_order_record(self.config.platform, payload)

    def persist_record(self, sync_job, record):
        run = self._require_run()
        external_id = record["source_order_id"]
        existing = SalesOrder.objects.filter(
            tenant=sync_job.tenant, store_id=record["store_id"], external_order_id=external_id
        ).first()
        before_hash = existing.payload_hash if existing else ""
        saved = upsert_normalized_order(tenant=sync_job.tenant, payload=record, source_run=run)
        action = "created" if existing is None else "skipped" if before_hash == saved.payload_hash else "updated"
        return {"action": action, "idempotency_key": f"{sync_job.id}:{external_id}"}

    def persist_records(self, sync_job, records):
        run = self._require_run()
        keys = [(str(record["store_id"]), record["source_order_id"]) for record in records]
        existing_hashes = {
            (str(store_id), external_id): payload_hash
            for store_id, external_id, payload_hash in SalesOrder.objects.filter(
                tenant=sync_job.tenant,
                store_id__in={store_id for store_id, _external_id in keys},
                external_order_id__in={external_id for _store_id, external_id in keys},
            ).values_list("store_id", "external_order_id", "payload_hash")
        }
        results = []
        for record, key in zip(records, keys):
            payload_hash = str(record.get("payload_hash") or _canonical_payload_hash(record))
            if existing_hashes.get(key) == payload_hash:
                results.append({"action": "skipped", "idempotency_key": f"{sync_job.id}:{key[1]}"})
                continue
            before_hash = existing_hashes.get(key)
            saved = upsert_normalized_order(tenant=sync_job.tenant, payload=record, source_run=run)
            existing_hashes[key] = saved.payload_hash
            action = "created" if before_hash is None else "skipped" if before_hash == saved.payload_hash else "updated"
            results.append({"action": action, "idempotency_key": f"{sync_job.id}:{key[1]}"})
        return results


class LazadaOrderAdapter(MarketplaceOrderAdapter):
    def normalize_record(self, record):
        store = self.authorization.store
        statuses = record.get("statuses")
        raw_status = _text(statuses[-1] if isinstance(statuses, list) and statuses else statuses, record.get("status"), "UNKNOWN")
        items = record.get("order_items") if isinstance(record.get("order_items"), list) else []
        payload = {
            "contract_version": "sales_order.v1",
            "store_id": str(store.id),
            "source_order_id": _text(record.get("order_id")),
            "ordered_at": _iso(record.get("created_at")),
            "source_updated_at": _iso(record.get("updated_at") or record.get("created_at")),
            "currency": _text(record.get("currency"), store.currency).upper(),
            "gross_amount": _amount(record.get("price"), record.get("total_amount")),
            "shipping_amount": _amount(record.get("shipping_fee")),
            "order_status": _normalized_order_status(raw_status),
            "region": self.authorization.region,
            "lines": [
                {
                    "source_line_id": _text(item.get("order_item_id"), f"{record.get('order_id')}:{index}"),
                    "sku": _text(
                        item.get("shop_sku"),
                        item.get("sku"),
                        item.get("seller_sku"),
                        item.get("sku_id"),
                        item.get("product_id"),
                        item.get("item_id"),
                    ),
                    "product_name": _text(item.get("name"), item.get("item_name")),
                    "quantity": _quantity(item.get("quantity"), 1),
                    "unit_price": _amount(item.get("item_price"), item.get("paid_price")),
                    "platform_product_id": _text(item.get("product_id"), item.get("item_id")),
                    "platform_variant_id": _text(item.get("sku_id")),
                    "raw_line_status": _text(item.get("status"), raw_status),
                }
                for index, item in enumerate(items, start=1)
                if isinstance(item, dict)
            ],
        }
        return normalize_sales_order_record(PlatformChoices.LAZADA, payload)


class MarketplaceFinanceTransactionAdapter(ProductionReadonlyAdapter):
    @staticmethod
    def _source_key(record):
        explicit = _text(record.get("source_key"))
        if explicit:
            return explicit
        transaction_id = _text(record.get("transaction_id"))
        if transaction_id:
            return transaction_id
        business_key = {
            "transaction": _text(record.get("transaction_number")),
            "reference": _text(record.get("reference")),
            "statement": _text(record.get("statement_id"), record.get("statement")),
            "order": _text(record.get("order_no"), record.get("order_id")),
            "item": _text(
                record.get("order_item_no"),
                record.get("orderItem_no"),
                record.get("order_item_id"),
            ),
            "sku": _text(record.get("seller_sku"), record.get("lazada_sku"), record.get("sku")),
            "fee": _text(record.get("fee_name"), record.get("transaction_type"), record.get("fee_type")),
            "amount": _amount(record.get("amount"), record.get("transaction_amount"), record.get("fee_amount")),
            "currency": _text(record.get("currency")),
            "occurred_at": _text(record.get("transaction_date"), record.get("created_at"), record.get("occurred_at")),
        }
        canonical = json.dumps(business_key, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def normalize_record(self, record):
        from apps.finance.contracts import normalize_finance_transaction_record

        store = self.authorization.store
        currency = _text(record.get("currency"), store.currency).upper()
        raw_amount = _amount(record.get("amount"), record.get("transaction_amount"), record.get("fee_amount"))
        if self.config.platform == PlatformChoices.TIKTOK:
            from .tiktok_finance_fields import amount

            currency = _text(record.get("currency"))
            raw_amount = amount(record.get("amount", record.get("transaction_amount", record.get("fee_amount"))), currency)
        occurred_at = (
            _local_date_iso(
                record.get("transaction_date") or record.get("created_at") or record.get("occurred_at"),
                store.timezone,
            )
            if self.config.platform == PlatformChoices.LAZADA
            else _iso(record.get("occurred_at") or record.get("created_at") or record.get("transaction_time"))
        )
        return normalize_finance_transaction_record(
            {
                "contract_version": "finance_transaction.v1",
                "source_key": self._source_key(record),
                "external_transaction_id": _text(
                    record.get("transaction_id"),
                    record.get("transaction_number"),
                    record.get("statement_id"),
                ),
                "external_order_id": _text(record.get("order_no"), record.get("order_id")),
                "external_order_item_id": _text(
                    record.get("order_item_no"),
                    record.get("orderItem_no"),
                    record.get("order_item_id"),
                ),
                "seller_sku": _text(record.get("seller_sku"), record.get("sku")),
                "platform_variant_id": _text(
                    record.get("sku_id"),
                    record.get("platform_variant_id"),
                    record.get("lazada_sku"),
                ),
                "raw_fee_name": _text(
                    record.get("fee_name"),
                    record.get("transaction_type"),
                    record.get("fee_type"),
                    record.get("description"),
                    "UNKNOWN",
                ),
                "raw_amount": raw_amount,
                "currency": currency,
                "occurred_at_utc": occurred_at,
            }
        )

    def persist_record(self, sync_job, record):
        from apps.finance.ingestion import upsert_finance_transaction
        from apps.finance.models import PlatformFinanceTransaction

        run = self._require_run()
        result = upsert_finance_transaction(
            tenant=sync_job.tenant,
            store=self.authorization.store,
            authorization=self.authorization,
            source_run=run,
            raw_envelope=run.raw_envelopes.order_by("-sequence").first(),
            payload=record,
        )
        masked_log = dict(run.masked_log or {})
        if result.instance.match_status != PlatformFinanceTransaction.MatchStatus.MATCHED:
            masked_log["finance_unmatched_count"] = int(masked_log.get("finance_unmatched_count") or 0) + 1
        if result.instance.fee_code == "OTHER":
            masked_log["finance_unknown_fee_count"] = int(masked_log.get("finance_unknown_fee_count") or 0) + 1
            masked_log["finance_data_quality"] = "partial"
        run.masked_log = masked_log
        if self.config.platform == PlatformChoices.LAZADA:
            affected_dates = getattr(self, "_finance_wide_dates", set())
            affected_dates.add(result.instance.business_date)
            self._finance_wide_dates = affected_dates
        return {"action": result.action, "idempotency_key": f"{sync_job.id}:{record['source_key']}"}

    def finalize_run(self, sync_job):
        if self.config.platform != PlatformChoices.LAZADA:
            return
        from apps.finance.wide_service import rebuild_lazada_finance_wide

        dates = getattr(self, "_finance_wide_dates", set())
        if not dates:
            return
        rebuild_lazada_finance_wide(
            tenant=sync_job.tenant,
            store=self.authorization.store,
            business_dates=dates,
        )


LazadaFinanceTransactionAdapter = MarketplaceFinanceTransactionAdapter


class MarketplaceRefundAdapter(ProductionReadonlyAdapter):
    def normalize_record(self, record):
        store = self.authorization.store
        if self.config.platform == PlatformChoices.SHOPEE:
            return_id = _text(record.get("return_sn"), record.get("return_id"))
            order_id = _text(record.get("order_sn"), record.get("order_id"))
            case_type = _text(record.get("return_type"), record.get("solution"), "refund")
            raw_status = _text(record.get("status"), record.get("return_status"), "unknown")
            refund = record.get("refund_amount") if isinstance(record.get("refund_amount"), dict) else {}
            items = next((record.get(name) for name in ("item", "item_list", "return_item_list", "return_items") if isinstance(record.get(name), list)), [])
            currency = _text(record.get("currency"), refund.get("currency"), store.currency).upper()
            payload = {
                "contract_version": "refund_return.v1",
                "store_id": str(store.id),
                "external_return_id": return_id,
                "external_refund_id": _text(record.get("refund_id")),
                "external_order_id": order_id,
                "case_type": case_type,
                "raw_status": raw_status,
                "normalized_status": raw_status.lower(),
                "arbitration_status": _text(record.get("negotiation_status"), record.get("arbitration_status")),
                "reason_code": _text(record.get("reason"), record.get("return_reason")),
                "requested_at_utc": _iso(record.get("create_time")),
                "updated_at_utc": _iso(record.get("update_time")),
                "completed_at_utc": _iso(record.get("complete_time") or record.get("refund_time")) or None,
                "currency": currency,
                "refund_amount": _amount(record.get("refund_amount"), record.get("refund_total")),
                "refund_subtotal": _amount(refund.get("refund_subtotal"), record.get("refund_subtotal")),
                "refund_shipping_fee": _amount(refund.get("refund_shipping_fee"), record.get("refund_shipping_fee")),
                "refund_tax": _amount(refund.get("refund_tax"), record.get("refund_tax")),
                "requires_physical_return": "RETURN" in case_type.upper(),
                "is_partial_quantity_return": _boolean(record.get("is_partial_quantity_return")),
                "is_refund_amount_adjusted": _boolean(record.get("is_refund_amount_adjusted")),
                "items": [self._shopee_refund_item(item, return_id, index, currency) for index, item in enumerate(items, start=1) if isinstance(item, dict)],
            }
        elif self.config.platform == PlatformChoices.LAZADA:
            lines = [item for item in record.get("reverse_order_lines", []) if isinstance(item, dict)]
            latest_line = max(
                lines,
                key=lambda item: int(item.get("return_order_line_gmt_modified") or 0),
                default={},
            )
            timestamps = [
                int(item.get("return_order_line_gmt_create") or 0)
                for item in lines
                if item.get("return_order_line_gmt_create")
            ]
            updated_timestamps = [
                int(item.get("return_order_line_gmt_modified") or 0)
                for item in lines
                if item.get("return_order_line_gmt_modified")
            ]
            return_id = _text(record.get("reverse_order_id"))
            case_type = _text(record.get("request_type"), "refund")
            raw_status = _text(latest_line.get("reverse_status"), "unknown")
            currency = _text(store.currency).upper()
            refund_total = sum(
                (Decimal(_lazada_amount(item.get("refund_amount"))) for item in lines),
                Decimal("0"),
            )
            payload = {
                "contract_version": "refund_return.v1",
                "store_id": str(store.id),
                "external_return_id": return_id,
                "external_refund_id": return_id if "REFUND" in case_type.upper() else "",
                "external_order_id": _text(record.get("trade_order_id")),
                "case_type": case_type,
                "raw_status": raw_status,
                "normalized_status": raw_status.lower(),
                "arbitration_status": "disputed" if any(item.get("is_dispute") for item in lines) else "",
                "reason_code": _text(latest_line.get("reason_code"), latest_line.get("reason_text")),
                "requested_at_utc": _iso(min(timestamps) if timestamps else ""),
                "updated_at_utc": _iso(max(updated_timestamps) if updated_timestamps else ""),
                "completed_at_utc": None,
                "currency": currency,
                "refund_amount": str(refund_total),
                "refund_subtotal": str(refund_total),
                "refund_shipping_fee": "0",
                "refund_tax": "0",
                "requires_physical_return": case_type.upper() == "RETURN",
                "is_partial_quantity_return": None,
                "is_refund_amount_adjusted": None,
                "items": [
                    self._lazada_refund_item(item, return_id, index, currency)
                    for index, item in enumerate(lines, start=1)
                ],
            }
        else:
            return_id = _text(record.get("return_id"), record.get("reverse_order_id"), record.get("aftersales_id"))
            refund = record.get("refund_amount") if isinstance(record.get("refund_amount"), dict) else {}
            items = next((record.get(name) for name in ("return_line_items", "return_items", "line_items", "order_line_list") if isinstance(record.get(name), list)), [])
            case_type = _text(record.get("return_type"), record.get("aftersales_type"), "refund")
            raw_status = _text(record.get("return_status"), record.get("status"), "unknown")
            currency = _text(refund.get("currency"), record.get("currency"), store.currency).upper()
            payload = {
                "contract_version": "refund_return.v1",
                "store_id": str(store.id),
                "external_return_id": return_id,
                "external_refund_id": _text(record.get("refund_id")),
                "external_order_id": _text(record.get("order_id")),
                "case_type": case_type,
                "raw_status": raw_status,
                "normalized_status": raw_status.lower(),
                "arbitration_status": _text(record.get("arbitration_status")),
                "reason_code": _text(record.get("return_reason"), record.get("reason_code")),
                "requested_at_utc": _iso(record.get("create_time")),
                "updated_at_utc": _iso(record.get("update_time")),
                "completed_at_utc": _iso(record.get("complete_time") or record.get("refund_time")) or None,
                "currency": currency,
                "refund_amount": _amount(refund.get("refund_total"), record.get("refund_total")),
                "refund_subtotal": _amount(refund.get("refund_subtotal")),
                "refund_shipping_fee": _amount(refund.get("refund_shipping_fee")),
                "refund_tax": _amount(refund.get("refund_tax")),
                "requires_physical_return": None if not case_type else "RETURN" in case_type.upper(),
                "is_partial_quantity_return": None,
                "is_refund_amount_adjusted": None,
                "items": [self._tiktok_refund_item(item, return_id, index, currency) for index, item in enumerate(items, start=1) if isinstance(item, dict)],
            }
            payload["normalized_status"] = tiktok_sales_fields.refund_status(raw_status)
            payload["refund_amount"] = tiktok_sales_fields.refund_money(refund, currency)
            for field in ("refund_subtotal", "refund_shipping_fee", "refund_tax"):
                payload[field] = tiktok_sales_fields.money(refund.get(field))
        return normalize_refund_return_record(self.config.platform, payload)

    @staticmethod
    def _shopee_refund_item(item, return_id, index, currency):
        return {
            "external_return_item_id": _text(item.get("return_item_id"), item.get("line_id"), f"{return_id}:{index}"),
            "external_order_item_id": _text(item.get("order_item_id")),
            "platform_product_id": _text(item.get("item_id")),
            "platform_variant_id": _text(item.get("model_id")),
            "seller_sku": _text(item.get("model_sku"), item.get("item_sku")),
            "item_name_snapshot": _text(item.get("item_name"), item.get("name")),
            "quantity": _quantity(item.get("amount"), item.get("quantity"), 1),
            "currency": currency,
            "refund_amount": _amount(item.get("refund_amount"), item.get("amount_refunded")),
        }

    @staticmethod
    def _lazada_refund_item(item, return_id, index, currency):
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        return {
            "external_return_item_id": _text(
                item.get("reverse_order_line_id"),
                f"{return_id}:{index}",
            ),
            "external_order_item_id": _text(item.get("trade_order_line_id")),
            "platform_product_id": _text(product.get("product_id")),
            "platform_variant_id": _text(item.get("platform_sku_id")),
            "seller_sku": _text(product.get("product_sku"), item.get("seller_sku_id")),
            "item_name_snapshot": "",
            "quantity": 1,
            "currency": currency,
            "refund_amount": _lazada_amount(item.get("refund_amount")),
        }

    @staticmethod
    def _tiktok_refund_item(item, return_id, index, currency):
        return {
            "external_return_item_id": _text(item.get("return_line_item_id"), item.get("id"), f"{return_id}:{index}"),
            "external_order_item_id": _text(item.get("order_line_item_id"), item.get("sub_order_line_item_id")),
            "platform_product_id": _text(item.get("product_id")),
            "platform_variant_id": _text(item.get("sku_id")),
            "seller_sku": _text(item.get("seller_sku")),
            "item_name_snapshot": _text(item.get("product_name")),
            "quantity": _quantity(item.get("quantity"), item.get("return_quantity"), 1),
            "currency": currency,
            "refund_amount": tiktok_sales_fields.refund_money(item.get("refund_amount"), currency),
        }

    def persist_record(self, sync_job, record):
        run = self._require_run()
        existing = RefundReturn.objects.filter(
            tenant=sync_job.tenant, store_id=record["store_id"], external_return_id=record["external_return_id"]
        ).first()
        before_hash = existing.payload_hash if existing else ""
        saved = upsert_normalized_refund(tenant=sync_job.tenant, payload=record, source_run=run)
        action = "created" if existing is None else "skipped" if before_hash == saved.payload_hash else "updated"
        return {"action": action, "idempotency_key": f"{sync_job.id}:{record['external_return_id']}"}

    def persist_records(self, sync_job, records):
        run = self._require_run()
        keys = [(str(record["store_id"]), record["external_return_id"]) for record in records]
        existing_hashes = {
            (str(store_id), external_id): payload_hash
            for store_id, external_id, payload_hash in RefundReturn.objects.filter(
                tenant=sync_job.tenant,
                store_id__in={store_id for store_id, _external_id in keys},
                external_return_id__in={external_id for _store_id, external_id in keys},
            ).values_list("store_id", "external_return_id", "payload_hash")
        }
        results = []
        for record, key in zip(records, keys):
            payload_hash = str(record.get("payload_hash") or _canonical_payload_hash(record))
            if existing_hashes.get(key) == payload_hash:
                results.append({"action": "skipped", "idempotency_key": f"{sync_job.id}:{key[1]}"})
                continue
            before_hash = existing_hashes.get(key)
            saved = upsert_normalized_refund(tenant=sync_job.tenant, payload=record, source_run=run)
            existing_hashes[key] = saved.payload_hash
            action = "created" if before_hash is None else "skipped" if before_hash == saved.payload_hash else "updated"
            results.append({"action": action, "idempotency_key": f"{sync_job.id}:{key[1]}"})
        return results


class JifengInventoryAdapter(ProductionReadonlyAdapter):
    def normalize_record(self, record):
        config = self.config.platform_config or {}
        warehouse_authorization = self.warehouse_authorization
        warehouse = getattr(warehouse_authorization, "warehouse", None)
        quantity_aliases = {
            'on_hand_qty': ('totalNum', 'total', 'quantity'),
            'available_qty': ('availableNum', 'available', 'availableQuantity'),
            'reserved_qty': ('lockedNum', 'locked', 'lockedQuantity'),
            'in_transit_qty': ('onTheWayNum', 'inTransit', 'onWay'),
            'pending_putaway_qty': ('pendingListingNum', 'pendingPutaway'),
            'defective_qty': ('nonGoodNum', 'nonGood', 'defectiveQuantity'),
        }
        return normalize_inventory_snapshot_record(
            {
                "contract_version": "inventory_snapshot.v1",
                'provided_quantity_fields': [name for name, aliases in quantity_aliases.items()
                    if any(record.get(key) not in (None, '') for key in aliases)],
                # The provider-issued code is used only in the upstream
                # request.  Normalized facts must retain the tenant-owned
                # warehouse archive selected by the sync job.
                "site_code": _text(
                    getattr(warehouse, "country_code", ""),
                    config.get("site_code"),
                ).upper(),
                "warehouse_id": str(
                    getattr(warehouse_authorization, "warehouse_id", None)
                    or config.get("warehouse_id")
                    or ""
                ),
                "source_sku": _text(record.get("sku"), record.get("skuCode"), record.get("code"), record.get("sellerSku")),
                "seller_sku": _text(record.get("sellerSku"), record.get("sku")),
                "on_hand_qty": _quantity(record.get("totalNum"), record.get("total"), record.get("quantity")),
                "available_qty": _quantity(record.get("availableNum"), record.get("available"), record.get("availableQuantity")),
                "reserved_qty": _quantity(record.get("lockedNum"), record.get("locked"), record.get("lockedQuantity")),
                "in_transit_qty": _quantity(record.get("onTheWayNum"), record.get("inTransit"), record.get("onWay")),
                "pending_putaway_qty": _quantity(record.get("pendingListingNum"), record.get("pendingPutaway")),
                "defective_qty": _quantity(record.get("nonGoodNum"), record.get("nonGood"), record.get("defectiveQuantity")),
                "snapshot_at_utc": _text(record.get("_snapshot_at_utc"), timezone.now().isoformat()),
            }
        )

    def persist_record(self, sync_job, record):
        run = self._require_run()
        existing = InventorySnapshot.objects.filter(
            tenant=sync_job.tenant,
            warehouse_id=record["warehouse_id"],
            source_sku=record["source_sku"],
            snapshot_at_utc=record["snapshot_at_utc"],
        ).first()
        before_hash = existing.payload_hash if existing else ""
        saved = upsert_inventory_snapshot(tenant=sync_job.tenant, payload=record, source_run=run)
        unchanged = existing is not None and before_hash == saved.payload_hash and existing.internal_sku_id == saved.internal_sku_id
        action = "created" if existing is None else "skipped" if unchanged else "updated"
        return {"action": action, "idempotency_key": f"{sync_job.id}:{saved.id}"}

    def persist_records(self, sync_job, records):
        from apps.commerce.services import bulk_upsert_inventory_snapshots

        results = bulk_upsert_inventory_snapshots(
            tenant=sync_job.tenant,
            payloads=records,
            source_run=self._require_run(),
        )
        return [
            {
                "action": result["action"],
                "idempotency_key": f"{sync_job.id}:{result['snapshot'].id}",
            }
            for result in results
        ]


def get_adapter_for_config(config, resource_type=None):
    if resource_type == "advertising_report" and config.platform == "tiktok" and config.environment in {"pilot", "production"}:
        from .ads_sync import AdsSpendAdapter
        return AdsSpendAdapter(config)
    if config.environment == "mock":
        return MockPlatformAdapter() if supports_resource("mock", resource_type, "mock") else DisabledProductionAdapter()
    if config.environment == "sandbox":
        return SandboxPlaceholderAdapter()
    if config.environment not in {"pilot", "production"}:
        return DisabledProductionAdapter()
    if not supports_resource(config.platform, resource_type, "live_readonly"):
        return DisabledProductionAdapter()
    if resource_type == SyncJob.ResourceType.ADVERTISING_REPORT and config.platform == PlatformChoices.SHOPEE:
        from .shopee_advertising import ShopeeAdvertisingAdapter
        return ShopeeAdvertisingAdapter(config)
    if resource_type == SyncJob.ResourceType.AFFILIATE_ORDER and config.platform == PlatformChoices.TIKTOK:
        from .affiliate_sync import TikTokAffiliateOrderAdapter
        return TikTokAffiliateOrderAdapter(config)
    if resource_type == SyncJob.ResourceType.SALES_ORDER and config.platform == PlatformChoices.LAZADA:
        return LazadaOrderAdapter(config)
    if resource_type == SyncJob.ResourceType.SALES_ORDER and config.platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
        return MarketplaceOrderAdapter(config)
    if resource_type == SyncJob.ResourceType.SETTLEMENT_BILL and config.platform in {
        PlatformChoices.LAZADA,
        PlatformChoices.SHOPEE,
        PlatformChoices.TIKTOK,
    }:
        return MarketplaceFinanceTransactionAdapter(config)
    if resource_type == SyncJob.ResourceType.PLATFORM_PRODUCT and config.platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
        return MarketplaceProductAdapter(config)
    if resource_type == SyncJob.ResourceType.REFUND_RETURN and config.platform in {
        PlatformChoices.LAZADA,
        PlatformChoices.SHOPEE,
        PlatformChoices.TIKTOK,
    }:
        return MarketplaceRefundAdapter(config)
    if resource_type == SyncJob.ResourceType.INVENTORY_SNAPSHOT and config.platform == PlatformChoices.JIFENG_WMS:
        return JifengInventoryAdapter(config)
    return DisabledProductionAdapter()
