"""Freeze TikTok BASIC spend history windows into the shared history outbox."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .ads_sync import load_mapping, resolve_scope
from .retention_policy import RETENTION_START


def tiktok_ads_history_scopes(job, payload, now=None):
    mapping = load_mapping(job)
    now = now or timezone.now()
    try:
        zone = ZoneInfo(mapping.timezone)
        account_today = now.astimezone(zone).date()
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValidationError("TikTok Ads 广告户时区无效。") from None
    try:
        start = date.fromisoformat(payload["start_date"])
        end = date.fromisoformat(payload["end_date"])
        if str(start) != payload["start_date"] or str(end) != payload["end_date"]:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValidationError("TikTok Ads 历史补采日期须为 YYYY-MM-DD。") from None
    if start > end or end >= account_today or start < RETENTION_START:
        raise ValidationError(f"TikTok Ads 历史补采须使用广告户时区已完成日期；日期范围不能早于 {RETENTION_START}。")

    scopes, cursor, sequence = [], start, 1
    while cursor <= end:
        stop = min(cursor + timedelta(days=6), end)
        query = {"mode": "range", "start_at": cursor.isoformat(), "end_at": stop.isoformat()}
        resolved = resolve_scope(mapping, {"query": query}, now=now)
        scope_start = int(datetime.combine(cursor, time.min, zone).timestamp())
        scope_end = int(datetime.combine(stop, time(23, 59, 59), zone).timestamp())
        scopes.append({"time_from": scope_start, "time_to": scope_end, "time_basis": "created",
                       "page_size": 100, "report_scope": "AUCTION_CAMPAIGN",
                       "history_query": query, "ads_scope": resolved})
        cursor, sequence = stop + timedelta(days=1), sequence + 1
    return scopes
