"""Apply a bounded, artifact-backed TikTok Shop video identity trial."""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.influencers.models import ExternalSourceRecord, ImportBatch, TikTokShopVideo
from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed, permission_scope_configs
from apps.tenants.models import Tenant


SOURCE = "tk_shop_dataset_trial"
RECORD_TYPE = "tiktok_shop_video_identity"
MAX_ROWS_PER_RUN = 20
VIDEO_PAYLOAD_FIELDS = {
    "external_video_id",
    "creator_open_id",
    "creator_username",
    "creator_nickname",
    "author_type",
    "title",
    "published_at",
    "source_published_at",
    "metric_date",
    "currency",
    "metrics",
    # Emitted by the paired exporter. This blocker is validation metadata only.
    "canonical_metric_blocker",
}
MANIFEST_KINDS = {"affiliate_orders", "creators", "videos"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DatasetImportError(ValueError):
    """A fixed, non-sensitive error suitable for CLI output."""


def load_artifact(manifest_path, expected_digest):
    """Delegate byte-level validation to the paired exporter artifact loader."""
    from apps.influencers.tiktok_shop_dataset import load_artifact as artifact_loader

    try:
        return artifact_loader(manifest_path, expected_digest)
    except Exception as exc:
        # Do not expose parser details, source content, paths, or provider text.
        code = str(exc) if str(exc).isascii() and re.fullmatch(r"[a-zA-Z0-9_:-]{1,100}", str(exc)) else "artifact_invalid"
        raise DatasetImportError(code) from None


def _canonical_digest(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_int(value, *, minimum=0):
    return type(value) is int and value >= minimum


def _date(value, field):
    if not isinstance(value, str):
        raise DatasetImportError("invalid_" + field)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise DatasetImportError("invalid_" + field) from None
    if parsed.isoformat() != value:
        raise DatasetImportError("invalid_" + field)
    return parsed


def _scope_matches_store(actor, store):
    scope_keys = {"platform_ids", "site_ids", "store_ids", "platforms", "regions"}
    try:
        configs = permission_scope_configs(
            actor,
            "influencers.manage",
            scope_keys,
            allowed_keys=scope_keys,
        )
    except Exception:
        raise DatasetImportError("influencer_store_scope_denied") from None
    if configs is None:
        return True

    platform_values = {
        str(store.platform.platform_type or "").strip().lower(),
        str(store.platform.code or "").strip().lower(),
    }
    country = str(store.country_code or "").strip().upper()
    for config in configs:
        if "platform_ids" in config and store.platform_id not in config["platform_ids"]:
            continue
        if "site_ids" in config and store.platform_site_id not in config["site_ids"]:
            continue
        if "store_ids" in config and store.pk not in config["store_ids"]:
            continue
        if "platforms" in config and not (platform_values & {str(value).strip().lower() for value in config["platforms"]}):
            continue
        if "regions" in config and country not in {str(value).strip().upper() for value in config["regions"]}:
            continue
        return True
    return False


def _resolve_scope(tenant_id, store_id, actor_id, *, lock=False):
    tenant_query = Tenant.objects.filter(pk=tenant_id, status=Tenant.Status.ACTIVE)
    if lock:
        tenant_query = tenant_query.select_for_update()
    tenant = tenant_query.first()
    if tenant is None:
        raise DatasetImportError("tenant_not_found_or_inactive")
    actor_query = get_user_model().objects.filter(
        pk=actor_id,
        tenant_id=tenant_id,
        is_active=True,
        user_type="internal",
    )
    if lock:
        actor_query = actor_query.select_for_update()
    actor = actor_query.first()
    if actor is None:
        raise DatasetImportError("active_internal_actor_required")
    store_query = StoreMaster.objects.select_related("platform").filter(
        pk=store_id,
        tenant_id=tenant_id,
        status="active",
    )
    if lock:
        store_query = store_query.select_for_update()
    store = store_query.first()
    if store is None:
        raise DatasetImportError("store_not_found_or_inactive")
    platform = str(store.platform.platform_type or store.platform.code or "").strip().lower()
    if platform != "tiktok":
        raise DatasetImportError("tiktok_store_required")

    permission_codes = ("influencers.manage", "integrations.run_live_readonly")
    if any(not check_user_permission(actor, code) for code in permission_codes):
        raise DatasetImportError("required_action_permission_missing")
    if not _scope_matches_store(actor, store):
        raise DatasetImportError("influencer_store_scope_denied")
    try:
        allowed = integration_values_allowed(
            actor,
            "integrations.run_live_readonly",
            platform="tiktok",
            regions=[store.country_code],
            store_id=store.pk,
        )
    except Exception:
        raise DatasetImportError("integration_store_scope_denied") from None
    if not allowed:
        raise DatasetImportError("integration_store_scope_denied")
    return tenant, actor, store


def _validate_manifest(manifest, rows, *, tenant, requested_store):
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] not in (1, 2)):
        raise DatasetImportError("invalid_manifest_schema")
    if not _is_int(manifest.get("tenant_id"), minimum=1) or manifest["tenant_id"] != tenant.pk:
        raise DatasetImportError("manifest_tenant_mismatch")
    start_date = _date(manifest.get("start_date"), "start_date")
    end_date = _date(manifest.get("end_date"), "end_date")
    if start_date > end_date or (end_date - start_date).days >= 7:
        raise DatasetImportError("invalid_manifest_window")

    raw_stores = manifest.get("stores")
    raw_components = manifest.get("components")
    if not isinstance(raw_stores, list) or not 1 <= len(raw_stores) <= 2 or not isinstance(raw_components, list):
        raise DatasetImportError("invalid_manifest_scope")
    store_ids = []
    store_entries = {}
    for entry in raw_stores:
        if not isinstance(entry, dict):
            raise DatasetImportError("invalid_manifest_store")
        entry_id = entry.get("store_id")
        if not _is_int(entry_id, minimum=1) or entry_id in store_entries:
            raise DatasetImportError("invalid_manifest_store")
        code = entry.get("store_code")
        external_id = entry.get("platform_shop_id")
        tz_name = entry.get("timezone")
        if not isinstance(code, str) or not code or not isinstance(external_id, str) or not external_id:
            raise DatasetImportError("invalid_manifest_store")
        if not isinstance(tz_name, str) or not tz_name:
            raise DatasetImportError("invalid_manifest_store_timezone")
        try:
            zone = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise DatasetImportError("invalid_manifest_store_timezone") from None
        store_ids.append(entry_id)
        store_entries[entry_id] = (entry, zone)
    if requested_store.pk not in store_entries:
        raise DatasetImportError("requested_store_not_in_manifest")

    db_stores = {
        item.pk: item
        for item in StoreMaster.objects.select_related("platform").filter(tenant_id=tenant.pk, pk__in=store_ids)
    }
    if len(db_stores) != len(store_ids):
        raise DatasetImportError("manifest_store_tenant_mismatch")
    for entry_id, (entry, zone) in store_entries.items():
        store = db_stores[entry_id]
        platform = str(store.platform.platform_type or store.platform.code or "").strip().lower()
        try:
            actual_zone = ZoneInfo(store.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise DatasetImportError("invalid_store_timezone") from None
        if (
            platform != "tiktok"
            or store.code != entry["store_code"]
            or store.external_store_id != entry["platform_shop_id"]
            or actual_zone.key != zone.key
        ):
            raise DatasetImportError("manifest_store_identity_mismatch")
        if end_date >= timezone.now().astimezone(actual_zone).date():
            raise DatasetImportError("manifest_window_not_completed")

    component_by_key = {}
    for component in raw_components:
        if not isinstance(component, dict):
            raise DatasetImportError("invalid_manifest_component")
        key = (component.get("store_id"), component.get("kind"))
        if key[0] not in store_entries or key[1] not in MANIFEST_KINDS or key in component_by_key:
            raise DatasetImportError("invalid_manifest_component_scope")
        status = component.get("status")
        allowed_statuses = {"complete", "failed"}
        if manifest["schema_version"] == 2 and key[1] == "videos":
            allowed_statuses.add("partial")
        if status not in allowed_statuses:
            raise DatasetImportError("invalid_manifest_component_status")
        if not _is_int(component.get("row_count")) or not _is_int(component.get("request_count")):
            raise DatasetImportError("invalid_manifest_component_counts")
        if status in {"complete", "partial"}:
            file_name = component.get("file")
            if (
                not isinstance(file_name, str)
                or not file_name
                or file_name in {".", "..", "manifest.json"}
                or any(char in file_name for char in ("/", "\\", ":"))
            ):
                raise DatasetImportError("invalid_manifest_component_file")
            if not isinstance(component.get("sha256"), str) or not SHA256_RE.fullmatch(component["sha256"]):
                raise DatasetImportError("invalid_manifest_component_digest")
        if manifest["schema_version"] == 2:
            days = component.get("days")
            expected_days = {(start_date + timedelta(days=i)).isoformat()
                             for i in range((end_date - start_date).days + 1)}
            if not isinstance(days, list) or {day.get("date") for day in days if isinstance(day, dict)} != expected_days or len(days) != len(expected_days):
                raise DatasetImportError("component_day_set_incomplete")
            for day in days:
                if (day.get("status") not in allowed_statuses or not _is_int(day.get("observed_count"))
                        or not _is_int(day.get("page_count"))
                        or day.get("expected_count") is not None and not _is_int(day["expected_count"])
                        or type(day.get("pagination_exhausted")) is not bool
                        or day.get("status") == "complete" and not day["pagination_exhausted"]
                        or key[1] == "videos" and day.get("status") == "complete"
                        and day.get("expected_count") is not None
                        and day.get("expected_count") != day["observed_count"]
                        or day.get("status") == "failed" and day["observed_count"]):
                    raise DatasetImportError("invalid_day_evidence")
            statuses = {day["status"] for day in days}
            aggregate = "complete" if statuses == {"complete"} else (
                "failed" if key[1] != "videos" or statuses == {"failed"} else "partial")
            if aggregate != status:
                raise DatasetImportError("component_day_quality_mismatch")
        component_by_key[key] = component
    expected = {(store_id, kind) for store_id in store_ids for kind in MANIFEST_KINDS}
    if set(component_by_key) != expected:
        raise DatasetImportError("manifest_component_set_incomplete")

    if not isinstance(rows, list):
        raise DatasetImportError("invalid_artifact_rows")
    seen_rows = Counter()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"kind", "tenant_id", "store_id", "store_code", "payload"}:
            raise DatasetImportError("invalid_artifact_row_shape")
        row_tenant = row.get("tenant_id")
        row_store = row.get("store_id")
        kind = row.get("kind")
        if (
            type(row_tenant) is not int
            or row_tenant != tenant.pk
            or type(row_store) is not int
            or row_store not in store_entries
            or kind not in MANIFEST_KINDS
            or row.get("store_code") != store_entries[row_store][0]["store_code"]
            or not isinstance(row.get("payload"), dict)
        ):
            raise DatasetImportError("artifact_row_scope_mismatch")
        component = component_by_key[(row_store, kind)]
        if component["status"] not in {"complete", "partial"}:
            raise DatasetImportError("failed_component_contains_rows")
        seen_rows[(row_store, kind)] += 1
        if kind == "videos":
            metric_date = _date(row["payload"].get("metric_date"), "metric_date")
            if not start_date <= metric_date <= end_date:
                raise DatasetImportError("video_row_outside_manifest_window")
            if manifest["schema_version"] == 2:
                evidence = next(day for day in component["days"] if day["date"] == metric_date.isoformat())
                if evidence["status"] == "failed":
                    raise DatasetImportError("failed_day_has_rows")
    for key, component in component_by_key.items():
        if seen_rows[key] != component["row_count"]:
            raise DatasetImportError("component_row_count_mismatch")
        if manifest["schema_version"] == 2 and key[1] == "videos":
            for day in component["days"]:
                count = sum(row["kind"] == "videos" and row["store_id"] == key[0]
                            and row["payload"].get("metric_date") == day["date"] for row in rows)
                if count != day["observed_count"]:
                    raise DatasetImportError("day_observation_count_mismatch")

    requested_component = component_by_key[(requested_store.pk, "videos")]
    if requested_component["status"] in {"complete", "partial"} and requested_component["row_count"] > 0:
        try:
            request_zone = ZoneInfo(requested_store.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise DatasetImportError("invalid_store_timezone") from None
        if end_date >= timezone.now().astimezone(request_zone).date():
            raise DatasetImportError("manifest_window_not_completed")
    return start_date, end_date, component_by_key


def _validate_locked_store_identity(manifest, store):
    entry = next(
        (item for item in manifest["stores"] if item.get("store_id") == store.pk),
        None,
    )
    if entry is None:
        raise DatasetImportError("requested_store_not_in_manifest")
    try:
        manifest_zone = ZoneInfo(entry["timezone"])
        store_zone = ZoneInfo(store.timezone)
    except (KeyError, TypeError, ZoneInfoNotFoundError, ValueError):
        raise DatasetImportError("invalid_store_timezone") from None
    platform = str(store.platform.platform_type or store.platform.code or "").strip().lower()
    if (
        platform != "tiktok"
        or store.code != entry.get("store_code")
        or store.external_store_id != entry.get("platform_shop_id")
        or manifest_zone.key != store_zone.key
    ):
        raise DatasetImportError("manifest_store_identity_mismatch")
    end_date = _date(manifest.get("end_date"), "end_date")
    if end_date >= timezone.now().astimezone(store_zone).date():
        raise DatasetImportError("manifest_window_not_completed")


def _optional_text(payload, field, maximum):
    value = payload.get(field)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > maximum:
        raise DatasetImportError("invalid_video_" + field)
    return value.strip()


def _prepare_video_candidates(rows, *, store_id, start_date, end_date, identity_v2=False, source_quality="complete"):
    grouped = defaultdict(list)
    quarantined = Counter()
    for row in rows:
        if row["store_id"] != store_id or row["kind"] != "videos":
            continue
        payload = row["payload"]
        if set(payload) - VIDEO_PAYLOAD_FIELDS:
            quarantined["video_payload_field_not_allowed"] += 1
            continue
        if payload.get("canonical_metric_blocker") not in (None, "nullable_daily_metric_contract_required"):
            quarantined["invalid_metric_blocker"] += 1
            continue
        video_id = payload.get("external_video_id")
        if not isinstance(video_id, str) or not video_id.strip() or len(video_id) > 160:
            quarantined["stable_video_id_required"] += 1
            continue
        author_type = payload.get("author_type")
        if identity_v2 and author_type is None:
            author_type = ""
        if not isinstance(author_type, str):
            quarantined["unknown_author_type"] += 1
            continue
        author_type = author_type.strip().upper()
        if identity_v2:
            # Observed account-type aliases must not guess marketing ownership.
            author_type = {"AFFILIATE_ACCOUNTS": "AFFILIATE", "OFFICIAL_ACCOUNTS": "OFFICIAL",
                           "MARKETING_ACCOUNTS": ""}.get(author_type, author_type)
        if author_type in {"OFFICIAL", "CHANNEL"}:
            video_type = TikTokShopVideo.VideoType.SELF_OPERATED
        elif author_type == "AFFILIATE":
            video_type = TikTokShopVideo.VideoType.CREATOR
        elif identity_v2 and not author_type:
            video_type = TikTokShopVideo.VideoType.UNKNOWN
        else:
            quarantined["unknown_author_type"] += 1
            continue
        try:
            metric_date = _date(payload.get("metric_date"), "metric_date")
            if not start_date <= metric_date <= end_date:
                raise DatasetImportError("video_row_outside_manifest_window")
            open_id = _optional_text(payload, "creator_open_id", 160)
            username = _optional_text(payload, "creator_username", 160)
            title = _optional_text(payload, "title", 8192 if identity_v2 else 500)
            nickname = _optional_text(payload, "creator_nickname", 160)
            currency = payload.get("currency")
            if currency is not None and (
                not isinstance(currency, str)
                or len(currency) > 3
                or (currency and (len(currency) != 3 or not currency.isascii() or not currency.isalpha()))
            ):
                raise DatasetImportError("invalid_video_currency")
            metrics = payload.get("metrics")
            if metrics is not None and not isinstance(metrics, dict):
                raise DatasetImportError("invalid_video_metrics_shape")
            published_at = payload.get("published_at")
            source_published_at = payload.get("source_published_at")
            if source_published_at is not None:
                if not isinstance(source_published_at, str) or len(source_published_at) != 19 or published_at is not None:
                    raise DatasetImportError("invalid_source_video_published_at")
                try:
                    source_time = datetime.strptime(source_published_at, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    raise DatasetImportError("invalid_source_video_published_at") from None
                if source_time.strftime("%Y-%m-%d %H:%M:%S") != source_published_at:
                    raise DatasetImportError("invalid_source_video_published_at")
            if published_at is not None:
                if not isinstance(published_at, str):
                    raise DatasetImportError("invalid_video_published_at")
                try:
                    published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                except ValueError:
                    raise DatasetImportError("invalid_video_published_at") from None
                if timezone.is_naive(published_at):
                    raise DatasetImportError("naive_video_published_at")
            identity = {
                "external_video_id": video_id.strip(),
                "creator_open_id": open_id,
                "creator_username": username,
                "title": title,
                "published_at": published_at.isoformat() if published_at else None,
                "video_type": video_type,
            }
            # The nickname and all metrics are validated then deliberately discarded.
            _ = nickname
            identity["payload_hash"] = _canonical_digest(identity)
            identity["published_at_value"] = published_at
            identity["source_api"] = ("tiktok_shop_identity_partial" if source_quality == "partial"
                                      else "tiktok_shop_dataset_trial")
            grouped[identity["external_video_id"]].append(identity)
        except DatasetImportError as exc:
            quarantined[str(exc)] += 1

    candidates = []
    for video_id, identities in grouped.items():
        signatures = {item["payload_hash"] for item in identities}
        if len(signatures) != 1:
            quarantined["conflicting_duplicate_video_identity"] += len(identities)
            continue
        candidates.append(identities[0])
    candidates.sort(key=lambda item: item["external_video_id"])
    return candidates, quarantined


def _external_record_id(store_id, external_video_id):
    value = f"{store_id}:{external_video_id}"
    if len(value) <= 160:
        return value
    return f"{store_id}:sha256:{hashlib.sha256(external_video_id.encode('utf-8')).hexdigest()}"


def _classify_existing(candidates, *, tenant_id, store_id, lock=False):
    record_ids = {_external_record_id(store_id, item["external_video_id"]): item for item in candidates}
    if not candidates:
        return {}, Counter()
    record_query = ExternalSourceRecord.objects.filter(
            tenant_id=tenant_id,
            source=SOURCE,
            record_type=RECORD_TYPE,
            external_id__in=record_ids,
        ).select_related("batch")
    video_query = TikTokShopVideo.objects.filter(
            tenant_id=tenant_id,
            store_id=store_id,
            external_video_id__in=[item["external_video_id"] for item in candidates],
        )
    if lock:
        record_query = record_query.select_for_update()
        video_query = video_query.select_for_update()
    source_records = {record.external_id: record for record in record_query}
    videos = {video.external_video_id: video for video in video_query}
    states = {}
    quarantined = Counter()
    for external_id, item in record_ids.items():
        record = source_records.get(external_id)
        video = videos.get(item["external_video_id"])
        if record is None and video is None:
            states[item["external_video_id"]] = "new"
        elif record is not None and video is not None:
            expected_username_normalized = item["creator_username"].strip().lstrip("@").casefold()
            if (
                record.payload_hash == item["payload_hash"]
                and record.target_model == "TikTokShopVideo"
                and record.target_id == str(video.pk)
                and record.batch.tenant_id == tenant_id
                and record.batch.source == SOURCE
                and record.batch.status == ImportBatch.Status.COMPLETED
                and video.tenant_id == tenant_id
                and video.store_id == store_id
                and video.external_video_id == item["external_video_id"]
                and video.creator_id == ""
                and video.creator_open_id == item["creator_open_id"]
                and video.creator_username == item["creator_username"]
                and video.creator_username_normalized == expected_username_normalized
                and video.title == item["title"]
                and video.published_at == item["published_at_value"]
                and video.video_type == item["video_type"]
                and video.influencer_id is None
                and video.source_api == item["source_api"]
            ):
                states[item["external_video_id"]] = "noop"
            else:
                states[item["external_video_id"]] = "quarantine"
                quarantined["existing_source_record_conflict"] += 1
        else:
            states[item["external_video_id"]] = "quarantine"
            quarantined["existing_video_untracked"] += 1
    return states, quarantined


def _batch_key(manifest_digest, store_id, limit):
    return "tkds-v1-" + _canonical_digest({
        "manifest_sha256": manifest_digest,
        "store_id": store_id,
        "limit": limit,
        "record_type": RECORD_TYPE,
    })


def run_import(*, manifest_path, manifest_sha256, tenant_id, store_id, actor_id, limit=MAX_ROWS_PER_RUN, apply=False):
    if not _is_int(limit, minimum=1) or limit > MAX_ROWS_PER_RUN:
        raise DatasetImportError("limit_must_be_between_1_and_20")
    if not isinstance(manifest_sha256, str) or not SHA256_RE.fullmatch(manifest_sha256):
        raise DatasetImportError("manifest_sha256_required")
    tenant, actor, store = _resolve_scope(tenant_id, store_id, actor_id)
    manifest, rows = load_artifact(manifest_path, manifest_sha256)
    start_date, end_date, components = _validate_manifest(manifest, rows, tenant=tenant, requested_store=store)
    all_candidates, quarantined = _prepare_video_candidates(
        rows,
        store_id=store.pk,
        start_date=start_date,
        end_date=end_date,
        identity_v2=manifest["schema_version"] == 2,
        source_quality=components[(store.pk, "videos")]["status"],
    )
    selected = all_candidates[:limit]
    deferred = max(0, len(all_candidates) - len(selected))
    mode = "apply" if apply else "dry-run"
    video_component_failed = components[(store.pk, "videos")]["status"] == "failed"
    if apply and video_component_failed:
        raise DatasetImportError("failed_video_component")

    def report(*, states, more_quarantined=None, created=0):
        reasons = Counter(quarantined)
        if more_quarantined:
            reasons.update(more_quarantined)
        noop = sum(state == "noop" for state in states.values())
        return {
            "mode": mode,
            "manifest_sha256": manifest_sha256,
            "tenant_id": tenant.pk,
            "store_id": store.pk,
            "limit": limit,
            "eligible": sum(state in {"new", "noop"} for state in states.values()),
            "valid_candidates": len(all_candidates),
            "quarantined": sum(reasons.values()),
            "deferred": deferred,
            "created": created,
            "noop": noop,
            "failed_video_component": video_component_failed,
            "identity_only": True,
            "metric_rows_written": 0,
            "source_quality": components[(store.pk, "videos")]["status"],
            "reasons": dict(sorted(reasons.items())),
        }

    if not apply:
        states, existing_conflicts = _classify_existing(selected, tenant_id=tenant.pk, store_id=store.pk)
        return report(states=states, more_quarantined=existing_conflicts)

    created = 0
    try:
        with transaction.atomic():
            locked_tenant = Tenant.objects.select_for_update().filter(
                pk=tenant.pk,
                status=Tenant.Status.ACTIVE,
            ).first()
            if locked_tenant is None:
                raise DatasetImportError("tenant_not_found_or_inactive")
            tenant, actor, store = _resolve_scope(tenant.pk, store.pk, actor.pk, lock=True)
            _validate_locked_store_identity(manifest, store)
            states, existing_conflicts = _classify_existing(
                selected,
                tenant_id=tenant.pk,
                store_id=store.pk,
                lock=True,
            )
            batch_key = _batch_key(manifest_sha256, store.pk, limit)
            batch = ImportBatch.objects.select_for_update().filter(
                tenant_id=tenant.pk,
                source=SOURCE,
                batch_key=batch_key,
            ).first()
            if batch is None:
                batch = ImportBatch.objects.create(
                    tenant=tenant,
                    source=SOURCE,
                    batch_key=batch_key,
                    status=ImportBatch.Status.PENDING,
                    row_count=0,
                    error_count=0,
                    manifest_digest=manifest_sha256,
                    created_by=actor,
                )
            elif batch.manifest_digest != manifest_sha256 or batch.status != ImportBatch.Status.COMPLETED:
                raise DatasetImportError("existing_batch_not_replayable")
            elif any(state == "new" for state in states.values()):
                missing = sum(state == "new" for state in states.values())
                existing_conflicts["completed_batch_missing_identity"] += missing
                states = {
                    video_id: ("quarantine" if state == "new" else state)
                    for video_id, state in states.items()
                }

            for item in selected:
                if states.get(item["external_video_id"]) != "new":
                    continue
                video = TikTokShopVideo.objects.create(
                    tenant=tenant,
                    store=store,
                    influencer=None,
                    external_video_id=item["external_video_id"],
                    creator_id="",
                    creator_open_id=item["creator_open_id"],
                    creator_username=item["creator_username"],
                    title=item["title"],
                    published_at=item["published_at_value"],
                    video_type=item["video_type"],
                    source_api=item["source_api"],
                )
                ExternalSourceRecord.objects.create(
                    tenant=tenant,
                    batch=batch,
                    source=SOURCE,
                    external_id=_external_record_id(store.pk, item["external_video_id"]),
                    record_type=RECORD_TYPE,
                    payload_hash=item["payload_hash"],
                    target_model="TikTokShopVideo",
                    target_id=str(video.pk),
                )
                created += 1
            if batch.status != ImportBatch.Status.COMPLETED:
                batch.status = ImportBatch.Status.COMPLETED
                batch.row_count = created
                batch.error_count = sum(quarantined.values()) + sum(existing_conflicts.values())
                batch.completed_at = timezone.now()
                batch.save(update_fields=("status", "row_count", "error_count", "completed_at"))
    except DatasetImportError:
        raise
    except IntegrityError:
        # A concurrent writer may not participate in this command's tenant lock.
        raise DatasetImportError("concurrent_identity_conflict_retry") from None

    return report(states=states, more_quarantined=existing_conflicts, created=created)
