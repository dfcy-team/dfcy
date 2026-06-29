# -*- coding: utf-8 -*-
"""广告户投放国家识别 + 导出店铺元数据（供入库）。"""
from __future__ import annotations

import configparser
import json
import re
from pathlib import Path
from typing import Any

from config import API_BASE

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHOP_CONFIG_INI = _PROJECT_ROOT / "config" / "店铺配置.ini"

TIMEZONE_REGION: dict[str, str] = {
    "Asia/Manila": "PH",
    "Asia/Bangkok": "TH",
    "Asia/Kuala_Lumpur": "MY",
    "Asia/Jakarta": "ID",
    "Asia/Singapore": "SG",
}

NAME_REGION_HINTS: tuple[tuple[str, str], ...] = (
    ("菲律宾", "PH"),
    ("马来", "MY"),
    ("泰国站", "TH"),
    ("泰国", "TH"),
    ("-PH", "PH"),
    ("-MY", "MY"),
    ("-TH", "TH"),
)

_REGION_SUFFIX_RE = re.compile(r"(PH|TH|MY)$", re.I)
_INI_SKIP = {"应用", "目录", "默认店", "批量启用", "导出文件名", "站点", "平台"}


def region_from_timezone(timezone: str) -> str:
    tz = (timezone or "").strip()
    if not tz:
        return ""
    if tz in TIMEZONE_REGION:
        return TIMEZONE_REGION[tz]
    for key, reg in TIMEZONE_REGION.items():
        if key.lower() == tz.lower():
            return reg
    return ""


def region_from_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return ""
    for hint, reg in NAME_REGION_HINTS:
        if hint in text:
            return reg
    m = _REGION_SUFFIX_RE.search(text.replace(" ", ""))
    if m:
        return m.group(1).upper()
    return ""


def detect_region(*, timezone: str = "", name: str = "") -> str:
    """优先时区，名称作兜底。"""
    reg = region_from_timezone(timezone)
    if reg:
        return reg
    return region_from_name(name)


def _shop_family_base(name: str) -> str:
    text = (name or "").strip()
    if len(text) >= 2 and text[-2:].upper() in ("PH", "TH", "MY"):
        return text[:-2]
    return text


def _read_shop_ini() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    if SHOP_CONFIG_INI.is_file():
        cp.read(SHOP_CONFIG_INI, encoding="utf-8")
    return cp


def lookup_ads_shop_config(ads_shop_label: str) -> dict[str, str] | None:
    """按广告绑定店名（店名 / 导出标签）精确匹配店铺配置。"""
    label = (ads_shop_label or "").strip()
    if not label:
        return None
    cp = _read_shop_ini()
    for sec in cp.sections():
        if sec in _INI_SKIP:
            continue
        shop_name = cp.get(sec, "店名", fallback="").strip()
        export_tag = cp.get(sec, "导出标签", fallback=shop_name).strip()
        if label not in (shop_name, export_tag):
            continue
        site = cp.get(sec, "站点", fallback="").strip().upper()
        if not site:
            site = region_from_name(shop_name or export_tag)
        mode = cp.get(sec, "模式", fallback="local").strip().lower()
        return {
            "shop_key": sec,
            "export_tag": export_tag or shop_name or label,
            "region": site,
            "shop_mode": mode,
        }
    return None


def is_local_ads_shop(ads_shop_label: str) -> bool:
    cfg = lookup_ads_shop_config(ads_shop_label)
    return bool(cfg and cfg.get("shop_mode") == "local")


def resolve_export_shop_meta(ads_shop_label: str, region: str) -> dict[str, str]:
    """解析入库用店铺简写与中文导出标签。

    本土店（模式=local）：固定用绑定店名，不按广告户时区换国家。
    跨境店（模式=cross_border）：按投放国家匹配同系列店铺（如 TKKJ1PH/TH/MY）。
    """
    label = (ads_shop_label or "").strip()
    local_cfg = lookup_ads_shop_config(label)
    if local_cfg and local_cfg.get("shop_mode") == "local":
        return {
            "shop_key": local_cfg["shop_key"],
            "export_tag": local_cfg["export_tag"],
            "region": local_cfg["region"],
            "shop_mode": "local",
        }

    reg = (region or "").strip().upper()
    if not reg and label:
        reg = region_from_name(label)
    base = _shop_family_base(label)

    cp = _read_shop_ini()
    for sec in cp.sections():
        if sec in _INI_SKIP:
            continue
        shop_name = cp.get(sec, "店名", fallback="").strip()
        export_tag = cp.get(sec, "导出标签", fallback=shop_name).strip()
        site = cp.get(sec, "站点", fallback="").strip().upper()
        if not shop_name or not site:
            continue
        if _shop_family_base(shop_name) == base and site == reg:
            return {
                "shop_key": sec,
                "export_tag": export_tag or shop_name,
                "region": reg,
                "shop_mode": "cross_border",
            }

    export_tag = f"{base}{reg}" if base and reg else label
    shop_key = label
    if reg and base:
        for sec in cp.sections():
            if sec in _INI_SKIP:
                continue
            if sec.upper().endswith(reg):
                shop_name = cp.get(sec, "店名", fallback="").strip()
                if shop_name and _shop_family_base(shop_name) == base:
                    shop_key = sec
                    export_tag = cp.get(sec, "导出标签", fallback=shop_name).strip() or export_tag
                    break
    return {
        "shop_key": shop_key,
        "export_tag": export_tag,
        "region": reg,
        "shop_mode": "cross_border",
    }


def fetch_advertisers_info(
    access_token: str,
    advertiser_ids: list[str],
    *,
    get_json,
) -> dict[str, dict[str, Any]]:
    """批量拉 advertiser/info，返回 {advertiser_id: info}。"""
    ids = [str(i).strip() for i in advertiser_ids if str(i).strip()]
    if not ids or not access_token:
        return {}
    out: dict[str, dict[str, Any]] = {}
    chunk_size = 50
    for i in range(0, len(ids), chunk_size):
        batch = ids[i : i + chunk_size]
        try:
            resp = get_json(
                f"{API_BASE}/advertiser/info/",
                access_token,
                {"advertiser_ids": json.dumps(batch)},
            )
        except Exception:
            continue
        items = (resp.get("data") or {}).get("list") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            aid = str(item.get("advertiser_id") or "").strip()
            if aid:
                out[aid] = item
    return out


def enrich_advertisers(
    advertisers: list[dict[str, Any]],
    access_token: str,
    *,
    get_json,
    ads_shop_label: str = "",
) -> list[dict[str, Any]]:
    """为每个广告户补充 timezone / currency / region。

    本土店：region 固定为绑定店铺站点（如 TIKTOK1号店PH → PH）。
    跨境店：region 按时区识别。
    """
    local_cfg = lookup_ads_shop_config(ads_shop_label)
    is_local = bool(local_cfg and local_cfg.get("shop_mode") == "local")
    ids = [str(a.get("advertiser_id") or "").strip() for a in advertisers]
    info_map = fetch_advertisers_info(access_token, ids, get_json=get_json)
    enriched: list[dict[str, Any]] = []
    for adv in advertisers:
        item = dict(adv)
        aid = str(item.get("advertiser_id") or "").strip()
        name = str(item.get("advertiser_name") or item.get("name") or "").strip()
        info = info_map.get(aid) or {}
        tz = str(info.get("display_timezone") or info.get("timezone") or item.get("timezone") or "")
        currency = str(info.get("currency") or item.get("currency") or "")
        if is_local:
            region = local_cfg.get("region") or region_from_name(ads_shop_label)
        else:
            region = detect_region(timezone=tz, name=name)
        if tz:
            item["timezone"] = tz
        if currency:
            item["currency"] = currency
        if region:
            item["region"] = region
        enriched.append(item)
    return enriched


def resolve_advertiser_meta(
    advertisers: list[dict[str, Any]] | None,
    advertiser_id: str,
    *,
    access_token: str = "",
    get_json=None,
    ads_shop_label: str = "",
) -> dict[str, str]:
    """解析单个广告户的 region / timezone / name。"""
    adv_id = (advertiser_id or "").strip()
    name = ""
    region = ""
    timezone = ""
    currency = ""
    local_cfg = lookup_ads_shop_config(ads_shop_label)
    is_local = bool(local_cfg and local_cfg.get("shop_mode") == "local")
    for adv in advertisers or []:
        if str(adv.get("advertiser_id") or "").strip() == adv_id:
            name = str(adv.get("advertiser_name") or adv.get("name") or "").strip()
            region = str(adv.get("region") or "").strip().upper()
            timezone = str(adv.get("timezone") or "").strip()
            currency = str(adv.get("currency") or "").strip()
            break
    if access_token and get_json and adv_id and (not timezone or not currency):
        info_map = fetch_advertisers_info(access_token, [adv_id], get_json=get_json)
        info = info_map.get(adv_id) or {}
        name = name or str(info.get("name") or "").strip()
        timezone = timezone or str(info.get("display_timezone") or info.get("timezone") or "")
        currency = currency or str(info.get("currency") or "")
    if is_local:
        region = local_cfg.get("region") or region_from_name(ads_shop_label)
    elif not region:
        region = detect_region(timezone=timezone, name=name)
    return {
        "advertiser_id": adv_id,
        "advertiser_name": name,
        "region": region,
        "timezone": timezone,
        "currency": currency,
    }
