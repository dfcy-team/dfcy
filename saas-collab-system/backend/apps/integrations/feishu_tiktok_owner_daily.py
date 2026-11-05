"""Owner-scoped rolling seven-day TikTok Feishu digest."""
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.influencers.models import TikTokVideoDailyMetric
from apps.integrations.gmv_max_read import stored_days
from apps.integrations.models import TikTokAdsAdvertiserMapping
from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission, check_stored_business_read_permission
from apps.permissions.ui_p6_scopes import analytics_dimensions_allowed
from apps.permissions.ui_p2_scopes import require_all_scope
from apps.reports.datasets import query_dataset
from apps.reports.advertising_dataset import advertising_store_scope
from types import SimpleNamespace


def _change(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) * Decimal("100") / previous


def _fmt(value, places=2):
    return "未提供" if value is None else f"{value:,.{places}f}"


def _window_for_store(store):
    try:
        today = timezone.localtime(timezone.now(), ZoneInfo(store.timezone or "UTC")).date()
    except (ZoneInfoNotFoundError, ValueError):
        today = timezone.localdate()
    end = today - timedelta(days=1)
    start = end - timedelta(days=6)
    previous_end = start - timedelta(days=1)
    return start, end, previous_end - timedelta(days=6), previous_end


def _authorized_video_stores(user, stores):
    """Use the staged video report's registered two-action read policy."""
    if not (check_user_permission(user, "influencers.outreach.view")
            and check_user_permission(user, "influencers.fulfillment.view")):
        return set()
    try:
        require_all_scope(user, "influencers.outreach.view")
        require_all_scope(user, "influencers.fulfillment.view")
    except PermissionDenied:
        return set()
    return {store.pk for store in stores}


def _authorized_ads_mappings(user, stores):
    if not check_user_permission(user, "analytics.view"):
        return []
    _, allowed_store_ids = advertising_store_scope(user)
    store_ids = {s.pk for s in stores} & set(allowed_store_ids)
    mappings = TikTokAdsAdvertiserMapping.objects.filter(
        tenant_id=user.tenant_id, store_id__in=store_ids, enabled=True,
        store__tenant_id=user.tenant_id, store__platform__platform_type="tiktok",
        integration_config__tenant_id=user.tenant_id, integration_config__platform="tiktok",
    ).select_related("store", "integration_config")
    return list(mappings)


def build_tiktok_owner_report(user, filters, *, delivery_store_ids):
    if not check_user_permission(user, "sales_management.view"):
        raise PermissionDenied("需要销售查看权限。")
    stores = list(StoreMaster.objects.filter(
        tenant_id=user.tenant_id, platform__platform_type="tiktok", operator_id=user.pk,
        **({"pk__in": set(delivery_store_ids)} if delivery_store_ids is not None else {}),
    ).order_by("pk"))
    if not stores:
        return {"title": "TikTok 店铺经营日报", "summary": "当前负责人范围内没有 TikTok 店铺。",
                "sections": [], "suppress_delivery": True}

    scope = {store.pk: _window_for_store(store) for store in stores}
    # Query the canonical sales dataset per store so it applies the same business_date,
    # non-cancelled order and tenant permission semantics as the report screen.
    sales = {}
    for store in stores:
        start, end, prior_start, prior_end = scope[store.pk]
        for label, first, last in (("current", start, end), ("previous", prior_start, prior_end)):
            response = query_dataset(SimpleNamespace(user=user), {
                "dataset": "sales", "dimensions": ["store_id", "currency"],
                "metrics": ["valid_order_count", "gross_sales"],
                "filters": {"date_from": first.isoformat(), "date_to": last.isoformat(),
                            "platform": "tiktok", "store_id": store.pk},
            }, use_cache=False, delivery_store_ids=[store.pk])
            sales[(store.pk, label)] = response.get("rows", [])

    video_ids = _authorized_video_stores(user, stores)
    ads_mappings = _authorized_ads_mappings(user, stores)
    mapping_by_store = {}
    for mapping in ads_mappings:
        mapping_by_store.setdefault(mapping.store_id, []).append(mapping)
    video_rows = {}
    for store in stores:
        if store.pk not in video_ids:
            continue
        start, end, prior_start, prior_end = scope[store.pk]
        values = TikTokVideoDailyMetric.objects.filter(
            tenant_id=user.tenant_id, store_id=store.pk,
            metric_date__range=(prior_start, end), quality_status__in=["passed", "degraded"],
        ).values("metric_date", "currency", "video_id").annotate(gmv=Sum("reported_gmv"), views=Sum("views"))
        video_rows[store.pk] = list(values)

    ads_rows = {}
    ads_revenue_allowed = check_stored_business_read_permission(user, "integrations.store.view")
    if ads_mappings:
        names = {mapping.pk: mapping.store.name for mapping in ads_mappings}
        for store in stores:
            mappings = mapping_by_store.get(store.pk, [])
            if not mappings:
                continue
            start, end, prior_start, prior_end = scope[store.pk]
            observed = stored_days(user, mappings, names, prior_start, end)
            ads_rows[store.pk] = [row for row in observed if row.get("relationship_verified")]

    output = []
    links = []
    periods = []
    for store in stores:
        start, end, prior_start, prior_end = scope[store.pk]
        periods.append((start, end, prior_start, prior_end))
        output.append(f"**{store.name} · {store.country_code or '国家未设置'}**")
        current = sales[(store.pk, "current")]
        previous = sales[(store.pk, "previous")]
        currencies = sorted({r.get("currency") for r in current + previous if r.get("currency")})
        if not currencies:
            output.append("订单 GMV：本期暂无已入库数据（按业务日期，不含取消订单）。")
        for currency in currencies:
            now = next((r for r in current if r.get("currency") == currency), None)
            before = next((r for r in previous if r.get("currency") == currency), None)
            amount = Decimal(str(now["gross_sales"])) if now and now.get("gross_sales") is not None else None
            old_amount = Decimal(str(before["gross_sales"])) if before and before.get("gross_sales") is not None else None
            orders = now.get("valid_order_count") if now else None
            old_orders = before.get("valid_order_count") if before else None
            delta = _change(amount, old_amount)
            order_delta = _change(Decimal(orders), Decimal(old_orders)) if orders is not None and old_orders is not None else None
            delta_text = "未提供对比" if delta is None else f"{delta:+.2f}%"
            order_delta_text = "未提供对比" if order_delta is None else f"{order_delta:+.2f}%"
            output.append(f"GMV {_fmt(amount)} {currency}（较前7天 {delta_text}）；非取消订单 {_fmt(orders, 0)} 单（{order_delta_text}）")

        vids = video_rows.get(store.pk)
        if vids is None:
            output.append("短视频：当前账号无视频数据权限。")
        else:
            current_vids = [r for r in vids if start <= r["metric_date"] <= end]
            prior_vids = [r for r in vids if prior_start <= r["metric_date"] <= prior_end]
            currencies = sorted({r["currency"] for r in current_vids + prior_vids})
            for currency in currencies:
                cur_currency = [r for r in current_vids if r["currency"] == currency and r["gmv"] is not None]
                old_currency = [r for r in prior_vids if r["currency"] == currency and r["gmv"] is not None]
                cur_total = sum((r["gmv"] for r in cur_currency), Decimal(0)) if cur_currency else None
                old_total = sum((r["gmv"] for r in old_currency), Decimal(0)) if old_currency else None
                video_delta = _change(cur_total, old_total)
                current_coverage = len({r["metric_date"] for r in cur_currency})
                previous_coverage = len({r["metric_date"] for r in old_currency})
                if current_coverage == 7 and previous_coverage == 7 and video_delta is not None:
                    comparison = f"较前7天 {video_delta:+.2f}%"
                else:
                    comparison = f"双周期采集不足，暂不比较（本期 {current_coverage}/7 天；对比期 {previous_coverage}/7 天）"
                output.append(f"短视频 GMV {_fmt(cur_total)} {currency}（{comparison}）")
                current_by_video = {}
                previous_by_video = {}
                for row in cur_currency:
                    current_by_video[row["video_id"]] = current_by_video.get(row["video_id"], Decimal(0)) + row["gmv"]
                for row in old_currency:
                    previous_by_video[row["video_id"]] = previous_by_video.get(row["video_id"], Decimal(0)) + row["gmv"]
                drops = [(video_id, before - current_by_video.get(video_id, Decimal(0)))
                         for video_id, before in previous_by_video.items()]
                declines = sorted((item for item in drops if item[1] > 0), key=lambda item: item[1], reverse=True)
                net_decline = old_total - cur_total if old_total is not None and cur_total is not None else None
                if declines and net_decline and net_decline > 0 and current_coverage == 7 and previous_coverage == 7:
                    top_id, top_drop = declines[0]
                    contribution = top_drop * Decimal(100) / net_decline
                    output.append(f"Top1 下滑贡献：视频 {top_id} 净下滑 {_fmt(top_drop)} {currency}（占视频净下滑额 {contribution:.2f}%）")
                elif net_decline is not None and net_decline > 0:
                    output.append("Top1 下滑贡献：双周期覆盖不足，暂不计算。")
                top = TikTokVideoDailyMetric.objects.filter(
                tenant_id=user.tenant_id, store_id=store.pk,
                    metric_date__range=(start, end), currency=currency,
                    quality_status__in=["passed", "degraded"],
                ).values("video_id", "video__external_video_id", "video__title", "currency").annotate(
                    gmv=Sum("reported_gmv"), views=Sum("views")
                ).order_by("-gmv")
                top_rows = list(top[:3])
                for index, item in enumerate(top_rows, 1):
                    if item["gmv"] is None:
                        continue
                    name = item["video__title"] or item["video__external_video_id"]
                    output.append(f"Top 视频 {index}. {name[:80]} · {_fmt(item['gmv'])} {currency} · 播放 {_fmt(item['views'], 0)} 次")

        ads = [r for r in ads_rows.get(store.pk, []) if start.isoformat() <= r["date"] <= end.isoformat()]
        if store.pk not in ads_rows:
            output.append("GMV Max：当前账号无广告数据权限或映射。")
        elif not ads:
            output.append("GMV Max：近7天无已验证采集数据。")
        else:
            by_currency = {}
            for row in ads:
                group = by_currency.setdefault(row["currency"], {
                    "cost": Decimal(0), "cost_days": 0, "revenue": Decimal(0),
                    "revenue_days": 0, "days": 0, "cost_complete": True,
                    "revenue_complete": True,
                })
                if row.get("cost") is not None:
                    group["cost"] += Decimal(str(row["cost"]))
                    group["cost_days"] += 1
                else:
                    group["cost_complete"] = False
                if row.get("gross_revenue") is not None:
                    group["revenue"] += Decimal(str(row["gross_revenue"]))
                    group["revenue_days"] += 1
                elif ads_revenue_allowed:
                    group["revenue_complete"] = False
                group["days"] += 1
            for currency, data in sorted(by_currency.items()):
                cost_text = _fmt(data["cost"]) if data["cost_days"] else "未提供"
                cost_coverage = f"花费采集 {data['cost_days']}/7 天"
                if ads_revenue_allowed:
                    revenue_text = _fmt(data["revenue"]) if data["revenue_days"] else "未提供"
                    roas = data["revenue"] / data["cost"] if data["cost_complete"] and data["revenue_complete"] and data["revenue_days"] and data["cost_days"] and data["cost"] else None
                    output.append(f"GMV Max 花费 {cost_text} {currency} · 已授权 GMV {revenue_text} {currency} · ROAS {_fmt(roas, 2)} · {cost_coverage}；快照 {data['days']}/7 天")
                else:
                    output.append(f"GMV Max 花费 {cost_text} {currency} · GMV/ROAS 无读取授权，未展示 · {cost_coverage}；快照 {data['days']}/7 天")

        links.append((f"/reports/basic?tab=analysis&feishu_dataset=sales&date_from={start}&date_to={end}&store_id={store.pk}", f"{store.name} 销售详情"))
        if store.pk in video_ids:
            links.append((f"/influencers?platform=tiktok&store_id={store.pk}", f"{store.name} 视频数据详情"))
        if mapping_by_store.get(store.pk):
            links.append((f"/marketing/advertising/tiktok/overview?store_id={store.pk}", f"{store.name} GMV Max 详情"))
    if periods:
        first = periods[0]
        period_line = f"数据周期 {first[0]} 至 {first[1]} · 对比 {first[2]} 至 {first[3]}；各店按店铺时区统计。"
    else:
        period_line = ""
    return {"report_type": "tiktok_owner_daily", "title": "TikTok 店铺近7天经营表现",
            "headline": period_line, "summary": "\n".join(output), "sections": [],
            "detail_links": links, "period": {"start": min(p[0] for p in periods).isoformat(),
                "end": max(p[1] for p in periods).isoformat()} if periods else {}}
