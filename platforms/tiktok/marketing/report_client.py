# -*- coding: utf-8 -*-
"""TikTok Marketing API 报表拉取。"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from config import API_BASE
from oauth import get_access_token

REPORT_URL = f"{API_BASE}/report/integrated/get/"
AD_URL = f"{API_BASE}/ad/get/"
CAMPAIGN_URL = f"{API_BASE}/campaign/get/"

CREATIVE_METRICS = [
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "complete_payment",
    "total_onsite_shopping_value",
    "onsite_shopping_roas",
    "cost_per_complete_payment",
    "conversion_rate",
    "currency",
    "video_watched_2s",
    "video_watched_6s",
    "video_views_p25",
    "video_views_p50",
    "video_views_p75",
    "video_views_p100",
]

LIVE_METRICS = [
    "spend",
    "cash_spend",
    "complete_payment",
    "total_onsite_shopping_value",
    "onsite_shopping_roas",
    "cost_per_complete_payment",
    "live_views",
    "live_effective_views",
    "follows",
    "currency",
]


def _get_json(url: str, access_token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    q: dict[str, str] = {}
    for k, v in (params or {}).items():
        if isinstance(v, (list, dict)):
            q[k] = json.dumps(v, ensure_ascii=False)
        elif v is not None:
            q[k] = str(v)
    full = f"{url}?{urllib.parse.urlencode(q)}" if q else url
    req = urllib.request.Request(full, headers={"Access-Token": access_token, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if parsed.get("code") not in (0, None):
        msg = parsed.get("message") or parsed.get("msg") or str(parsed.get("code"))
        raise RuntimeError(f"{msg} (code={parsed.get('code')})")
    return parsed


def _paginate_list(url: str, access_token: str, base_params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        params = dict(base_params)
        params["page"] = page
        params.setdefault("page_size", 1000)
        resp = _get_json(url, access_token, params)
        data = resp.get("data") or {}
        batch = data.get("list") or []
        if not isinstance(batch, list):
            break
        items.extend(batch)
        info = data.get("page_info") or {}
        total_page = int(info.get("total_page") or 1)
        if page >= total_page:
            break
        page += 1
    return items


def fetch_all_ads(advertiser_id: str, access_token: str | None = None) -> dict[str, dict[str, Any]]:
    token = access_token or get_access_token()
    ads = _paginate_list(
        AD_URL,
        token,
        {"advertiser_id": advertiser_id, "page_size": 1000},
    )
    out: dict[str, dict[str, Any]] = {}
    for row in ads:
        ad_id = str(row.get("ad_id") or "")
        if ad_id:
            out[ad_id] = row
    return out


def fetch_all_campaigns(advertiser_id: str, access_token: str | None = None) -> dict[str, dict[str, Any]]:
    token = access_token or get_access_token()
    camps = _paginate_list(
        CAMPAIGN_URL,
        token,
        {"advertiser_id": advertiser_id, "page_size": 1000},
    )
    out: dict[str, dict[str, Any]] = {}
    for row in camps:
        cid = str(row.get("campaign_id") or "")
        if cid:
            out[cid] = row
    return out


def fetch_ad_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    token = access_token or get_access_token()
    return _paginate_list(
        REPORT_URL,
        token,
        {
            "advertiser_id": advertiser_id,
            "report_type": "BASIC",
            "service_type": "AUCTION",
            "data_level": "AUCTION_AD",
            "dimensions": ["ad_id"],
            "metrics": CREATIVE_METRICS,
            "start_date": start_date,
            "end_date": end_date,
            "page_size": 1000,
        },
    )


def fetch_campaign_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    access_token: str | None = None,
) -> list[dict[str, Any]]:
    token = access_token or get_access_token()
    return _paginate_list(
        REPORT_URL,
        token,
        {
            "advertiser_id": advertiser_id,
            "report_type": "BASIC",
            "service_type": "AUCTION",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": ["campaign_id"],
            "metrics": LIVE_METRICS,
            "start_date": start_date,
            "end_date": end_date,
            "page_size": 1000,
        },
    )


def _num(val: Any) -> float:
    if val is None or val == "" or val == "-":
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _rate(part: Any, whole: Any) -> str:
    p, w = _num(part), _num(whole)
    if w <= 0:
        return "-"
    return f"{p / w:.4f}"


def _fmt_money(val: Any) -> str:
    if val is None or val == "" or val == "-":
        return "0.000"
    try:
        return f"{float(val):.3f}"
    except (TypeError, ValueError):
        return str(val)


def _status_cn(ad: dict[str, Any]) -> str:
    st = (ad.get("operation_status") or ad.get("secondary_status") or "").upper()
    if "ENABLE" in st:
        return "投放中"
    if "DISABLE" in st:
        return "已暂停"
    return st or "-"


def _creative_type_cn(ad: dict[str, Any]) -> str:
    fmt = (ad.get("ad_format") or "").upper()
    if "VIDEO" in fmt:
        return "视频"
    if "CAROUSEL" in fmt or ad.get("image_ids"):
        return "商品图片"
    return fmt or "-"


def _auth_type_cn(ad: dict[str, Any]) -> str:
    if ad.get("creative_authorized") is True:
        return "已授权素材"
    if ad.get("identity_type"):
        return str(ad.get("identity_type"))
    return "N/A"


def build_creative_rows(
    report_rows: list[dict[str, Any]],
    ads: dict[str, dict[str, Any]],
) -> list[list[Any]]:
    out: list[list[Any]] = []
    for row in report_rows:
        dims = row.get("dimensions") or {}
        metrics = row.get("metrics") or {}
        ad_id = str(dims.get("ad_id") or "")
        ad = ads.get(ad_id, {})
        imps = metrics.get("impressions")
        out.append(
            [
                ad.get("campaign_name") or ad.get("adgroup_name") or "-",
                ad.get("campaign_id") or "-",
                ad.get("item_group_id") or ad.get("product_id") or ad.get("tiktok_item_id") or "-",
                _creative_type_cn(ad),
                ad.get("ad_text") or ad.get("ad_name") or "-",
                ad.get("tiktok_item_id") or ad.get("video_id") or "N/A",
                ad.get("display_name") or ad.get("app_name") or "-",
                ad.get("create_time") or "-",
                _status_cn(ad),
                _auth_type_cn(ad),
                _fmt_money(metrics.get("spend")),
                int(_num(metrics.get("complete_payment"))),
                _fmt_money(metrics.get("cost_per_complete_payment")),
                _fmt_money(metrics.get("total_onsite_shopping_value")),
                _fmt_money(metrics.get("onsite_shopping_roas")),
                int(_num(imps)),
                int(_num(metrics.get("clicks"))),
                metrics.get("ctr") if metrics.get("ctr") not in (None, "") else _rate(metrics.get("clicks"), imps),
                metrics.get("conversion_rate") if metrics.get("conversion_rate") not in (None, "") else "-",
                _rate(metrics.get("video_watched_2s"), imps),
                _rate(metrics.get("video_watched_6s"), imps),
                _rate(metrics.get("video_views_p25"), imps),
                _rate(metrics.get("video_views_p50"), imps),
                _rate(metrics.get("video_views_p75"), imps),
                _rate(metrics.get("video_views_p100"), imps),
                metrics.get("currency") or "PHP",
            ]
        )
    return out


def build_live_rows(
    report_rows: list[dict[str, Any]],
    campaigns: dict[str, dict[str, Any]],
) -> list[list[Any]]:
    out: list[list[Any]] = []
    for row in report_rows:
        dims = row.get("dimensions") or {}
        metrics = row.get("metrics") or {}
        cid = str(dims.get("campaign_id") or "")
        camp = campaigns.get(cid, {})
        live_views = _num(metrics.get("live_views"))
        live_10s = _num(metrics.get("live_effective_views"))
        spend = _num(metrics.get("spend"))
        if live_views <= 0 and live_10s <= 0:
            obj = (camp.get("objective_type") or "").upper()
            if "LIVE" not in obj and "直播" not in (camp.get("campaign_name") or ""):
                continue
        orders = int(_num(metrics.get("complete_payment")))
        revenue = _num(metrics.get("total_onsite_shopping_value"))
        roi = metrics.get("onsite_shopping_roas")
        out.append(
            [
                camp.get("campaign_name") or f"直播-{cid}",
                camp.get("create_time") or "-",
                _status_cn(camp),
                camp.get("campaign_name") or "-",
                cid or "-",
                _fmt_money(metrics.get("spend")),
                _fmt_money(metrics.get("cash_spend") or metrics.get("spend")),
                orders,
                orders,
                _fmt_money(metrics.get("cost_per_complete_payment")),
                _fmt_money(revenue),
                _fmt_money(revenue),
                _fmt_money(roi),
                int(live_views),
                _fmt_money(spend / live_views) if live_views > 0 else "-",
                int(live_10s),
                _fmt_money(spend / live_10s) if live_10s > 0 else "-",
                int(_num(metrics.get("follows"))),
                metrics.get("currency") or "PHP",
            ]
        )
    return out
