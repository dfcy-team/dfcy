"""Stored advertising facts only, with explicit provider/attribution boundaries."""
from decimal import Decimal, InvalidOperation

from django.db.models import F
from django.db.models.fields.json import KeyTextTransform

from .models import ShopeeAdvertisingRecord, TikTokAdsDailySpend
from .readonly_sales_inventory import related_scope


METRICS = (
    "impression", "clicks", "ctr", "expense", "cpc", "direct_order", "broad_order",
    "direct_gmv", "broad_gmv", "direct_item_sold", "broad_item_sold",
    "direct_roas", "broad_roas", "direct_conversions", "broad_conversions",
    "cost_per_conversion", "direct_order_amount", "broad_order_amount", "direct_roi", "broad_roi",
    "direct_cir", "broad_cir", "cr", "direct_cr", "cpdc",
)
FIELDS = ("id", "store_id", "kind", "report_date", "campaign_id", "currency", "report_timezone", "updated_at") + METRICS
CONTRACTS = {
    "advertising_overview": (ShopeeAdvertisingRecord, FIELDS),
    "advertising_performance": (ShopeeAdvertisingRecord, FIELDS),
    "advertising_tiktok_spend": (TikTokAdsDailySpend, ("id", "mapping_id", "store_id", "advertiser_id", "date", "spend", "currency", "fetched_at")),
}
NOTES = {
    "advertising_overview": "Shopee 店铺日报；报表消耗不等于扣费。直接与广泛归因不可相加，最近 7 天可能回补。缺失指标返回 null。",
    "advertising_performance": "Shopee 活动日报；与店铺日报重叠，不可重复汇总。直接与广泛归因不可相加。缺失指标返回 null。",
    "advertising_tiktok_spend": "TikTok BASIC/AUCTION_CAMPAIGN 每日花费，仅此报表范围，不代表全部广告花费。",
}
PENDING_REASONS = {
    "advertising_reconciliation": "待接入广告账户实际扣费账单、财务入账记录及其关联规则；现有广告报表消耗不能替代扣费或对账结果。",
}


def query(resource, tenant_id):
    model, _ = CONTRACTS[resource]
    qs = model.objects.filter(tenant_id=tenant_id)
    if resource == "advertising_tiktok_spend":
        return related_scope(qs, tenant_id, "mapping", "mapping__store", "mapping__integration_config").annotate(
            store_id=F("mapping__store_id"), advertiser_id=F("mapping__advertiser_id"))
    qs = related_scope(qs, tenant_id, "store", "source_run", "source_run__sync_job")
    return qs.filter(kind="shop_daily" if resource == "advertising_overview" else "campaign_daily").annotate(
        **{metric: KeyTextTransform(metric, "data") for metric in METRICS})


def transform(resource, item):
    if resource == "advertising_tiktok_spend":
        return
    for metric in METRICS:
        raw = item[metric]
        try:
            value = Decimal(str(raw))
            item[metric] = str(value) if value.is_finite() and value >= 0 and not isinstance(raw, bool) else None
        except (InvalidOperation, TypeError, ValueError):
            item[metric] = None
