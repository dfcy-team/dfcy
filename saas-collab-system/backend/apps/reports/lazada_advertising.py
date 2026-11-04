"""Read persisted SMAX facts. GET never calls Lazada or refreshes a token."""
from django.db.models import Count, F, Max, Min, Sum
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import paginated_data
from apps.integrations.lazada_advertising import _money
from apps.integrations.lazada_api_service import scoped_authorizations
from apps.integrations.models import LazadaAdvertisingDailySpend, LazadaApiSnapshot
from apps.permissions.ui_p6_scopes import analytics_dimensions_allowed, filter_analytics_queryset


class DailySpendSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)

    class Meta:
        model = LazadaAdvertisingDailySpend
        fields = ["id", "store_id", "store_name", "store_code", "report_date", "currency", "spend",
                  "report_timezone", "source_snapshot_id", "overview_snapshot_id", "updated_at"]


def daily_spend_report(request, values):
    if values["kind"] != "shop_daily" or not values.get("period_start") or not values.get("period_end"):
        raise ValidationError("Lazada 仅支持店铺日报，必须选择开始和结束日期。")
    start, end = values["period_start"], values["period_end"]
    if not 0 <= (end - start).days < 31:
        raise ValidationError("Lazada 广告日报每次查询连续 1～31 天。")
    if set(values) & {"store_ids", "platforms", "country", "storecountry", "region"}:
        raise ValidationError("Lazada 请使用店铺、币种和日期筛选。")
    scoped = filter_analytics_queryset(request.user, LazadaAdvertisingDailySpend.objects.filter(
        tenant=request.user.tenant, store__tenant=request.user.tenant, store__platform__platform_type="lazada",
        source_snapshot__tenant=request.user.tenant, source_snapshot__authorization__tenant=request.user.tenant,
        source_snapshot__authorization__store_id=F("store_id"),
        overview_snapshot__tenant=request.user.tenant, overview_snapshot__authorization_id=F("source_snapshot__authorization_id"),
    ), "analytics.view")
    stores = {row["store_id"]: row for row in scoped.order_by("store_id").values("store_id", "store__name", "store__code").distinct()}
    # Sync targets require their own integration scopes, not just analytics access.
    try:
        authorizations = scoped_authorizations(request.user, execute=True).filter(status="active")
        for auth in authorizations:
            dimensions = {"platform": "lazada", "store_id": auth.store_id, "country": auth.region.upper()}
            if analytics_dimensions_allowed(request.user, "analytics.view", dimensions):
                stores[auth.store_id] = {"store_id": auth.store_id, "store__name": auth.store.name,
                    "store__code": auth.store.code, "authorization_id": auth.pk}
    except PermissionDenied:
        pass
    rows = scoped.filter(report_date__range=(start, end))
    if values.get("store_id"):
        rows = rows.filter(store_id=values["store_id"])
    if values.get("currency"):
        rows = rows.filter(currency=values["currency"])
    summaries = []
    groups = list(rows.values("store_id", "store__name", "store__code", "currency", "report_timezone").annotate(
        spend=Sum("spend"), days=Count("id"), overview_min=Min("overview_snapshot_id"), overview_max=Max("overview_snapshot_id")))
    sources = LazadaApiSnapshot.objects.filter(tenant=request.user.tenant).in_bulk(
        {group["overview_min"] for group in groups if group["overview_min"] == group["overview_max"]})
    for group in groups:
        complete = group["days"] == (end - start).days + 1
        metrics = {}
        if complete and group["overview_min"] == group["overview_max"]:
            source = sources[group["overview_min"]]
            if source.parameters.get("startDate") == str(start) and source.parameters.get("endDate") == str(end):
                detail = source.response.get("result", {}).get("reportOverviewDetailDTO", {})
                for key in ("spend", "revenue", "clicks", "impressions", "unitsSold", "roi", "ctr", "cpc"):
                    if key in detail:
                        try:
                            metrics[key] = str(_money(detail[key]))
                        except ValidationError:
                            pass  # Missing/malformed optional metrics stay absent, not zero.
        summaries.append({key: value for key, value in group.items() if key not in {"overview_min", "overview_max"}} |
                         {"spend": format(group["spend"], ".4f"), "complete": complete, "expected_days": (end - start).days + 1,
                          "overview_metrics": metrics})
    result = paginated_data(request, rows.select_related("store").order_by("-report_date", "store_id"),
                            DailySpendSerializer, page=values["page"], page_size=values["page_size"])
    return {**result, "platform": "lazada", "solution": "Sponsored Max", "stores": list(stores.values()),
            "summaries": summaries, "notice": "报表花费不等于账单扣费；不同币种不合并，缺失日期不视为零。期间收入为 API revenue 字段，未认定等于后台 Guided GMV。"}
