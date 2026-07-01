# -*- coding: utf-8 -*-
"""TikTok Marketing API 报表拉取。"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from config import API_BASE
from oauth import get_access_token

_TIKTOK_ROOT = Path(__file__).resolve().parent.parent
_SHOP_DIR = _TIKTOK_ROOT / "shop"
_TEST_ENV_DIR = _TIKTOK_ROOT / "test_env"
_PRODUCT_POOL_DIR = Path(__file__).resolve().parent / "data"
_SHOP_PRODUCT_STATUSES = (None, "ACTIVATE", "DELETED", "FREEZE", "SELLER_DEACTIVATED", "PLATFORM_DEACTIVATED")

REPORT_URL = f"{API_BASE}/report/integrated/get/"
AD_URL = f"{API_BASE}/ad/get/"
CAMPAIGN_URL = f"{API_BASE}/campaign/get/"
GMV_MAX_STORE_URL = f"{API_BASE}/gmv_max/store/list/"
GMV_MAX_REPORT_URL = f"{API_BASE}/gmv_max/report/get/"
GMV_MAX_VIDEO_URL = f"{API_BASE}/gmv_max/video/get/"
GMV_MAX_CAMPAIGN_INFO_URL = f"{API_BASE}/campaign/gmv_max/info/"

GMV_MAX_CREATIVE_METRICS = [
    "cost",
    "orders",
    "cost_per_order",
    "gross_revenue",
    "roi",
    "product_impressions",
    "product_clicks",
    "product_click_rate",
    "ad_click_rate",
    "ad_conversion_rate",
    "ad_video_view_rate_2s",
    "ad_video_view_rate_6s",
    "ad_video_view_rate_p25",
    "ad_video_view_rate_p50",
    "ad_video_view_rate_p75",
    "ad_video_view_rate_p100",
]

# 创意级商品 GMV Max 报表维度（需配合 filtering 中的 campaign_ids / item_group_ids）
GMV_MAX_CREATIVE_DIMENSIONS = ["campaign_id", "item_group_id", "item_id"]
GMV_MAX_ITEM_DIMENSIONS = ["campaign_id", "item_group_id"]
GMV_MAX_CAMPAIGN_DIMENSIONS = ["campaign_id"]

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


def _find_shop_config_by_tag(shop_tag: str) -> Path | None:
    tag = (shop_tag or "").strip()
    if not tag:
        return None
    for cfg in _SHOP_DIR.glob("config_*.env"):
        try:
            text = cfg.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("TTS_EXPORT_SHOP_TAG=") and line.split("=", 1)[1].strip() == tag:
                return cfg
    return None


def _load_supplemental_product_ids(shop_tag: str | None = None) -> set[str]:
    """可选：从 data/gmv_max_product_pool_<tag>.json 读取官方对账补全的商品 ID。"""
    tag = (shop_tag or "").strip()
    if not tag:
        return set()
    safe = "".join(c if c not in '<>:"/\\|?*' else "_" for c in tag)
    path = _PRODUCT_POOL_DIR / f"gmv_max_product_pool_{safe}.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, list):
        return {str(x) for x in data if x}
    if isinstance(data, dict):
        items = data.get("product_ids") or data.get("item_group_ids") or []
        if isinstance(items, list):
            return {str(x) for x in items if x}
    return set()


def _fetch_shop_product_ids(shop_tag: str | None = None) -> set[str]:
    """店铺商品目录（含多状态并集），用于 GMV Max 跨商品零消耗行展开。"""
    tag = (shop_tag or "").strip()
    if not tag:
        return set()
    cfg_path = _find_shop_config_by_tag(tag)
    if cfg_path is None:
        return set()
    if not (_TEST_ENV_DIR / "tts_client.py").is_file():
        return set()
    if str(_TEST_ENV_DIR) not in sys.path:
        sys.path.insert(0, str(_TEST_ENV_DIR))
    try:
        from tts_client import TikTokShopClient, load_env
    except ImportError:
        return set()

    load_env(_SHOP_DIR / "app.env", override=True)
    load_env(cfg_path, override=True)
    import os

    app_key = os.environ.get("TTS_APP_KEY", "")
    app_secret = os.environ.get("TTS_APP_SECRET", "")
    token = os.environ.get("TTS_ACCESS_TOKEN", "")
    cipher = os.environ.get("TTS_SHOP_CIPHER", "")
    if not all((app_key, app_secret, token, cipher)):
        return set()

    client = TikTokShopClient(app_key, app_secret)
    pool: set[str] = set()
    for status in _SHOP_PRODUCT_STATUSES:
        page_token: str | None = None
        for _ in range(50):
            extra: dict[str, Any] = {"shop_cipher": cipher, "page_size": 100}
            if page_token:
                extra["page_token"] = page_token
            body: dict[str, Any] = {"status": status} if status else {}
            try:
                resp = client.post("/product/202309/products/search", token, body, extra)
            except Exception:
                break
            if resp.get("code") not in (0, None):
                break
            data = resp.get("data") or {}
            for product in data.get("products") or []:
                pid = str(product.get("id") or "")
                if pid:
                    pool.add(pid)
            page_token = data.get("next_page_token") or ""
            if not page_token:
                break
    return pool


def _collect_gmv_max_campaign_ids(
    advertiser_id: str,
    store_ids: list[str],
    start_date: str,
    end_date: str,
    access_token: str,
) -> list[str]:
    campaign_rows = _paginate_gmv_max_report(
        advertiser_id,
        store_ids,
        GMV_MAX_CAMPAIGN_DIMENSIONS,
        ["cost"],
        start_date,
        end_date,
        access_token,
    )
    campaign_ids: list[str] = []
    for row in campaign_rows:
        dims, _ = _row_dims_metrics(row)
        cid = str(dims.get("campaign_id") or "")
        if cid and cid not in campaign_ids:
            campaign_ids.append(cid)
    return campaign_ids


def _collect_gmv_max_campaign_ids_by_name_filters(
    advertiser_id: str,
    store_ids: list[str],
    start_date: str,
    end_date: str,
    access_token: str,
    name_filters: list[str],
) -> list[str]:
    """按 campaign_name 模糊筛选（与 Ads Manager 家族名 HYYL226 / HY107 等对齐）。"""
    campaign_ids: list[str] = []
    seen: set[str] = set()
    for name in name_filters:
        name = str(name or "").strip()
        if not name:
            continue
        rows = _paginate_gmv_max_report(
            advertiser_id,
            store_ids,
            GMV_MAX_CAMPAIGN_DIMENSIONS,
            ["cost"],
            start_date,
            end_date,
            access_token,
            filtering={"campaign_name": name},
        )
        for row in rows:
            dims, _ = _row_dims_metrics(row)
            cid = str(dims.get("campaign_id") or "")
            if cid and cid not in seen:
                seen.add(cid)
                campaign_ids.append(cid)
    return campaign_ids


def _build_gmv_max_item_group_pool(
    advertiser_id: str,
    store_ids: list[str],
    campaign_ids: list[str],
    start_date: str,
    end_date: str,
    access_token: str,
    campaign_info_cache: dict[str, dict[str, Any]],
    *,
    shop_tag: str | None = None,
    video_spus: set[str] | None = None,
    include_historical: bool = True,
) -> list[str]:
    """商品池 = 报表商品 ∪ 计划配置商品 ∪ 店铺目录 ∪ 视频 spu ∪ 可选补全文件。"""
    pool: set[str] = set()

    for cid in campaign_ids:
        item_rows = _paginate_gmv_max_report(
            advertiser_id,
            store_ids,
            GMV_MAX_ITEM_DIMENSIONS,
            ["cost"],
            start_date,
            end_date,
            access_token,
            filtering={"campaign_ids": [cid]},
        )
        for row in item_rows:
            dims, _ = _row_dims_metrics(row)
            igid = str(dims.get("item_group_id") or "")
            if igid:
                pool.add(igid)

        info = _fetch_gmv_max_campaign_info(advertiser_id, cid, access_token, campaign_info_cache)
        for spu in info.get("item_group_ids") or info.get("product_ids") or []:
            if spu:
                pool.add(str(spu))

    if include_historical and campaign_ids:
        try:
            from datetime import date, timedelta

            end_d = date.fromisoformat(end_date)
            hist_start = (end_d - timedelta(days=364)).isoformat()
            if hist_start < end_date:
                for cid in campaign_ids:
                    item_rows = _paginate_gmv_max_report(
                        advertiser_id,
                        store_ids,
                        GMV_MAX_ITEM_DIMENSIONS,
                        ["cost"],
                        hist_start,
                        end_date,
                        access_token,
                        filtering={"campaign_ids": [cid]},
                    )
                    for row in item_rows:
                        dims, _ = _row_dims_metrics(row)
                        igid = str(dims.get("item_group_id") or "")
                        if igid:
                            pool.add(igid)
        except (ValueError, RuntimeError):
            pass

    pool.update(_fetch_shop_product_ids(shop_tag))
    pool.update(_load_supplemental_product_ids(shop_tag))
    if video_spus:
        pool.update(video_spus)
    return sorted(pool)


def fetch_gmv_max_stores(advertiser_id: str, access_token: str | None = None) -> list[dict[str, Any]]:
    token = access_token or get_access_token()
    resp = _get_json(GMV_MAX_STORE_URL, token, {"advertiser_id": advertiser_id})
    data = resp.get("data") or {}
    stores = data.get("store_list") or data.get("list") or []
    if not isinstance(stores, list):
        return []
    return [s for s in stores if isinstance(s, dict)]


def _resolve_gmv_region(
    *,
    shop_tag: str | None = None,
    advertiser_id: str | None = None,
    access_token: str | None = None,
    advertisers: list[dict[str, Any]] | None = None,
    target_region: str | None = None,
) -> str:
    """解析 GMV Max 店铺筛选用的国家：本土店固定站点；跨境店优先广告户时区。"""
    reg = (target_region or "").strip().upper()
    if reg:
        return reg

    from advertiser_region import lookup_ads_shop_config, region_from_name, resolve_advertiser_meta

    label = (shop_tag or "").strip()
    local_cfg = lookup_ads_shop_config(label)
    if local_cfg and local_cfg.get("shop_mode") == "local":
        return (local_cfg.get("region") or region_from_name(label) or "").upper()

    adv = (advertiser_id or "").strip()
    token = access_token or (get_access_token(label) if label else get_access_token())
    if adv and token:
        meta = resolve_advertiser_meta(
            advertisers,
            adv,
            access_token=token,
            get_json=_get_json,
            ads_shop_label=label,
        )
        reg = (meta.get("region") or "").strip().upper()
        if reg:
            return reg

    return region_from_name(label)


def _select_gmv_max_stores(
    stores: list[dict[str, Any]],
    *,
    shop_tag: str | None = None,
    advertiser_id: str | None = None,
    access_token: str | None = None,
    advertisers: list[dict[str, Any]] | None = None,
    target_region: str | None = None,
) -> list[dict[str, Any]]:
    """GMV Max 报表 API 的 store_ids 每次最多 1 个；跨境户常绑多国店铺，需按投放国家筛选。"""
    if not stores:
        return []

    candidates = list(stores)
    region = _resolve_gmv_region(
        shop_tag=shop_tag,
        advertiser_id=advertiser_id,
        access_token=access_token,
        advertisers=advertisers,
        target_region=target_region,
    )
    if region:
        by_region = [
            s
            for s in candidates
            if region in [str(c).upper() for c in (s.get("targeting_region_codes") or [])]
        ]
        if by_region:
            candidates = by_region

    adv = (advertiser_id or "").strip()
    if adv:
        by_adv = [
            s
            for s in candidates
            if str((s.get("exclusive_authorized_advertiser_info") or {}).get("advertiser_id") or "").strip()
            == adv
        ]
        if by_adv:
            candidates = by_adv

    available = [s for s in candidates if s.get("is_gmv_max_available")]
    if available:
        candidates = available

    if len(candidates) > 1:
        # 仍有多店时取第一个（已按国家/专属户收窄）；避免 API 40002
        candidates = [candidates[0]]
    return candidates


def find_shop_exclusive_advertiser_id(
    advertisers: list[dict[str, Any]],
    access_token: str,
) -> str:
    """从 OAuth 广告主列表中解析店铺绑定的专属广告户（与卖家中心 GMV Max 面板同源）。"""
    authorized = {
        str(a.get("advertiser_id") or "").strip()
        for a in advertisers
        if str(a.get("advertiser_id") or "").strip()
    }
    if not authorized:
        return ""

    seen_exclusive: set[str] = set()
    for adv in advertisers:
        aid = str(adv.get("advertiser_id") or "").strip()
        if not aid:
            continue
        try:
            stores = fetch_gmv_max_stores(aid, access_token)
        except Exception:
            continue
        for store in stores:
            ex = store.get("exclusive_authorized_advertiser_info") or {}
            ex_id = str(ex.get("advertiser_id") or "").strip()
            if ex_id and ex_id in authorized:
                seen_exclusive.add(ex_id)

    if len(seen_exclusive) == 1:
        return next(iter(seen_exclusive))
    if len(seen_exclusive) > 1:
        # 多个店铺绑定时优先 GMV Max 可用户
        for adv in advertisers:
            aid = str(adv.get("advertiser_id") or "").strip()
            if aid not in seen_exclusive:
                continue
            try:
                stores = fetch_gmv_max_stores(aid, access_token)
            except Exception:
                continue
            if any(s.get("is_gmv_max_available") for s in stores):
                return aid
        return sorted(seen_exclusive)[0]
    return ""


def _paginate_gmv_max_report(
    advertiser_id: str,
    store_ids: list[str],
    dimensions: list[str],
    metrics: list[str],
    start_date: str,
    end_date: str,
    access_token: str,
    filtering: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not store_ids:
        raise RuntimeError("store_ids 不能为空")
    # TikTok GMV Max report: store_ids 最多 1 项（跨境广告户常返回 PH+TH 多店）
    api_store_ids = [store_ids[0]]

    items: list[dict[str, Any]] = []
    page = 1
    while True:
        params: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "store_ids": api_store_ids,
            "dimensions": dimensions,
            "metrics": metrics,
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": 1000,
        }
        if filtering:
            params["filtering"] = filtering
        resp = _get_json(GMV_MAX_REPORT_URL, access_token, params)
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


def _fetch_gmv_max_campaign_info(
    advertiser_id: str,
    campaign_id: str,
    access_token: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if campaign_id in cache:
        return cache[campaign_id]
    try:
        resp = _get_json(
            GMV_MAX_CAMPAIGN_INFO_URL,
            access_token,
            {"advertiser_id": advertiser_id, "campaign_id": campaign_id},
        )
        info = resp.get("data") or {}
    except Exception:
        info = {}
    cache[campaign_id] = info if isinstance(info, dict) else {}
    return cache[campaign_id]


def _shopping_ads_type(info: dict[str, Any]) -> str:
    return str(info.get("shopping_ads_type") or "").strip().upper()


def classify_gmv_max_campaign_ids(
    advertiser_id: str,
    store_ids: list[str],
    start_date: str,
    end_date: str,
    access_token: str,
    *,
    shopping_ads_type: str | None = None,
    campaign_ids: list[str] | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """按 shopping_ads_type（PRODUCT / LIVE）筛选 GMV Max 计划。"""
    ids = campaign_ids
    if ids is None:
        ids = _collect_gmv_max_campaign_ids(
            advertiser_id, store_ids, start_date, end_date, access_token
        )
    cache: dict[str, dict[str, Any]] = {}
    filtered: list[str] = []
    want = (shopping_ads_type or "").strip().upper()
    for cid in ids:
        info = _fetch_gmv_max_campaign_info(advertiser_id, cid, access_token, cache)
        t = _shopping_ads_type(info)
        if not want or t == want:
            filtered.append(cid)
    return filtered, cache


def fetch_gmv_max_creative_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    access_token: str | None = None,
    *,
    shop_tag: str | None = None,
    expand_all_products: bool = False,
    item_group_pool: list[str] | None = None,
    campaign_name_filters: list[str] | None = None,
    target_region: str | None = None,
    advertisers: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """拉取商品 GMV Max 创意级全量报表。

    expand_all_products=True 时按「计划 × 商品池 × 创意」展开（阶段 B，对齐官方零消耗跨商品行）。
    商品池默认含：当日/历史报表商品、计划配置、店铺目录、视频 spu、可选补全 JSON。
    """
    token = access_token or get_access_token()
    all_stores = fetch_gmv_max_stores(advertiser_id, token)
    stores = _select_gmv_max_stores(
        all_stores,
        shop_tag=shop_tag,
        advertiser_id=advertiser_id,
        access_token=token,
        advertisers=advertisers,
        target_region=target_region,
    )
    store_ids = [str(s.get("store_id") or s.get("id") or "") for s in stores]
    store_ids = [sid for sid in store_ids if sid]
    if not store_ids:
        hint = ""
        resolved = _resolve_gmv_region(
            shop_tag=shop_tag,
            advertiser_id=advertiser_id,
            access_token=token,
            advertisers=advertisers,
            target_region=target_region,
        )
        if len(all_stores) > 1:
            hint = f"（广告户下共 {len(all_stores)} 个 GMV Max 店铺"
            if resolved:
                hint += f"，未能匹配投放国家 {resolved}"
            elif shop_tag:
                hint += f"，未能识别店名/时区对应国家"
            hint += "）"
        raise RuntimeError(f"未找到 GMV Max 店铺，请确认广告主已授权 TikTok Shop{hint}")

    if campaign_name_filters:
        raw_campaign_ids = _collect_gmv_max_campaign_ids_by_name_filters(
            advertiser_id, store_ids, start_date, end_date, token, campaign_name_filters
        )
    else:
        raw_campaign_ids = _collect_gmv_max_campaign_ids(
            advertiser_id, store_ids, start_date, end_date, token
        )
    campaign_ids, campaign_info_cache = classify_gmv_max_campaign_ids(
        advertiser_id,
        store_ids,
        start_date,
        end_date,
        token,
        shopping_ads_type="PRODUCT",
        campaign_ids=raw_campaign_ids,
    )
    campaign_infos: list[dict[str, Any]] = [
        campaign_info_cache[cid] for cid in campaign_ids if cid in campaign_info_cache
    ]

    pool = item_group_pool
    if pool is None and expand_all_products:
        pool = _build_gmv_max_item_group_pool(
            advertiser_id,
            store_ids,
            campaign_ids,
            start_date,
            end_date,
            token,
            campaign_info_cache,
            shop_tag=shop_tag,
        )

    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for cid in campaign_ids:
        info = campaign_info_cache.get(cid) or {}
        campaign_name = str(info.get("campaign_name") or cid)
        status = info.get("operation_status")

        if expand_all_products and pool:
            item_group_ids = pool
            filtering = {"campaign_ids": [cid], "item_group_ids": item_group_ids}
            creative_rows = _paginate_gmv_max_report(
                advertiser_id,
                store_ids,
                GMV_MAX_CREATIVE_DIMENSIONS,
                GMV_MAX_CREATIVE_METRICS,
                start_date,
                end_date,
                token,
                filtering=filtering,
            )
            for row in creative_rows:
                dims, metrics = _row_dims_metrics(row)
                dims = dict(dims)
                igid = str(dims.get("item_group_id") or "")
                item_id = str(dims.get("item_id") or "")
                key = (cid, igid, item_id)
                if key in seen:
                    continue
                seen.add(key)
                dims.setdefault("campaign_id", cid)
                if igid:
                    dims.setdefault("item_group_id", igid)
                dims["campaign_name"] = campaign_name
                if status:
                    dims.setdefault("campaign_status", status)
                out.append({"dimensions": dims, "metrics": metrics})
            continue

        item_rows = _paginate_gmv_max_report(
            advertiser_id,
            store_ids,
            GMV_MAX_ITEM_DIMENSIONS,
            ["cost"],
            start_date,
            end_date,
            token,
            filtering={"campaign_ids": [cid]},
        )
        item_group_ids = []
        for row in item_rows:
            dims, _ = _row_dims_metrics(row)
            igid = str(dims.get("item_group_id") or "")
            if igid and igid not in item_group_ids:
                item_group_ids.append(igid)

        for igid in item_group_ids:
            creative_rows = _paginate_gmv_max_report(
                advertiser_id,
                store_ids,
                GMV_MAX_CREATIVE_DIMENSIONS,
                GMV_MAX_CREATIVE_METRICS,
                start_date,
                end_date,
                token,
                filtering={"campaign_ids": [cid], "item_group_ids": [igid]},
            )
            for row in creative_rows:
                dims, metrics = _row_dims_metrics(row)
                dims = dict(dims)
                igid = str(dims.get("item_group_id") or igid)
                item_id = str(dims.get("item_id") or "")
                key = (cid, igid, item_id)
                if key in seen:
                    continue
                seen.add(key)
                dims.setdefault("campaign_id", cid)
                dims.setdefault("item_group_id", igid)
                dims["campaign_name"] = campaign_name
                if status:
                    dims.setdefault("campaign_status", status)
                out.append({"dimensions": dims, "metrics": metrics})
    return out, campaign_infos


def _normalize_gmv_video_item(raw: dict[str, Any]) -> dict[str, Any]:
    info = raw.get("identity_info") or {}
    vi = raw.get("video_info") or {}
    identity_type = str(info.get("identity_type") or "")
    auth_map = {
        "AUTH_CODE": "Affiliate mass authorization",
        "TTS_TT": "Authorized creatives",
        "BC_AUTH_TT": "Authorized creatives",
    }
    item_id = str(raw.get("item_id") or "")
    return {
        "item_id": item_id,
        "video_id": str(vi.get("video_id") or item_id),
        "tiktok_item_id": item_id,
        "text": raw.get("text") or "",
        "title": raw.get("text") or "",
        "video_title": raw.get("text") or "",
        "display_name": info.get("display_name") or "",
        "identity_name": info.get("display_name") or "",
        "identity_type": identity_type,
        "authorization_type": auth_map.get(identity_type, identity_type or "N/A"),
        "spu_id_list": raw.get("spu_id_list") or [],
        "create_time": raw.get("create_time") or raw.get("posted_time") or "-",
    }


def _fetch_gmv_max_video_index(
    advertiser_id: str,
    stores: list[dict[str, Any]],
    access_token: str,
    campaign_infos: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}

    def _ingest(v: dict[str, Any]) -> None:
        norm = _normalize_gmv_video_item(v)
        for key in (norm.get("item_id"), norm.get("video_id"), norm.get("tiktok_item_id")):
            if key:
                index[str(key)] = norm

    def _paginate_videos(params: dict[str, Any]) -> None:
        page = 1
        while True:
            req = dict(params)
            req["page"] = page
            req.setdefault("page_size", 50)
            resp = _get_json(GMV_MAX_VIDEO_URL, access_token, req)
            data = resp.get("data") or {}
            batch = data.get("item_list") or data.get("list") or data.get("video_list") or []
            if not isinstance(batch, list):
                break
            for v in batch:
                if isinstance(v, dict):
                    _ingest(v)
            info = data.get("page_info") or {}
            total_page = int(info.get("total_page") or 1)
            if page >= total_page or not batch:
                break
            page += 1

    campaigns = campaign_infos or []
    if campaigns:
        for info in campaigns:
            identity_list = [
                ident
                for ident in (info.get("identity_list") or [])
                if isinstance(ident, dict) and ident.get("identity_id")
            ]
            if not identity_list:
                continue
            spu_ids = [
                str(spu)
                for spu in (info.get("item_group_ids") or info.get("product_ids") or [])
                if spu
            ]
            for store in stores:
                store_id = str(store.get("store_id") or store.get("id") or "")
                bc_id = str(store.get("store_authorized_bc_id") or store.get("bc_id") or "")
                if not store_id or not bc_id:
                    continue
                base = {
                    "advertiser_id": advertiser_id,
                    "store_id": store_id,
                    "store_authorized_bc_id": bc_id,
                    "need_auth_code_video": True,
                    "identity_list": identity_list,
                }
                _paginate_videos(base)
                for spu_id in spu_ids:
                    _paginate_videos(
                        {
                            **base,
                            "custom_posts_eligible": True,
                            "spu_id_list": [spu_id],
                        }
                    )
        return index

    for store in stores:
        store_id = str(store.get("store_id") or store.get("id") or "")
        bc_id = str(store.get("store_authorized_bc_id") or store.get("bc_id") or "")
        if not store_id or not bc_id:
            continue
        _paginate_videos(
            {
                "advertiser_id": advertiser_id,
                "store_id": store_id,
                "store_authorized_bc_id": bc_id,
                "need_auth_code_video": True,
            }
        )
    return index


def _row_dims_metrics(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    dims = row.get("dimensions") or {}
    metrics = row.get("metrics") or {}
    if dims or metrics:
        return dims, metrics
    metric_keys = set(GMV_MAX_CREATIVE_METRICS)
    dims = {k: v for k, v in row.items() if k not in metric_keys}
    metrics = {k: v for k, v in row.items() if k in metric_keys}
    return dims, metrics


def _fmt_roi(val: Any) -> str:
    if val is None or val == "" or val == "-":
        return "0.00"
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_rate_metric(val: Any) -> str:
    if val is None or val == "" or val == "-":
        return "-"
    try:
        f = float(val)
        if f <= 0:
            return "-"
        return f"{f:.4f}"
    except (TypeError, ValueError):
        return str(val)


def _gmv_creative_type_label(raw: Any) -> str:
    s = str(raw or "").upper()
    if "CARD" in s or "PRODUCT_CARD" in s:
        return "Product card"
    if "VIDEO" in s:
        return "Video"
    return str(raw) if raw not in (None, "") else "-"


def _gmv_status_label(raw: Any) -> str:
    s = str(raw or "").upper()
    if "DELIVER" in s or "ENABLE" in s or s == "STATUS_DELIVERY_OK":
        return "Delivering"
    if "DISABLE" in s or "PAUSE" in s:
        return "Paused"
    return str(raw) if raw not in (None, "") else "-"


def _is_product_card_row(dims: dict[str, Any], creative_type: str) -> bool:
    item_id = str(dims.get("item_id") or "")
    if item_id == "-1":
        return True
    if "PRODUCT" in creative_type.upper() and "CARD" in creative_type.upper():
        return True
    ct = str(dims.get("creative_type") or "").upper()
    return "CARD" in ct or ct == "PRODUCT_CARD"


def build_gmv_max_creative_rows(
    report_rows: list[dict[str, Any]],
    video_index: dict[str, dict[str, Any]] | None = None,
    currency: str = "PHP",
) -> list[list[Any]]:
    videos = video_index or {}
    out: list[list[Any]] = []
    for row in report_rows:
        dims, metrics = _row_dims_metrics(row)
        item_id = str(dims.get("item_id") or "")
        item_group_id = str(dims.get("item_group_id") or dims.get("product_id") or dims.get("spu_id") or "")
        campaign_id = str(dims.get("campaign_id") or "")
        campaign_name = str(dims.get("campaign_name") or dims.get("campaign") or campaign_id or "-")
        creative_type = _gmv_creative_type_label(dims.get("creative_type"))
        is_card = _is_product_card_row(dims, creative_type)
        if is_card:
            creative_type = "Product card"

        video = videos.get(item_id) or videos.get(str(dims.get("video_id") or ""))
        if not is_card and video:
            creative_type = "Video"

        video_id = "N/A"
        video_title = "-"
        tiktok_account = "-"
        time_posted = "-"
        auth_type = "N/A"
        status = _gmv_status_label(
            dims.get("creative_delivery_status")
            or dims.get("status")
            or dims.get("campaign_status")
            or (video or {}).get("creative_delivery_status")
            or (video or {}).get("status")
        )

        if not is_card and video:
            video_id = str(
                video.get("item_id")
                or video.get("tiktok_item_id")
                or item_id
                or video.get("video_id")
                or "N/A"
            )
            video_title = (
                video.get("text")
                or video.get("title")
                or video.get("video_title")
                or video.get("ad_text")
                or "-"
            )
            tiktok_account = (
                video.get("identity_name")
                or video.get("display_name")
                or video.get("tiktok_account")
                or video.get("nickname")
                or "-"
            )
            time_posted = (
                video.get("create_time")
                or video.get("time_posted")
                or video.get("posted_time")
                or "-"
            )
            auth_type = (
                video.get("authorization_type")
                or video.get("auth_type")
                or video.get("creative_authorization_type")
                or "N/A"
            )
            status = _gmv_status_label(
                video.get("creative_delivery_status")
                or video.get("status")
                or status
            )
        elif not is_card and item_id and item_id != "-1":
            creative_type = "Video"
            video_id = item_id

        has_video_metrics = not is_card and creative_type == "Video"
        row_currency = str(metrics.get("currency") or currency or "PHP")
        out.append(
            [
                campaign_name,
                campaign_id or "-",
                item_group_id or "-",
                creative_type,
                video_title,
                video_id,
                tiktok_account,
                time_posted,
                status,
                auth_type,
                _fmt_money(metrics.get("cost")),
                int(_num(metrics.get("orders"))),
                _fmt_money(metrics.get("cost_per_order")),
                _fmt_money(metrics.get("gross_revenue")),
                _fmt_roi(metrics.get("roi")),
                int(_num(metrics.get("product_impressions"))),
                int(_num(metrics.get("product_clicks"))),
                _fmt_rate_metric(metrics.get("product_click_rate")),
                _fmt_rate_metric(metrics.get("ad_conversion_rate")),
                _fmt_rate_metric(metrics.get("ad_video_view_rate_2s")) if has_video_metrics else "-",
                _fmt_rate_metric(metrics.get("ad_video_view_rate_6s")) if has_video_metrics else "-",
                _fmt_rate_metric(metrics.get("ad_video_view_rate_p25")) if has_video_metrics else "-",
                _fmt_rate_metric(metrics.get("ad_video_view_rate_p50")) if has_video_metrics else "-",
                _fmt_rate_metric(metrics.get("ad_video_view_rate_p75")) if has_video_metrics else "-",
                _fmt_rate_metric(metrics.get("ad_video_view_rate_p100")) if has_video_metrics else "-",
                row_currency,
            ]
        )
    return out


def fetch_product_creative_rows(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    access_token: str | None = None,
    currency: str = "PHP",
    shop_tag: str | None = None,
    expand_all_products: bool = False,
    campaign_name_filters: list[str] | None = None,
    target_region: str | None = None,
    advertisers: list[dict[str, Any]] | None = None,
) -> list[list[Any]]:
    """商品 GMV Max 创意报表（阶段 A：有消耗与汇总对齐官方；阶段 B 需 expand_all_products=True）。"""
    token = access_token or get_access_token()
    resolved_tag = (shop_tag or "").strip()
    if not resolved_tag:
        try:
            from oauth import _active_shop_label

            resolved_tag = (_active_shop_label.get() or "").strip()
        except ImportError:
            resolved_tag = ""

    if advertisers is None and resolved_tag:
        try:
            from oauth import load_shop_token

            tok = load_shop_token(resolved_tag)
            if tok:
                advertisers = tok.get("advertisers")
        except ImportError:
            pass

    all_stores = fetch_gmv_max_stores(advertiser_id, token)
    stores = _select_gmv_max_stores(
        all_stores,
        shop_tag=resolved_tag or None,
        advertiser_id=advertiser_id,
        access_token=token,
        advertisers=advertisers,
        target_region=target_region,
    )
    report, campaign_infos = fetch_gmv_max_creative_report(
        advertiser_id,
        start_date,
        end_date,
        token,
        shop_tag=resolved_tag or None,
        expand_all_products=expand_all_products,
        campaign_name_filters=campaign_name_filters,
        target_region=target_region,
        advertisers=advertisers,
    )
    video_index = _fetch_gmv_max_video_index(advertiser_id, stores, token, campaign_infos)
    return build_gmv_max_creative_rows(report, video_index, currency=currency)


GMV_MAX_LIVE_CAMPAIGN_METRICS = [
    "cost",
    "orders",
    "cost_per_order",
    "gross_revenue",
    "roi",
]

GMV_MAX_LIVE_ROOM_DIMENSIONS = ["campaign_id", "room_id"]
GMV_MAX_LIVE_ROOM_METRICS = [
    "cost",
    "net_cost",
    "orders",
    "cost_per_order",
    "gross_revenue",
    "roi",
    "live_views",
    "cost_per_live_view",
    "10_second_live_views",
    "cost_per_10_second_live_view",
    "live_follows",
]


def _live_room_label(dims: dict[str, Any], campaign_name: str) -> str:
    for key in ("room_name", "live_room_name", "live_name", "title"):
        val = dims.get(key)
        if val not in (None, "", "-"):
            return str(val)
    return campaign_name


def _live_room_start(dims: dict[str, Any], fallback: Any = "-") -> str:
    for key in ("room_start_time", "live_start_time", "start_time", "stat_time"):
        val = dims.get(key)
        if val not in (None, "", "-"):
            return str(val)
    return str(fallback or "-")


def _build_gmv_max_live_row(
    dims: dict[str, Any],
    metrics: dict[str, Any],
    *,
    campaign_name: str,
    campaign_id: str,
    campaign_info: dict[str, Any],
    currency: str,
) -> list[Any]:
    room_name = _live_room_label(dims, campaign_name)
    orders = int(_num(metrics.get("orders")))
    spend = _num(metrics.get("cost"))
    net_spend = _num(metrics.get("net_cost") or metrics.get("cost"))
    revenue = _num(metrics.get("gross_revenue"))
    live_views = int(_num(metrics.get("live_views")))
    live_10s = int(_num(metrics.get("10_second_live_views")))
    row_currency = str(metrics.get("currency") or currency or "USD")
    return [
        room_name,
        _live_room_start(dims, campaign_info.get("schedule_start_time")),
        _gmv_status_label(campaign_info.get("operation_status")),
        campaign_name,
        campaign_id or "-",
        _fmt_money(spend),
        _fmt_money(net_spend),
        orders,
        orders,
        _fmt_money(metrics.get("cost_per_order")),
        _fmt_money(revenue),
        _fmt_money(revenue),
        _fmt_roi(metrics.get("roi")),
        live_views if live_views > 0 else "-",
        _fmt_money(metrics.get("cost_per_live_view"))
        if metrics.get("cost_per_live_view") not in (None, "", "-")
        else (_fmt_money(spend / live_views) if live_views > 0 else "-"),
        live_10s if live_10s > 0 else "-",
        _fmt_money(metrics.get("cost_per_10_second_live_view"))
        if metrics.get("cost_per_10_second_live_view") not in (None, "", "-")
        else (_fmt_money(spend / live_10s) if live_10s > 0 else "-"),
        int(_num(metrics.get("live_follows"))) if _num(metrics.get("live_follows")) > 0 else "-",
        row_currency,
    ]


def fetch_gmv_max_live_rows(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    access_token: str | None = None,
    *,
    currency: str = "USD",
    shop_tag: str | None = None,
    target_region: str | None = None,
    advertisers: list[dict[str, Any]] | None = None,
) -> list[list[Any]]:
    """GMV Max 直播广告（shopping_ads_type=LIVE）按直播场次导出，对齐卖家中心「直播广告」。"""
    token = access_token or get_access_token()
    all_stores = fetch_gmv_max_stores(advertiser_id, token)
    stores = _select_gmv_max_stores(
        all_stores,
        shop_tag=shop_tag,
        advertiser_id=advertiser_id,
        access_token=token,
        advertisers=advertisers,
        target_region=target_region,
    )
    store_ids = [str(s.get("store_id") or s.get("id") or "") for s in stores]
    store_ids = [sid for sid in store_ids if sid]
    if not store_ids:
        raise RuntimeError("未找到 GMV Max 店铺，请确认广告主已授权 TikTok Shop")

    live_ids, cache = classify_gmv_max_campaign_ids(
        advertiser_id,
        store_ids,
        start_date,
        end_date,
        token,
        shopping_ads_type="LIVE",
    )
    if not live_ids:
        return []

    out: list[list[Any]] = []
    try:
        report_rows = _paginate_gmv_max_report(
            advertiser_id,
            store_ids,
            GMV_MAX_LIVE_ROOM_DIMENSIONS,
            GMV_MAX_LIVE_ROOM_METRICS,
            start_date,
            end_date,
            token,
            filtering={"campaign_ids": live_ids},
        )
        live_set = set(live_ids)
        for row in report_rows:
            dims, metrics = _row_dims_metrics(row)
            cid = str(dims.get("campaign_id") or "")
            if cid not in live_set:
                continue
            info = cache.get(cid) or {}
            campaign_name = str(info.get("campaign_name") or cid)
            out.append(
                _build_gmv_max_live_row(
                    dims,
                    metrics,
                    campaign_name=campaign_name,
                    campaign_id=cid,
                    campaign_info=info,
                    currency=currency,
                )
            )
        if out:
            return out
    except Exception:
        pass

    live_set = set(live_ids)
    report_rows = _paginate_gmv_max_report(
        advertiser_id,
        store_ids,
        GMV_MAX_CAMPAIGN_DIMENSIONS,
        GMV_MAX_LIVE_CAMPAIGN_METRICS,
        start_date,
        end_date,
        token,
    )
    for row in report_rows:
        dims, metrics = _row_dims_metrics(row)
        cid = str(dims.get("campaign_id") or "")
        if cid not in live_set:
            continue
        info = cache.get(cid) or {}
        campaign_name = str(info.get("campaign_name") or cid)
        out.append(
            _build_gmv_max_live_row(
                dims,
                metrics,
                campaign_name=campaign_name,
                campaign_id=cid,
                campaign_info=info,
                currency=currency,
            )
        )
    return out


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
