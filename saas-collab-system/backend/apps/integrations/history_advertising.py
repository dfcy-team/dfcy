"""Freeze store-local advertising periods into the existing history outbox."""
from calendar import monthrange
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .shopee_advertising import SITE_ZONES, advertising_sync_scope

HISTORICAL_DATASETS = {"campaign_daily", "shop_daily", "campaign_hourly", "shop_hourly", "gms_campaign", "gms_item"}


def advertising_history_scopes(job, payload, now=None):
    auth = job.store_authorization
    if not auth or auth.region.upper() not in SITE_ZONES:
        raise ValidationError("广告补采须绑定支持站点的店铺广告授权。")
    try:
        start, end = date.fromisoformat(payload["start_date"]), date.fromisoformat(payload["end_date"])
        if str(start) != payload["start_date"] or str(end) != payload["end_date"]:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise ValidationError("广告补采日期须为 YYYY-MM-DD。")
    today = (now or timezone.now()).astimezone(ZoneInfo(SITE_ZONES[auth.region.upper()])).date()
    year, month = divmod(today.year * 12 + today.month - 1 - 6, 12)
    oldest = max(date(2025, 1, 1), date(year, month + 1, min(today.day, monthrange(year, month + 1)[1])))
    if start < oldest or end > today or (end - start).days < 1:
        raise ValidationError(f"广告补采须选择店铺站点最近六个月内至少 2 天，最早 {oldest}，结束不能晚于 {today}。")
    datasets = payload.get("advertising_datasets", ["campaign_daily", "shop_daily"])
    if not isinstance(datasets, list) or not datasets or any(not isinstance(x, str) or x not in HISTORICAL_DATASETS for x in datasets):
        raise ValidationError("广告历史补采只支持按日期的效果报表；余额、广告设置、开关和推荐商品是当前快照。")
    result, cursor = [], start
    while cursor <= end:
        remaining = (end - cursor).days + 1
        length = min(30, remaining)
        if remaining - length == 1:
            length -= 1
        stop = cursor + timedelta(days=length - 1)
        query = {"mode": "range", "start_at": str(cursor), "end_at": str(stop), "advertising_datasets": sorted(set(datasets))}
        result.append({**advertising_sync_scope(job.integration_config, {"query": query}, auth), "history_query": query})
        cursor = stop + timedelta(days=1)
    return result
