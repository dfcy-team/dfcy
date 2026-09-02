import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant

from ...models import Influencer, InfluencerProfile, VideoResult, normalize_tiktok_username


def _text(row, key):
    return str(row.get(key) or "").strip()


def _integer(row, key):
    try:
        return max(0, int(Decimal(_text(row, key) or "0")))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{key}:invalid_integer")


def _decimal(row, key):
    try:
        value = Decimal(_text(row, key) or "0")
    except InvalidOperation:
        raise ValueError(f"{key}:invalid_decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{key}:invalid_decimal")
    return value


def _datetime(value, field, *, required=False):
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise ValueError(f"{field}:required")
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"{field}:invalid_datetime") from exc
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _content_type(value):
    normalized = str(value or "").strip().casefold()
    if normalized in {"live", "livestream", "直播"}:
        return VideoResult.ContentType.LIVE
    return VideoResult.ContentType.VIDEO


class Command(BaseCommand):
    help = "Import latest, real per-video performance snapshots; dry-run unless --apply is supplied."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--file", required=True)
        parser.add_argument("--source", default="legacy_video_performance")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError("CSV file does not exist.")
        try:
            tenant = Tenant.objects.get(pk=options["tenant_id"])
        except Tenant.DoesNotExist as exc:
            raise CommandError("Tenant does not exist.") from exc
        source = str(options["source"] or "").strip()
        if not source or len(source) > 40:
            raise CommandError("source must be 1-40 characters.")
        batch_size = max(1, min(int(options["batch_size"] or 500), 5000))

        creator_map = {}
        for profile in InfluencerProfile.objects.filter(
            tenant=tenant, external_influencer_id__gt=""
        ).select_related("influencer"):
            creator_map.setdefault(profile.external_influencer_id.strip(), []).append(profile.influencer)
        handle_map = {}
        for influencer in Influencer.objects.filter(tenant=tenant, platform__iexact="TikTok"):
            handle = normalize_tiktok_username(influencer.handle)
            if handle:
                handle_map.setdefault(handle, []).append(influencer)
        store_map = {}
        for store in StoreMaster.objects.filter(tenant=tenant):
            for value in (store.code, store.name):
                if value:
                    store_map.setdefault(str(value).strip().casefold(), store)

        summary = {
            "mode": "apply" if options["apply"] else "dry-run",
            "source_rows": 0,
            "latest_rows": 0,
            "created": 0,
            "updated": 0,
            "noop": 0,
            "stale": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "invalid": 0,
        }
        latest = {}
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"video_id", "data_time", "creator_id", "creator_name"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise CommandError("CSV is missing required video columns.")
            for row in reader:
                summary["source_rows"] += 1
                video_id = _text(row, "video_id")
                if not video_id:
                    summary["invalid"] += 1
                    continue
                try:
                    observed_at = _datetime(
                        _text(row, "export_time") or _text(row, "data_time"),
                        "source_updated_at",
                        required=True,
                    )
                except ValueError:
                    summary["invalid"] += 1
                    continue
                previous = latest.get(video_id)
                if previous is None or observed_at > previous[0]:
                    latest[video_id] = (observed_at, row)
        summary["latest_rows"] = len(latest)

        rows = list(latest.values())
        for offset in range(0, len(rows), batch_size):
            with transaction.atomic():
                for observed_at, row in rows[offset:offset + batch_size]:
                    self._process_row(
                        tenant, source, observed_at, row, creator_map, handle_map, store_map,
                        summary, apply=options["apply"],
                    )
                if not options["apply"]:
                    transaction.set_rollback(True)
        self.stdout.write(" ".join(f"{key}={value}" for key, value in summary.items()))

    def _process_row(self, tenant, source, observed_at, row, creator_map, handle_map, store_map, summary, *, apply):
        creator_id = _text(row, "creator_id")
        candidates = creator_map.get(creator_id, []) if creator_id else []
        if not candidates:
            handle = normalize_tiktok_username(_text(row, "creator_name"))
            candidates = handle_map.get(handle, []) if handle else []
        if not candidates:
            summary["unmatched"] += 1
            return
        if len(candidates) != 1:
            summary["ambiguous"] += 1
            return
        influencer = candidates[0]
        try:
            metric_time = _datetime(_text(row, "data_time"), "data_time", required=True)
            published_at = _datetime(_text(row, "publish_time"), "publish_time")
            values = {
                "influencer": influencer,
                "store": store_map.get(_text(row, "shop_abbr").casefold()),
                "content_type": _content_type(_text(row, "video_type")),
                "url": "",
                "title": _text(row, "video_title")[:240],
                "published_at": published_at,
                "metric_date": timezone.localtime(metric_time).date(),
                "views": _integer(row, "vv"),
                "live_views": _integer(row, "vv") if _content_type(_text(row, "video_type")) == VideoResult.ContentType.LIVE else 0,
                "orders": _integer(row, "orders"),
                "gmv": _decimal(row, "gmv_video"),
                # The legacy video export has no currency column. Preserve an
                # explicit unknown marker rather than fabricating CNY.
                "currency": _text(row, "currency")[:8] or "UNKNOWN",
                "source": source,
                "source_updated_at": observed_at,
            }
        except ValueError:
            summary["invalid"] += 1
            return
        video_id = _text(row, "video_id")
        current = VideoResult.objects.filter(
            tenant=tenant, platform="TikTok", external_content_id=video_id
        ).first()
        if current is not None and current.source_updated_at and current.source_updated_at > observed_at:
            summary["stale"] += 1
            return
        comparable = tuple(values[field] for field in values if field not in {"source_updated_at"})
        existing = tuple(getattr(current, field) for field in values if field not in {"source_updated_at"}) if current else None
        if current is not None and existing == comparable and current.source_updated_at == observed_at:
            summary["noop"] += 1
            return
        if not apply:
            summary["updated" if current else "created"] += 1
            return
        if current is None:
            candidate = VideoResult(
                tenant=tenant, platform="TikTok", external_content_id=video_id, **values
            )
            candidate.full_clean()
            candidate.save()
            summary["created"] += 1
            return
        for field, value in values.items():
            setattr(current, field, value)
        current.full_clean()
        current.save(update_fields=[*values, "updated_at"])
        summary["updated"] += 1
