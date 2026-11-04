"""Explicit manual SMAX reads using existing tokens; complete daily facts only."""
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .lazada_api_service import execute_operation, scoped_authorizations
from .models import IntegrationAuditLog, LazadaAdvertisingDailySpend, LazadaApiSnapshot


SITE_ZONES = {"PH": "Asia/Manila", "SG": "Asia/Singapore", "MY": "Asia/Kuala_Lumpur",
              "TH": "Asia/Bangkok", "VN": "Asia/Ho_Chi_Minh", "ID": "Asia/Jakarta"}
SITE_CURRENCIES = {"PH": "PHP", "SG": "SGD", "MY": "MYR", "TH": "THB", "VN": "VND", "ID": "IDR"}


def _period(payload):
    try:
        start, end = (date.fromisoformat(payload[key]) for key in ("startDate", "endDate"))
        if not 0 <= (end - start).days < 31:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValidationError("请选择连续 1～31 天，日期格式为 YYYY-MM-DD。") from None
    return start, end


def _money(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number < Decimal("10000000000000000"):
            raise ValueError
        if number != number.quantize(Decimal("0.0001")):
            raise ValueError
        return number
    except (ValueError, InvalidOperation):
        raise ValidationError("Lazada 广告报表包含缺失或无效的花费金额。") from None


def _body(snapshot, operation):
    if snapshot.status != "succeeded" or snapshot.operation != operation:
        raise ValidationError("不能导入失败或类型不符的广告快照。")
    response = snapshot.response
    body = response.get("result") if isinstance(response, dict) else None
    if (not isinstance(response, dict) or response.get("success") is not True or response.get("code") not in (0, "0")
            or not isinstance(body, dict) or body.get("success") is False):
        raise ValidationError("Lazada 广告报表未返回成功且完整的结果。")
    return body


def import_report_pair(*, actor, overview, daily):
    """Validate the entire capture before upserting; never sum overlapping captures."""
    auth = scoped_authorizations(actor, execute=True).filter(pk=daily.authorization_id).first()
    if (auth is None or auth.store.tenant_id != actor.tenant_id or auth.integration_config.tenant_id != actor.tenant_id
            or overview.tenant_id != actor.tenant_id or daily.tenant_id != actor.tenant_id
            or overview.authorization_id != daily.authorization_id):
        raise PermissionDenied("广告快照不在当前租户和店铺权限范围。")
    region, store = auth.region.upper(), auth.store
    if region not in SITE_ZONES or store.currency != SITE_CURRENCIES[region]:
        raise ValidationError("请核对 Lazada 店铺站点及币种配置。")
    start, end = _period(daily.parameters)
    if _period(overview.parameters) != (start, end) or daily.parameters.get("metricType") != 1:
        raise ValidationError("广告汇总与每日花费的日期或指标不一致。")
    if daily.parameters.get("useRtTable") is not False or overview.parameters.get("useRtTable") is not False:
        raise ValidationError("本次仅接入非实时日报。")
    body = _body(daily, "smax_ad_metrics")
    detail = _body(overview, "smax_ad_overview").get("reportOverviewDetailDTO")
    if not isinstance(detail, dict):
        raise ValidationError("广告期间汇总缺失。")
    expected_sum = _money(detail.get("spend"))
    dates, values = body.get("dateList"), body.get("metricList")
    days = (end - start).days + 1
    if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != days or len(values) != days or body.get("hourList"):
        raise ValidationError("广告日报日期或金额列表不完整。")
    rows = {}
    zone = ZoneInfo(SITE_ZONES[region])
    for stamp, value in zip(dates, values):
        if not re.fullmatch(r"[0-9]{13}", str(stamp)):
            raise ValidationError("广告日报时间戳无效。")
        local = datetime.fromtimestamp(int(stamp) / 1000, dt_timezone.utc).astimezone(zone)
        day = local.date()
        if not start <= day <= end or day in rows or any((local.hour, local.minute, local.second, local.microsecond)):
            raise ValidationError("广告日报日期重复、越界或不符合站点时区。")
        rows[day] = _money(value)
    actual_sum = sum(rows.values(), Decimal("0"))
    if actual_sum != expected_sum:
        raise ValidationError("每日广告花费合计与期间汇总不一致；本次未更新日报。")
    created = updated = 0
    with transaction.atomic():
        # Serialize overlapping captures, including a replacement authorization for the same store.
        from apps.masterdata.models import StoreMaster
        StoreMaster.objects.select_for_update().get(pk=store.pk, tenant_id=actor.tenant_id)
        for day, amount in sorted(rows.items()):
            existing = LazadaAdvertisingDailySpend.objects.select_for_update().filter(
                tenant_id=actor.tenant_id, store=store, report_date=day).first()
            if existing and existing.source_snapshot_id >= daily.pk:
                continue
            _, is_new = LazadaAdvertisingDailySpend.objects.update_or_create(
                tenant_id=actor.tenant_id, store=store, report_date=day,
                defaults={"spend": amount, "currency": store.currency, "report_timezone": SITE_ZONES[region],
                          "dimensions": {"platform": "lazada", "store_id": store.pk, "country": region},
                          "source_snapshot": daily, "overview_snapshot": overview})
            created += int(is_new)
            updated += int(not is_new)
        IntegrationAuditLog.objects.create(tenant_id=actor.tenant_id, actor=actor,
            integration_config=auth.integration_config, store_authorization=auth, action="lazada_ads.import",
            result="success", masked_detail={"overview_snapshot_id": overview.pk, "daily_snapshot_id": daily.pk,
                "days": days, "created": created, "updated": updated, "token_refresh": False})
    return {"status": "succeeded", "days": days, "daily_sum": str(actual_sum), "currency": store.currency,
            "created": created, "updated": updated, "overview_snapshot_id": overview.pk, "daily_snapshot_id": daily.pk}


def sync_advertising(*, actor, authorization_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"startDate", "endDate"}:
        raise ValidationError("采集参数只能包含 startDate 和 endDate；不能传入令牌或接口地址。")
    start, end = _period(payload)
    auth = scoped_authorizations(actor, execute=True).filter(pk=authorization_id).first()
    if auth is None:
        raise PermissionDenied("店铺授权不在权限范围。")
    region = auth.region.upper()
    if region not in SITE_ZONES or end >= timezone.now().astimezone(ZoneInfo(SITE_ZONES[region])).date():
        raise ValidationError("仅采集已结束的店铺站点日期，不采集今天或未来日期。")
    previous_end = start - timedelta(days=1)
    overview = execute_operation(actor=actor, authorization_id=auth.pk, name="smax_ad_overview", payload={
        **payload, "lastStartDate": str(previous_end - (end - start)), "lastEndDate": str(previous_end), "useRtTable": False})
    if overview["status"] != "succeeded":
        raise ValidationError("Lazada 广告汇总读取失败；未刷新授权，未更新日报。")
    daily = execute_operation(actor=actor, authorization_id=auth.pk, name="smax_ad_metrics", payload={
        **payload, "metricType": 1, "useRtTable": False})
    if daily["status"] != "succeeded":
        raise ValidationError("Lazada 广告日报读取失败；未刷新授权，未更新日报。")
    return import_report_pair(actor=actor, overview=LazadaApiSnapshot.objects.get(pk=overview["id"]),
                              daily=LazadaApiSnapshot.objects.get(pk=daily["id"]))
