"""Bounded offline ingestion. No network, canonical promotion, or financial writes."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
import re

from django.db import transaction
from django.utils import timezone

from .models import (
    InfluencerProfile, TikTokDatasetStageBatch, TikTokDatasetStagePartition,
    TikTokDatasetStageRecord, normalize_tiktok_username,
)
from .tiktok_dataset_import import (
    DatasetImportError, VIDEO_PAYLOAD_FIELDS, _canonical_digest, _date,
    _resolve_scope, _validate_locked_store_identity, _validate_manifest,
)
from .tiktok_shop_dataset import (
    AFFILIATE_MONEY_FIELDS, DatasetError, _money, _number, _published_time, _text, load_artifact,
)
from .settlement import normalize_settlement_status


MAX_SOURCE_ROWS = 10000
PAGE_SIZE = 50
METRIC_COUNTS = frozenset({
    "views", "likes", "comments", "shares", "orders", "sku_orders", "items_sold",
    "product_impressions", "product_clicks", "unique_customers", "customers",
})
METRIC_MONEY = frozenset({"gmv", "direct_gmv", "indirect_gmv", "gpm"})


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise DatasetImportError("invalid_source_timestamp") from None
    if timezone.is_naive(parsed):
        raise DatasetImportError("naive_source_timestamp")
    return parsed


def _validated_manifest(manifest, rows, tenant, store):
    version = manifest.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise DatasetImportError("invalid_manifest_schema")
    normalized = dict(manifest, schema_version=1)
    normalized["components"] = [dict(c, status="complete" if c.get("status") == "partial" else c.get("status"))
                                for c in manifest["components"]]
    start, end, _ = _validate_manifest(normalized, rows, tenant=tenant, requested_store=store)
    source_created_at = _timestamp(manifest.get("created_at"))
    if source_created_at > timezone.now() + timedelta(minutes=5):
        raise DatasetImportError("source_timestamp_in_future")
    partitions = {}
    for component in manifest["components"]:
        if component["store_id"] != store.pk:
            continue
        kind, status = component["kind"], component["status"]
        if status == "partial" and (version != 2 or kind != "videos"):
            raise DatasetImportError("unsupported_partial_component")
        if kind == "videos" and version == 2:
            days = component.get("days")
            if not isinstance(days, list):
                raise DatasetImportError("video_day_evidence_required")
            seen = set()
            for evidence in days:
                if not isinstance(evidence, dict):
                    raise DatasetImportError("invalid_day_evidence")
                day = _date(evidence.get("date"), "evidence_date")
                quality = evidence.get("status")
                expected, observed = evidence.get("expected_count"), evidence.get("observed_count")
                pages, exhausted = evidence.get("page_count"), evidence.get("pagination_exhausted")
                if (day in seen or not start <= day <= end or quality not in {"complete", "partial", "failed"}
                        or type(observed) is not int or observed < 0
                        or expected is not None and (type(expected) is not int or expected < 0)
                        or type(pages) is not int or not 0 <= pages <= 100 or type(exhausted) is not bool):
                    raise DatasetImportError("invalid_day_evidence")
                count = sum(r["kind"] == kind and r["store_id"] == store.pk and r["payload"]["metric_date"] == day.isoformat() for r in rows)
                if count != observed or quality == "failed" and count:
                    raise DatasetImportError("day_observation_count_mismatch")
                if quality == "complete" and (not exhausted or expected is not None and expected != observed):
                    raise DatasetImportError("unproven_complete_day")
                reason = evidence.get("reason", "")
                if not isinstance(reason, str) or not re.fullmatch(r"[a-zA-Z0-9_:-]{0,100}", reason):
                    raise DatasetImportError("invalid_quality_reason")
                seen.add(day)
                partitions[(kind, day)] = {"quality": quality, "observed_count": observed,
                    "expected_count": expected, "reason": reason,
                    "evidence": {"page_count": pages, "pagination_exhausted": exhausted}}
            if seen != {start + timedelta(days=i) for i in range((end - start).days + 1)}:
                raise DatasetImportError("video_day_set_incomplete")
            qualities = [partitions[(kind, day)]["quality"] for day in seen]
            actual_status = "complete" if all(q == "complete" for q in qualities) else (
                "failed" if all(q == "failed" for q in qualities) else "partial")
            if status != actual_status:
                raise DatasetImportError("component_day_quality_mismatch")
        else:
            partitions[(kind, start)] = {"quality": status, "observed_count": component["row_count"],
                "expected_count": None, "reason": "source_failed" if status == "failed" else "",
                "evidence": {"schema_version": version}}
    return start, end, source_created_at, partitions


def _video(payload, store):
    if set(payload) - VIDEO_PAYLOAD_FIELDS:
        raise DatasetImportError("unsupported_video_fields")
    result = {field: _text(payload.get(field), cap) for field, cap in (
        ("external_video_id", 160), ("creator_open_id", 160), ("creator_username", 160),
        ("creator_nickname", 160), ("author_type", 30), ("title", 8192))}
    if not result["external_video_id"]:
        raise DatasetImportError("video_identity_missing")
    published = payload.get("published_at")
    source_published = payload.get("source_published_at")
    if published is not None:
        _timestamp(published)
        if source_published is not None:
            raise DatasetImportError("conflicting_publication_times")
    if source_published is not None:
        if not isinstance(source_published, str) or _published_time(source_published) != (None, source_published):
            raise DatasetImportError("invalid_source_video_published_at")
    result.update(published_at=published, source_published_at=source_published,
                  metric_date=payload["metric_date"], video_type={"OFFICIAL": "self_operated", "CHANNEL": "self_operated", "AFFILIATE": "creator"}.get(result["author_type"].upper(), "unknown"))
    raw = payload.get("metrics")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or set(raw) - METRIC_COUNTS - METRIC_MONEY:
        raise DatasetImportError("invalid_video_metrics_shape")
    result["metrics"] = {key: _number(raw.get(key), True) for key in sorted(METRIC_COUNTS)}
    result["metrics"].update({key: _money(raw.get(key)) for key in sorted(METRIC_MONEY)})
    currencies = {money["currency"] for key in METRIC_MONEY if (money := result["metrics"][key])["amount"] is not None}
    if None in currencies or currencies and currencies != {store.currency.upper()}:
        raise DatasetImportError("video_currency_mismatch")
    result["currency"] = next(iter(currencies), None)
    return [("video_daily", result["external_video_id"], result)]


def _affiliate(payload, store, start, end):
    try:
        settlement_status = normalize_settlement_status(payload.get("settlement_status"))
    except ValueError:
        raise DatasetImportError("unknown_settlement_status") from None
    result = {key: _text(payload.get(key), 160) for key in (
        "order_id", "sku_id", "product_id", "creator_username", "content_id", "content_type", "commission_model")}
    if not all(result[key] for key in ("order_id", "sku_id", "product_id")):
        raise DatasetImportError("affiliate_identity_missing")
    result.update(quantity=_number(payload.get("quantity"), True), create_time=_number(payload.get("create_time"), True),
                  settlement_status=settlement_status,
                  fully_return=_text(payload.get("fully_return"), 20) or None,
                  commission_rate=_number(payload.get("commission_rate")))
    if result["create_time"] is None:
        raise DatasetImportError("affiliate_create_time_missing")
    from zoneinfo import ZoneInfo
    try:
        day = datetime.fromtimestamp(result["create_time"], UTC).astimezone(ZoneInfo(store.timezone)).date()
    except (ValueError, OSError, OverflowError):
        raise DatasetImportError("invalid_affiliate_create_time") from None
    if not start <= day <= end:
        raise DatasetImportError("affiliate_row_outside_verified_window")
    for key in AFFILIATE_MONEY_FIELDS:
        result[key] = _money(payload.get(key))
        if result[key]["amount"] is not None and result[key]["currency"] != store.currency.upper():
            raise DatasetImportError("affiliate_currency_mismatch")
        if (key == "actual_paid_shop_ads_commission" and result[key]["currency"] is not None
                and result[key]["currency"] != store.currency.upper()):
            raise DatasetImportError("affiliate_currency_mismatch")
    payment = payload.get("order_payment")
    if payment is not None and (not isinstance(payment, dict) or payment.get("source") != "ordinary_order_detail"):
        raise DatasetImportError("untrusted_payment_source")
    money = _money(payment)
    if money["amount"] is not None and (money["currency"] != store.currency.upper() or payment.get("status") != "matched"):
        raise DatasetImportError("affiliate_payment_currency_or_status_mismatch")
    order_payment = dict(order_id=result["order_id"], **money, status="matched" if money["amount"] is not None else "missing",
                         source="ordinary_order_detail" if payment else "not_queried")
    identity = [result[key] for key in ("order_id", "sku_id", "product_id", "creator_username", "content_id", "commission_model")]
    return [("affiliate_line", identity, result), ("order_payment", result["order_id"], order_payment)]


def _creator(payload, store):
    external_id = _text(payload.get("external_influencer_id"), 160)
    if not external_id.isascii() or not external_id.isdecimal() or not 1 <= len(external_id) <= 20 or int(external_id) <= 0:
        raise DatasetImportError("untrusted_creator_id")
    claimed_id = payload.get("influencer_id")
    profiles = list(InfluencerProfile.objects.filter(tenant_id=store.tenant_id, external_influencer_id=external_id).select_related("influencer"))
    unique = (len(profiles) == 1 and type(claimed_id) is int and profiles[0].influencer_id == claimed_id
              and profiles[0].is_active and profiles[0].influencer.platform.lower() == "tiktok")
    result = {key: _text(payload.get(key), cap) for key, cap in (("username", 255), ("nickname", 160), ("selection_region", 8))}
    result.update(external_influencer_id=external_id, follower_count=_number(payload.get("follower_count"), True),
                  id_namespace="seller.creator_marketplace.creator_user_id", influencer_id=None)
    status = "untrusted_or_conflicting_id"
    if unique:
        if not result["username"] or not result["selection_region"]:
            status = "incomplete"
        elif result["selection_region"].upper() != store.country_code.upper():
            status = "region_mismatch"
        elif normalize_tiktok_username(result["username"]) != normalize_tiktok_username(profiles[0].influencer.handle):
            status = "handle_mismatch"
        else:
            status = "matched"
            result["influencer_id"] = claimed_id
    result["identity_status"] = status
    return [("creator_snapshot", external_id, result)]


def _prepare(rows, *, store, start, end, schema_version, partitions):
    grouped = defaultdict(list)
    for row in rows:
        if row["store_id"] != store.pk:
            continue
        day = _date(row["payload"]["metric_date"], "metric_date") if row["kind"] == "videos" and schema_version == 2 else start
        grouped[(row["kind"], day)].append(row["payload"])
    if set(grouped) - set(partitions):
        raise DatasetImportError("row_without_partition_evidence")
    if len(rows) > MAX_SOURCE_ROWS:
        raise DatasetImportError("staging_row_limit_exceeded")
    return grouped


def stage_artifact(*, manifest_path, manifest_sha256, tenant_id, store_id, actor_id, apply=False):
    tenant, actor, store = _resolve_scope(tenant_id, store_id, actor_id)
    if not isinstance(manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise DatasetImportError("manifest_sha256_required")
    try:
        manifest, rows = load_artifact(manifest_path, manifest_sha256)
    except Exception:
        raise DatasetImportError("artifact_invalid") from None
    start, end, source_time, partitions = _validated_manifest(manifest, rows, tenant, store)
    grouped = _prepare(rows, store=store, start=start, end=end, schema_version=manifest["schema_version"], partitions=partitions)
    summary = {"mode": "apply" if apply else "dry-run", "is_formal": False, "canonical_writes": 0,
               "batch_id": None, "created": 0, "noop": 0, "rejected": 0, "partitions": []}
    functions = {"videos": lambda p: _video(p, store), "creators": lambda p: _creator(p, store),
                 "affiliate_orders": lambda p: _affiliate(p, store, start, end)}
    # Detect conflicts across page boundaries in preview as well as apply.
    seen_projected = {}
    # Dry-run and apply share projection validation; apply rechecks identities under the tenant lock.
    for key, meta in sorted(partitions.items()):
        source_rows = grouped.get(key, [])
        report = {"kind": key[0], "date": key[1].isoformat(), **{k: meta[k] for k in ("quality", "observed_count", "expected_count", "reason")}}
        summary["partitions"].append(report)
        for offset in range(0, max(1, len(source_rows)), PAGE_SIZE):
            with transaction.atomic():
                if apply:
                    tenant, actor, store = _resolve_scope(tenant_id, store_id, actor_id, lock=True)
                    _validate_locked_store_identity(manifest, store)
                    entry = next(s for s in manifest["stores"] if s["store_id"] == store.pk)
                    batch, _ = TikTokDatasetStageBatch.objects.get_or_create(tenant=tenant, store=store,
                        manifest_digest=manifest_sha256, defaults={"created_by": actor, "schema_version": manifest["schema_version"],
                            "window_start": start, "window_end": end, "source_created_at": source_time, "store_identity": entry})
                    summary["batch_id"] = batch.pk
                    partition, _ = TikTokDatasetStagePartition.objects.get_or_create(tenant=tenant, batch=batch,
                        kind=key[0], partition_date=key[1], defaults=meta)
                    if partition.next_offset > offset or partition.import_status == "completed":
                        summary["noop"] += min(PAGE_SIZE, len(source_rows) - offset)
                        if offset == 0:
                            summary["rejected"] += partition.rejected_count
                        continue
                    if partition.next_offset != offset:
                        raise DatasetImportError("staging_cursor_conflict")
                candidates, rejected = {}, Counter()
                for payload in source_rows[offset:offset + PAGE_SIZE]:
                    try:
                        projected = functions[key[0]](payload)
                    except (DatasetImportError, DatasetError, TypeError, ValueError) as exc:
                        code = str(exc) if isinstance(exc, (DatasetImportError, DatasetError)) else "invalid_payload"
                        rejected[code] += 1
                        continue
                    for record_type, identity, value in projected:
                        hash_values = dict(value)
                        if record_type == "affiliate_line" and hash_values.get("settlement_status") is None:
                            hash_values.pop("settlement_status", None)
                        if (record_type == "affiliate_line" and hash_values.get("actual_paid_shop_ads_commission")
                                == {"amount": None, "currency": None}):
                            hash_values.pop("actual_paid_shop_ads_commission", None)
                        record_key, payload_hash = _canonical_digest(identity), _canonical_digest(hash_values)
                        candidate_key = (record_type, record_key)
                        scope_key = (key, candidate_key)
                        if scope_key in seen_projected and seen_projected[scope_key] != payload_hash:
                            raise DatasetImportError("conflicting_dataset_identity")
                        seen_projected[scope_key] = payload_hash
                        candidates[candidate_key] = (payload_hash, value)
                if apply:
                    for (record_type, record_key), (payload_hash, payload) in sorted(candidates.items()):
                        existing = TikTokDatasetStageRecord.objects.filter(tenant=tenant, partition=partition,
                            record_type=record_type, record_key=record_key).first()
                        if existing:
                            if existing.payload_hash != payload_hash:
                                raise DatasetImportError("conflicting_dataset_identity")
                            summary["noop"] += 1
                            continue
                        TikTokDatasetStageRecord.objects.create(tenant=tenant, partition=partition,
                            record_type=record_type, record_key=record_key, payload_hash=payload_hash, payload=payload)
                        partition.imported_count += 1
                        summary["created"] += 1
                    partition.next_offset = min(len(source_rows), offset + PAGE_SIZE)
                    partition.rejected_count += sum(rejected.values())
                    reasons = Counter(partition.rejection_reasons)
                    reasons.update(rejected)
                    partition.rejection_reasons = dict(reasons)
                    if partition.next_offset == len(source_rows):
                        partition.import_status = "completed"
                    partition.save()
                summary["rejected"] += sum(rejected.values())
    return summary
