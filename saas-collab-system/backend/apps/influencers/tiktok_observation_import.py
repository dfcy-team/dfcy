"""Offline, versioned observations. Never promote to canonical or financial facts.

The caller hashes its sanitized source bytes into evidence.source_sha256. This
service verifies shape/scope, not provider authenticity, and hashes the complete
document independently. A complete partition is capture evidence only.
"""

from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import TikTokAdsAdvertiserMapping, marketplace_authorization_api_type
from apps.integrations.ads_subject import mapping_allowed
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p2_scopes import filter_master_data
from apps.masterdata.models import StoreMaster
from .models import TikTokDatasetStageBatch, TikTokDatasetStagePartition, TikTokDatasetStageRecord
from .settlement import normalize_settlement_status
from .tiktok_dataset_import import DatasetImportError, VIDEO_PAYLOAD_FIELDS, _canonical_digest, _date, _resolve_scope
from .tiktok_dataset_staging import METRIC_COUNTS, METRIC_MONEY, _creator, _video
from .tiktok_shop_dataset import AFFILIATE_MONEY_FIELDS


VERSION = "tk-observations-v1"
KINDS = {"affiliate_observation": "affiliate_orders", "video_observation": "videos",
         "creator_snapshot": "creators", "gmv_max_campaign": "gmv_max"}
ENDPOINTS = {"affiliate_observation": "/affiliate_seller/202410/orders/search",
             "video_observation": "/analytics/202605/shop_videos/performance",
             "gmv_max_campaign": "/open_api/v1.3/gmv_max/report/get/"}
TOP = {"schema_version", "tenant_id", "store_id", "day", "observed_at", "kind", "quality",
       "expected_count", "observed_count", "reason", "endpoint", "store_identity", "evidence", "rows"}
ADS = {"mapping_id", "advertiser_id", "currency", "timezone"}
AFF_TEXT = {"order_id", "sku_id", "product_id", "creator_username", "content_id", "content_type", "commission_model"}
AFF_FIELDS = AFF_TEXT | set(AFFILIATE_MONEY_FIELDS) | {
    "create_time", "quantity", "fully_return", "commission_rate", "settlement_status", "payment_amount",
    "canonical_import_blocker", "source_settlement_status", "settlement_mapping_status", "blockers", "affiliate_observed_at"}
CREATOR_FIELDS = {"external_influencer_id", "influencer_id", "username", "nickname", "follower_count",
                  "selection_region", "canonical_import_blocker"}
CREATOR_ENDPOINT = "/affiliate_seller/202406/marketplace_creators/{creator_id}"


def _require(condition, code):
    if not condition:
        raise DatasetImportError(code)


def _shape(value, allowed, required=()):
    _require(isinstance(value, dict) and not set(value) - allowed and set(required) <= set(value), "invalid_fields")


def _int(value, *, nullable=False, minimum=0):
    _require(nullable and value is None or type(value) is int and minimum <= value <= 2**63 - 1, "invalid_integer")


def _text(value, cap=160, *, nullable=False, empty=True, multiline=False):
    _require(nullable and value is None or isinstance(value, str) and len(value) <= cap
             and (empty or bool(value.strip())) and not any(
                 ord(c) < 32 and not (multiline and c in "\r\n\t") for c in value), "invalid_text")


def _decimal(value):
    if value is None:
        return
    _require(isinstance(value, str) and bool(re.fullmatch(r"[0-9]{1,20}(?:\.[0-9]{1,8})?", value)), "invalid_decimal")
    try:
        _require(Decimal(value).is_finite() and Decimal(value) >= 0, "invalid_decimal")
    except InvalidOperation:
        raise DatasetImportError("invalid_decimal") from None


def _money(value, currency):
    _shape(value, {"amount", "currency"}, {"amount", "currency"})
    _decimal(value["amount"])
    _require(value["currency"] is None or value["currency"] == currency, "currency_mismatch")
    _require(value["amount"] is None or value["currency"] == currency, "currency_required")


def _time(value):
    _text(value, 64, empty=False)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DatasetImportError("invalid_timestamp") from None
    _require(timezone.is_aware(parsed) and parsed <= timezone.now() + timedelta(minutes=5), "invalid_timestamp")
    return parsed


def _mapping(doc, actor, store, *, lock=False):
    _int(doc["mapping_id"], minimum=1)
    query = TikTokAdsAdvertiserMapping.objects.select_related("integration_config", "store__platform", "tenant").filter(
        pk=doc["mapping_id"], tenant_id=store.tenant_id, store_id=store.pk, enabled=True)
    if lock:
        query = query.select_for_update()
    mapping = query.first()
    _require(mapping is not None, "ads_mapping_denied")
    config = mapping.integration_config
    _require(config.tenant_id == store.tenant_id and config.platform == "tiktok"
             and marketplace_authorization_api_type(config) == "advertising"
             and not config.deleted_at and config.status in {"active", "verified"}
             and config.environment in {"pilot", "production"}
             and (not config.regions or store.country_code.upper() in {r.upper() for r in config.regions})
             and not config.sync_write_enabled, "ads_config_denied")
    _require(all(doc[k] == getattr(mapping, k) for k in ("advertiser_id", "currency", "timezone")), "ads_mapping_mismatch")
    _require(bool(re.fullmatch(r"[A-Z]{3}", mapping.currency)), "invalid_currency")
    ZoneInfo(mapping.timezone)
    _require(check_user_permission(actor, "masterdata.view") and filter_master_data(actor, StoreMaster.objects.filter(pk=store.pk, tenant_id=store.tenant_id),
                                "masterdata.view", "stores").exists(), "ads_subject_denied")
    for code in ("integrations.view", "integrations.store.view", "integrations.run_live_readonly"):
        _require(check_user_permission(actor, code) and mapping_allowed(actor, mapping, code), "ads_scope_denied")
    from apps.integrations.ads_sync import bound_evidence
    bound_evidence(mapping, lock=lock)
    return mapping


def _scope(doc, actor_id, *, lock=False):
    tenant, actor, store = _resolve_scope(doc["tenant_id"], doc["store_id"], actor_id, lock=lock)
    identity = doc["store_identity"]
    _require(identity == {"platform_store_id": store.external_store_id, "store_code": store.code,
                          "timezone": store.timezone}, "store_identity_mismatch")
    day = _date(doc["day"], "day")
    _require(day < timezone.now().astimezone(ZoneInfo(store.timezone)).date(), "day_not_completed")
    if doc["kind"] != "creator_snapshot":
        _require(_time(doc["observed_at"]) >= datetime.combine(day + timedelta(days=1), time.min,
                 ZoneInfo(store.timezone)), "capture_before_day_completed")
    _require(store.platform.tenant_id == tenant.pk and store.platform.status == "active", "store_platform_denied")
    if doc["kind"] == "gmv_max_campaign":
        mapping = _mapping(doc, actor, store, lock=lock)
        _require(day < timezone.now().astimezone(ZoneInfo(mapping.timezone)).date(), "advertiser_day_not_completed")
        _require(_time(doc["observed_at"]) >= datetime.combine(day + timedelta(days=1), time.min,
                 ZoneInfo(mapping.timezone)), "capture_before_advertiser_day_completed")
    return tenant, actor, store, day


def _project(row, doc, store, day):
    kind = doc["kind"]
    currency = store.currency.upper()
    if kind == "affiliate_observation":
        _shape(row, AFF_FIELDS, {"order_id", "sku_id", "product_id", "create_time", "source_settlement_status",
                                "settlement_mapping_status", "settlement_status", "blockers"})
        for field in AFF_TEXT:
            _text(row.get(field, ""), empty=field not in {"order_id", "sku_id", "product_id"})
        _int(row["create_time"])
        try:
            actual_day = datetime.fromtimestamp(row["create_time"], UTC).astimezone(ZoneInfo(store.timezone)).date()
        except (OverflowError, OSError, ValueError):
            raise DatasetImportError("invalid_create_time") from None
        _require(actual_day == day, "affiliate_day_mismatch")
        if "affiliate_observed_at" in row:
            _require(_time(row["affiliate_observed_at"]) >= _time(doc["observed_at"]), "observation_before_capture")
        _int(row.get("quantity"), nullable=True)
        _text(row.get("fully_return"), 20, nullable=True)
        rate = row.get("commission_rate")
        _require(rate is None or type(rate) in (int, str), "invalid_commission_rate")
        _decimal(str(rate) if rate is not None else None)
        for field in AFFILIATE_MONEY_FIELDS:
            if field in row:
                _money(row[field], currency)
        _require(row.get("payment_amount") is None, "payment_guess_forbidden")
        raw = row["source_settlement_status"]
        _text(raw, 80, nullable=True)
        try:
            mapped = normalize_settlement_status(raw)
            status = "absent" if mapped is None else "mapped"
        except ValueError:
            mapped, status = None, "unmapped"
        _require(row["settlement_status"] == mapped and row["settlement_mapping_status"] == status, "settlement_mapping_mismatch")
        blockers = row["blockers"]
        _require(isinstance(blockers, list) and len(blockers) <= 8
                 and all(isinstance(b, str) and b in {"unmapped_settlement_status", "sku_payment_semantics_not_verified",
                         "absent_settlement_status"} for b in blockers) and len(set(blockers)) == len(blockers), "invalid_blockers")
        required = {"sku_payment_semantics_not_verified"}
        if status != "mapped":
            required.add("unmapped_settlement_status" if status == "unmapped" else "absent_settlement_status")
        _require(set(blockers) == required and row.get("canonical_import_blocker", "sku_payment_semantics_not_verified")
                 == "sku_payment_semantics_not_verified", "missing_blocker")
        identity = [row["order_id"], row["sku_id"]]
        unknown = status == "unmapped"
    elif kind == "video_observation":
        _shape(row, VIDEO_PAYLOAD_FIELDS, {"external_video_id", "metric_date", "metrics"})
        _require(row["metric_date"] == doc["day"], "video_day_mismatch")
        for field, cap in (("external_video_id", 160), ("creator_open_id", 160), ("creator_username", 160),
                           ("creator_nickname", 160), ("author_type", 30), ("title", 8192)):
            _text(row.get(field, ""), cap, empty=field != "external_video_id", multiline=field == "title")
        _shape(row["metrics"], METRIC_COUNTS | METRIC_MONEY)
        for field, value in row["metrics"].items():
            _int(value, nullable=True) if field in METRIC_COUNTS else _money(value, currency)
        _require(row.get("currency") in (None, currency), "currency_mismatch")
        _require(row.get("canonical_metric_blocker", "nullable_daily_metric_contract_required")
                 == "nullable_daily_metric_contract_required", "invalid_blocker")
        if row.get("published_at") is not None:
            _time(row["published_at"])
        _video(row, store)
        identity, unknown = row["external_video_id"], False
    elif kind == "creator_snapshot":
        _shape(row, CREATOR_FIELDS, {"external_influencer_id"})
        for field, cap in (("external_influencer_id", 20), ("username", 255), ("nickname", 160), ("selection_region", 8)):
            _text(row.get(field, ""), cap)
        _int(row.get("influencer_id"), nullable=True, minimum=1)
        _int(row.get("follower_count"), nullable=True)
        _require(doc["endpoint"] == CREATOR_ENDPOINT or doc["endpoint"].rsplit("/", 1)[-1]
                 == row["external_influencer_id"], "creator_endpoint_mismatch")
        _require(row.get("canonical_import_blocker", "creator_snapshot_dependency_not_in_main")
                 == "creator_snapshot_dependency_not_in_main", "invalid_blocker")
        diagnostic = _creator(row, store)[0][2]
        row = {**row, "identity_status": diagnostic["identity_status"],
               "matched_influencer_id": diagnostic["influencer_id"]}
        identity, unknown = row["external_influencer_id"], False
    else:
        _shape(row, {"campaign_id", "stat_time_day", "cost"}, {"campaign_id", "stat_time_day", "cost"})
        _text(row["campaign_id"], 64, empty=False)
        _require(bool(re.fullmatch(r"[0-9]+", row["campaign_id"])), "invalid_campaign_id")
        _require(row["stat_time_day"] == doc["day"], "gmv_day_mismatch")
        _decimal(row["cost"])
        identity, unknown = [doc["mapping_id"], row["campaign_id"]], False
    payload = {"schema_version": VERSION, "observation": row, "is_formal": False,
               "canonical_blocker": "raw_observation_only", "provenance": {
                   k: doc[k] for k in ("observed_at", "endpoint", "store_identity", "evidence")}}
    payload["provenance"]["status"] = "unverified_source_claim"
    if kind == "gmv_max_campaign":
        payload["provenance"].update({k: doc[k] for k in ADS})
    return _canonical_digest(identity), payload, int(unknown)


def import_observations(document, actor_id, apply=False):
    """Validate all rows first; persist only Stage* tables in resumable 50-row pages.

    source_total is provider-reported, expected_count is the collector's reconciled
    row count, observed_count is len(rows), unknown_count is computed here.
    Neither a hash nor a caller's complete flag proves upstream authenticity.
    """
    _require(type(apply) is bool, "invalid_apply")
    _shape(document, TOP | ADS, TOP)
    doc = deepcopy(document)
    _require(doc["schema_version"] == VERSION and isinstance(doc["kind"], str) and doc["kind"] in KINDS, "invalid_version_or_kind")
    _require(set(doc) == TOP | (ADS if doc["kind"] == "gmv_max_campaign" else set()), "invalid_document_fields")
    for field in ("tenant_id", "store_id"):
        _int(doc[field], minimum=1)
    _int(actor_id, minimum=1)
    _shape(doc["store_identity"], {"platform_store_id", "store_code", "timezone"}, {"platform_store_id", "store_code", "timezone"})
    for value in doc["store_identity"].values():
        _text(value, 160, empty=False)
    observed_at = _time(doc["observed_at"])
    _require(doc["quality"] in ("complete", "partial"), "invalid_quality")
    _require(isinstance(doc["reason"], str) and bool(re.fullmatch(r"[A-Za-z0-9_:-]{0,100}", doc["reason"])), "invalid_reason")
    endpoint = doc["endpoint"]
    _require(isinstance(endpoint, str), "invalid_endpoint")
    if doc["kind"] == "creator_snapshot":
        _require(endpoint == CREATOR_ENDPOINT or bool(re.fullmatch(
            r"/affiliate_seller/202406/marketplace_creators/[0-9]{1,20}", endpoint)), "invalid_endpoint")
    else:
        _require(endpoint == ENDPOINTS[doc["kind"]], "invalid_endpoint")
    evidence = doc["evidence"]
    _shape(evidence, {"count_unit", "pagination_exhausted", "page_count", "source_total", "source_sha256"},
           {"count_unit", "pagination_exhausted", "page_count", "source_total", "source_sha256"})
    _require(isinstance(evidence["count_unit"], str) and evidence["count_unit"] in {"order_sku", "video", "creator", "campaign"}
             and evidence["count_unit"] == {"affiliate_observation": "order_sku", "video_observation": "video",
                 "creator_snapshot": "creator", "gmv_max_campaign": "campaign"}[doc["kind"]], "invalid_count_unit")
    _require(type(evidence["pagination_exhausted"]) is bool, "invalid_pagination")
    _int(evidence["page_count"])
    _require(evidence["page_count"] <= 100, "page_limit_exceeded")
    _int(evidence["source_total"], nullable=True)
    _require(isinstance(evidence["source_sha256"], str) and bool(re.fullmatch(r"[0-9a-f]{64}", evidence["source_sha256"])), "invalid_source_hash")
    _int(doc["expected_count"], nullable=True)
    _require(doc["expected_count"] is None or doc["expected_count"] <= 2**32 - 1, "expected_count_out_of_range")
    _int(doc["observed_count"])
    _require(isinstance(doc["rows"], list) and len(doc["rows"]) <= 10000
             and doc["observed_count"] == len(doc["rows"]), "invalid_row_count")
    _require(not doc["rows"] or evidence["page_count"] > 0, "missing_page_evidence")
    if doc["quality"] == "complete":
        _require(evidence["pagination_exhausted"] and doc["expected_count"] == len(doc["rows"]), "unproven_complete")
        _require(evidence["source_total"] is None or evidence["source_total"] == len(doc["rows"]), "source_total_mismatch")
    # PARTIAL may contain fewer or more rows than the provider's declared total.
    # Preserve that discrepancy; only COMPLETE requires equality above.
    try:
        encoded = json.dumps(doc, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError):
        raise DatasetImportError("invalid_document_json") from None
    _require(len(encoded) <= 20 * 1024 * 1024, "document_too_large")
    digest = _canonical_digest(doc)
    tenant, actor, store, day = _scope(doc, actor_id)
    prepared, unknown, identities = [], 0, set()
    for row in doc["rows"]:
        key, payload, count = _project(row, doc, store, day)
        _require(key not in identities, "duplicate_observation_identity")
        identities.add(key)
        prepared.append((key, _canonical_digest(payload), payload))
        unknown += count
    missing_settlement = sum(doc["kind"] == "affiliate_observation" and
                             row["settlement_mapping_status"] == "absent" for row in doc["rows"])
    missing_cost = sum(doc["kind"] == "gmv_max_campaign" and row["cost"] is None for row in doc["rows"])
    diagnostics = {"unknown_count": unknown, "unknown_settlement_count": unknown,
                   "missing_settlement_count": missing_settlement, "missing_cost_count": missing_cost}
    meta = {"quality": doc["quality"], "observed_count": len(prepared), "expected_count": doc["expected_count"],
            "reason": doc["reason"], "evidence": {**evidence, "schema_version": VERSION,
                "source_provenance": "unverified_source_claim",
                **diagnostics, "observed_at": doc["observed_at"], "endpoint": endpoint,
                **({k: doc[k] for k in ADS} if doc["kind"] == "gmv_max_campaign" else {})}}
    result = {"is_formal": False, "canonical_writes": 0, "manifest_digest": digest, "batch_id": None,
              "source_provenance": "unverified_source_claim",
              "observed_count": len(prepared), "expected_count": doc["expected_count"], "source_total": evidence["source_total"],
              **diagnostics, "created": 0, "noop": 0, "would_create": 0, "quality": doc["quality"],
              "mode": "apply" if apply else "dry-run"}
    for offset in range(0, max(1, len(prepared)), 50):
        with transaction.atomic():
            tenant, actor, store, day = _scope(doc, actor_id, lock=apply)
            batch_query = TikTokDatasetStageBatch.objects.filter(tenant=tenant, store=store, manifest_digest=digest)
            batch = batch_query.select_for_update().first() if apply else batch_query.first()
            if batch is None and apply:
                batch = TikTokDatasetStageBatch.objects.create(tenant=tenant, store=store, created_by=actor,
                    manifest_digest=digest, schema_version=1, window_start=day, window_end=day,
                    source_created_at=observed_at, store_identity={**doc["store_identity"], "schema_version": VERSION})
            partition = None
            if batch:
                _require(batch.schema_version == 1 and batch.window_start == day and batch.window_end == day
                         and batch.source_created_at == observed_at and batch.store_identity == {
                             **doc["store_identity"], "schema_version": VERSION}, "batch_conflict")
                result["batch_id"] = batch.pk
                partition = batch.partitions.filter(tenant=tenant, kind=KINDS[doc["kind"]], partition_date=day).first()
            if partition is None and apply:
                partition = TikTokDatasetStagePartition.objects.create(tenant=tenant, batch=batch,
                    kind=KINDS[doc["kind"]], partition_date=day, **meta)
            if partition:
                _require(all(getattr(partition, k) == v for k, v in meta.items()), "partition_conflict")
                _require(partition.next_offset <= len(prepared) and (partition.next_offset % 50 == 0
                         or partition.next_offset == len(prepared)), "cursor_conflict")
                initial_empty = not prepared and partition.next_offset == 0 and partition.import_status == "pending"
                _require(partition.imported_count == partition.next_offset and not partition.rejected_count
                         and (initial_empty or (partition.import_status == "completed") ==
                              (partition.next_offset == len(prepared)))
                         and partition.records.count() == partition.next_offset, "cursor_conflict")
            for key, payload_hash, payload in prepared[offset:offset + 50]:
                existing = partition.records.filter(tenant=tenant, record_type=doc["kind"], record_key=key).first() if partition else None
                if existing:
                    _require(existing.payload_hash == payload_hash and existing.payload == payload, "immutable_payload_conflict")
                    result["noop"] += 1
                else:
                    _require(not partition or offset >= partition.next_offset, "missing_committed_observation")
                    if apply:
                        TikTokDatasetStageRecord.objects.create(tenant=tenant, partition=partition,
                            record_type=doc["kind"], record_key=key, payload_hash=payload_hash, payload=payload)
                        result["created"] += 1
                    else:
                        result["would_create"] += 1
            if apply and offset >= partition.next_offset:
                partition.next_offset = min(len(prepared), offset + 50)
                partition.imported_count = partition.next_offset
                partition.import_status = "completed" if partition.next_offset == len(prepared) else "pending"
                partition.save(update_fields=["next_offset", "imported_count", "import_status"])
    return result
