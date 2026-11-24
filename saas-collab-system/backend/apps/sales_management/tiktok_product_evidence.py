"""On-demand TikTok product traffic evidence for sales diagnosis."""
from datetime import date, timedelta

from django.db import DatabaseError, transaction
from django.db.models import Case, Count, F, Q, Sum, When


READ_CODES = ("influencers.outreach.view", "influencers.fulfillment.view")


def _has_access(user, store_id):
    from apps.influencers.scopes import filter_queryset
    from apps.masterdata.models import StoreMaster
    from apps.permissions.services import check_user_permission

    stores = StoreMaster.objects.filter(tenant_id=user.tenant_id, pk=store_id)
    for code in READ_CODES:
        if not check_user_permission(user, code):
            return False
        stores = filter_queryset(user, stores, code)
    return stores.exists()


def video_section(user, *, store_id, product_id, date_from, date_to):
    """Return associated-video totals, never product-attributed video totals."""
    denied = {"title": "视频与达人线索", "scope": "无达人模块读取权限或店铺不在授权范围", "status": "unavailable", "metrics": []}
    if not _has_access(user, store_id):
        return denied
    from apps.influencers.models import TikTokShopVideo, TikTokVideoDailyMetric

    videos = TikTokShopVideo.objects.filter(
        tenant_id=user.tenant_id, store_id=store_id,
        video_products__tenant_id=user.tenant_id,
        video_products__external_product_id=str(product_id),
        video_products__parse_status="parsed",
    ).distinct()
    if not videos.exists():
        return {"title": "视频与达人线索", "scope": "该商品没有已关联视频", "status": "missing", "metrics": []}
    metrics = TikTokVideoDailyMetric.objects.filter(
        tenant_id=user.tenant_id, store_id=store_id, video_id__in=videos.values("pk"),
        metric_date__gte=date_from, metric_date__lt=date_to + timedelta(days=1),
        quality_status__in=("passed", "degraded"),
    )
    aggregate = metrics.aggregate(
        impressions=Sum("product_impressions"), clicks=Sum("product_clicks"),
        rows=Count("id"), days=Count("metric_date", distinct=True),
        views=Sum("views"), likes=Sum("likes"), comments=Sum("comments"), shares=Sum("shares"),
        paired_impressions=Sum(Case(When(Q(product_impressions__isnull=False) & Q(product_clicks__isnull=False), then=F("product_impressions")), default=None)),
        paired_clicks=Sum(Case(When(Q(product_impressions__isnull=False) & Q(product_clicks__isnull=False), then=F("product_clicks")), default=None)),
    )
    video_count = videos.values("pk").distinct().count()
    creators = set()
    for creator_id, open_id, username in videos.values_list("creator_id", "creator_open_id", "creator_username_normalized").distinct().iterator():
        identity = open_id or creator_id or username
        if identity:
            creators.add(identity.casefold())
    exposed = aggregate["impressions"]
    clicked = aggregate["clicks"]
    ctr = aggregate["paired_clicks"] / aggregate["paired_impressions"] if aggregate["paired_impressions"] else None
    populated = aggregate["rows"] > 0
    return {
        "title": "视频与达人线索",
        "scope": "关联视频整体表现；多商品视频未分摊到本商品；仅汇总已通过及降级记录，可能不完整",
        "status": "available" if populated else "missing",
        "message": f"覆盖 {aggregate['days']} 天；含降级记录，指标可能不完整" if populated else "该区间无可用视频指标",
        "metrics": [
            {"label": "关联视频数", "value": video_count, "note": "已入库关联数，非所选周期新增数"},
            {"label": "关联达人数", "value": len(creators) if creators else None, "note": "已识别达人数，非所选周期新增数"},
            {"label": "播放量", "value": aggregate["views"]},
            {"label": "点赞数", "value": aggregate["likes"]},
            {"label": "评论数", "value": aggregate["comments"]},
            {"label": "分享数", "value": aggregate["shares"]},
            {"label": "关联视频商品曝光", "value": exposed},
            {"label": "关联视频商品点击", "value": clicked},
            {"label": "关联视频商品点击率", "value": ctr, "unit": "percent", "note": "仅曝光和点击双字段齐全的记录计算"},
        ],
    }


def product_traffic_section(user, *, store_id, product_id, date_from, date_to):
    if not _has_access(user, store_id):
        return {"title": "商品整体流量", "scope": "无达人模块读取权限或店铺不在授权范围", "status": "unavailable", "metrics": []}
    try:
        from apps.influencers.models import TikTokProductPerformanceSnapshot
        start = date_from if isinstance(date_from, date) else date.fromisoformat(str(date_from))
        end = date_to if isinstance(date_to, date) else date.fromisoformat(str(date_to))
        with transaction.atomic():
            snapshot = TikTokProductPerformanceSnapshot.objects.filter(
                tenant_id=user.tenant_id, store_id=store_id, product_id=str(product_id),
                window_start=start, window_end=end + timedelta(days=1),
            ).order_by("-source_updated_at", "-id").first()
    except (ImportError, DatabaseError):
        snapshot = None
    if snapshot is None:
        return {"title": "商品整体流量", "scope": "该日期区间暂无商品整体流量快照", "status": "not_collected", "metrics": []}
    data = snapshot.metrics if isinstance(snapshot.metrics, dict) else {}
    labels = (
        ("商品曝光", "product_impressions", "count"), ("曝光人数", "unique_product_impressions", "count"),
        ("商品点击", "product_clicks", "count"), ("点击人数", "unique_clicks", "count"),
        ("点击率", "ctr", "percent"), ("加购人数", "add_cart_users", "count"),
        ("加购率", "unique_atc_rate", "percent"), ("点击下单率", "click_order_rate", "percent"),
        ("预估购买客户数", "estimated_customers", "count"),
    )
    metrics = [{"label": label, "value": data.get(key), "unit": unit} for label, key, unit in labels]
    channel_names = {
        "seller_product_card_performance": "卖家商品卡",
        "seller_video_performance": "卖家视频", "seller_live_performance": "卖家直播",
        "affiliate_total_performance": "达人整体", "affiliate_video_performance": "达人视频",
        "affiliate_live_performance": "达人直播",
        "shop_tab_performance": "Shop Tab",
    }
    channel_fields = {
        "product_impressions": ("曝光", "count"), "unique_product_impressions": ("曝光人数", "count"),
        "product_clicks": ("点击", "count"), "unique_clicks": ("点击人数", "count"),
        "ctr": ("点击率", "percent"), "add_cart_users": ("加购人数", "count"),
        "unique_atc_rate": ("加购率", "percent"), "click_order_rate": ("点击下单率", "percent"),
        "shop_tab_product_impressions": ("曝光", "count"),
        "shop_tab_product_clicks": ("点击", "count"), "shop_tab_ctr": ("点击率", "percent"),
        "shop_tab_ctor_sku": ("SKU 点击下单率", "percent"),
    }
    for key, label in channel_names.items():
        channel = data.get(key)
        if isinstance(channel, dict):
            for field, (field_label, unit) in channel_fields.items():
                value = channel.get(field)
                if value is not None:
                    metrics.append({"label": f"{label} {field_label}", "value": value, "unit": unit})
    return {
        "title": "商品整体流量", "scope": "TikTok Shop 商品维度，日期窗口精确匹配；去重口径以平台返回为准；父子渠道可能重叠，不合计",
        "status": "available", "source_updated_at": snapshot.source_updated_at.isoformat() if snapshot.source_updated_at else None, "metrics": metrics,
    }
