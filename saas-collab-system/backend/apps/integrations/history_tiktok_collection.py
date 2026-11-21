"""Store-local whole-day segments for TikTok collection backfills."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError


TIKTOK_DAY_RESOURCES = frozenset({"affiliate_order", "video_metrics"})


def _identity(job):
    store = job.store_authorization.store
    return {
        "authorization": job.store_authorization_id,
        "store": store.pk,
        "timezone": store.timezone,
    }


def _video_policy(job):
    policy = (job.sync_scope or {}).get("collection") or {}
    return {key: policy.get(key, default) for key, default in (("actor_id", None), ("page_size", 10))}


def _affiliate_policy(job):
    policy = (job.sync_scope or {}).get("affiliate") or {}
    return {key: policy.get(key) for key in ("snapshot_source", "site")}


def tiktok_day_scopes(job, start, end, now):
    identity = _identity(job)
    zone = ZoneInfo(identity["timezone"])
    today = now.astimezone(zone).date()
    if end >= today:
        raise ValidationError("补采须选择店铺当地已经结束的自然日。")
    if job.resource_type == "video_metrics" and start < today - timedelta(days=30):
        raise ValidationError("视频补采仅支持店铺当地最近 30 个完整自然日。")
    policy = _video_policy(job) if job.resource_type == "video_metrics" else _affiliate_policy(job)
    for index in range((end - start).days + 1):
        day = start + timedelta(days=index)
        yield {
            "time_from": int(datetime.combine(day, time.min, zone).timestamp()),
            "time_to": int(datetime.combine(day + timedelta(days=1), time.min, zone).timestamp()) - 1,
            "time_basis": "created",
            "tiktok_day_history": {**identity, "day": day.isoformat(), "policy": policy},
        }


def apply_tiktok_day_scope(candidate, scope):
    frozen = scope.get("tiktok_day_history")
    if not isinstance(frozen, dict) or any(frozen.get(key) != value for key, value in _identity(candidate).items()):
        raise ValidationError("补采分段缺少原店铺日期范围，或店铺授权绑定、时区已变更。")
    day = frozen["day"]
    effective = candidate.sync_scope or {}
    if candidate.resource_type == "affiliate_order":
        if frozen.get("policy") != _affiliate_policy(candidate):
            raise ValidationError("联盟订单的数据来源或站点已变更，请核对原补采范围。")
        candidate.sync_scope = {"affiliate": {**(effective.get("affiliate") or {}), "trial_days": [day]}}
    else:
        if frozen.get("policy") != _video_policy(candidate):
            raise ValidationError("视频补采的执行账号或分页配置已变更，请核对原补采范围。")
        candidate.sync_scope = {"collection": frozen["policy"]}
        candidate._history_video_day = date.fromisoformat(day)
    return candidate


def video_history_day_expired(job, scope, now):
    if job.resource_type != "video_metrics" or not job.store_authorization_id:
        return False
    frozen = scope.get("tiktok_day_history")
    if not isinstance(frozen, dict) or not isinstance(frozen.get("day"), str):
        return False
    identity = _identity(job)
    if any(frozen.get(key) != value for key, value in identity.items()):
        return False
    try:
        day = date.fromisoformat(frozen["day"])
        today = now.astimezone(ZoneInfo(identity["timezone"])).date()
    except (ValueError, KeyError, TypeError):
        return False
    return day < today - timedelta(days=30)
