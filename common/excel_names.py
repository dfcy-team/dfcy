# -*- coding: utf-8 -*-
"""Excel 导出中文文件名 / 工作表名（与 店铺配置.ini [导出文件名] 对齐）。"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

DEFAULT_ANALYTICS_STEMS: dict[str, str] = {
    "product": "产品数据表",
    "sku": "商品sku信息",
    "video": "视频总和明细",
    "shop": "店铺数据",
}

FINANCE_API_LABELS: dict[str, str] = {
    "statements": "获取对账单",
    "statement_tx": "按对账单获取交易记录",
    "order_tx": "按订单获取交易记录",
    "payments": "获取付款记录",
    "withdrawals": "获取提现记录",
    "unsettled": "获取未结算交易",
}

DEFAULT_FINANCE_STEMS: dict[str, str] = dict(FINANCE_API_LABELS)

ANALYTICS_CACHE_STEM: dict[str, str] = {
    "product": "product_list",
    "sku": "sku_list",
    "video": "video_detail",
    "shop": "shop_key_metrics",
}

ANALYTICS_SHEET_TITLES: dict[str, str] = {
    "product": "产品数据表",
    "sku": "商品sku信息",
    "video": "视频总和明细",
    "shop": "店铺数据",
}

FINANCE_SHEET_TITLES: dict[str, str] = {
    k: v[:31] for k, v in FINANCE_API_LABELS.items()
}

# 与 导入总配置.ini [店铺财务] 键名对应
FINANCE_DIR_KEYS: dict[str, str] = {
    "statements": "对账单目录",
    "statement_tx": "按对账单交易目录",
    "order_tx": "按订单交易目录",
    "payments": "付款记录目录",
    "withdrawals": "提现记录目录",
    "unsettled": "未结算交易目录",
}

FINANCE_DIR_LEGACY_INI_KEYS: dict[str, str] = {
    "对账单目录": "结算单目录",
    "按对账单交易目录": "结算明细目录",
    "按订单交易目录": "订单交易目录",
    "付款记录目录": "付款目录",
    "提现记录目录": "提现目录",
    "未结算交易目录": "未结算目录",
}

FINANCE_STEM_LEGACY: dict[str, list[str]] = {
    "statements": ["结算单"],
    "statement_tx": ["结算单流水", "结算明细"],
    "order_tx": ["订单交易流水", "订单交易"],
    "payments": ["付款记录", "付款"],
    "withdrawals": ["提现流水", "提现"],
    "unsettled": ["未结算"],
}


def finance_label(kind: str) -> str:
    return FINANCE_API_LABELS.get(kind, kind)


def finance_import_root(import_dirs: dict[str, Path]) -> Path:
    for key in FINANCE_DIR_KEYS.values():
        if key in import_dirs:
            return import_dirs[key].parent
    return next(iter(import_dirs.values())).parent


def zhanfu_day_tag(start: str, api_end: str) -> str:
    """展示日 = api_end 前一天（与 店铺分析.py 一致）。"""
    end = api_end or start
    return (date.fromisoformat(end) - timedelta(days=1)).isoformat()


def analytics_export_filename(
    export_tag: str,
    kind: str,
    start: str,
    end: str,
    *,
    stems: dict[str, str] | None = None,
    zhanfu: bool = True,
) -> str:
    s = {**DEFAULT_ANALYTICS_STEMS, **(stems or {})}
    name = s.get(kind, kind)
    tag = export_tag or "shop"
    if zhanfu:
        start_inc = start
        end_inc = zhanfu_day_tag(start, end)
        return f"{tag}_{name}_{start_inc}_{end_inc}.xlsx"
    return f"{tag}_{name}_{start}_{end}.xlsx"


def analytics_export_filename_by_cache_stem(
    export_tag: str,
    cache_stem: str,
    start: str,
    end: str,
    *,
    stems: dict[str, str] | None = None,
    zhanfu: bool = True,
) -> str:
    kind = {
        "product_list": "product",
        "sku_list": "sku",
        "video_detail": "video",
        "shop_key_metrics": "shop",
    }.get(cache_stem, cache_stem)
    return analytics_export_filename(export_tag, kind, start, end, stems=stems, zhanfu=zhanfu)


def finance_export_filename(
    export_tag: str,
    kind: str,
    start: str,
    end: str,
    *,
    stems: dict[str, str] | None = None,
) -> str:
    """与订单/罗盘一致：TIKTOK4号店PH_获取对账单_2026-06-01_2026-06-02.xlsx"""
    s = {**DEFAULT_FINANCE_STEMS, **(stems or {})}
    name = s.get(kind, kind)
    tag = export_tag or "shop"
    return f"{tag}_{name}_{start}_{end}.xlsx"


def finance_export_filename_legacy(
    kind: str,
    start: str,
    end: str,
    *,
    stems: dict[str, str] | None = None,
) -> str:
    """旧版无店名（多店会互相覆盖，仅作兼容读取）。"""
    s = {**DEFAULT_FINANCE_STEMS, **(stems or {})}
    name = s.get(kind, kind)
    return f"{name}_{start}_{end}.xlsx"


def default_finance_import_dirs() -> dict[str, Path]:
    from common.paths import Z_API_INTERFACE, Z_JSON_CACHE

    return {
        "对账单目录": Z_API_INTERFACE / "获取对账单",
        "按对账单交易目录": Z_API_INTERFACE / "按对账单获取交易记录",
        "按订单交易目录": Z_API_INTERFACE / "按订单获取交易记录",
        "付款记录目录": Z_API_INTERFACE / "获取付款记录",
        "提现记录目录": Z_API_INTERFACE / "获取提现记录",
        "未结算交易目录": Z_API_INTERFACE / "获取未结算交易",
        "财务_JSON目录": Z_JSON_CACHE / "店铺财务",
    }


def load_finance_import_dirs() -> dict[str, Path]:
    """从 导入总配置.ini 读取 Z 盘目录，失败则用默认。"""
    try:
        from common.config_loader import load_config
        from common.paths import MASTER_CONFIG

        return load_config(MASTER_CONFIG)["finance"]["import_dirs"]
    except Exception:
        return default_finance_import_dirs()


def default_order_import_dirs() -> dict[str, Path]:
    from common.paths import Z_API_INTERFACE, Z_JSON_CACHE

    return {
        "订单目录": Z_API_INTERFACE / "订单数据表",
        "订单_JSON目录": Z_JSON_CACHE / "订单数据表",
    }


def load_order_import_dirs() -> dict[str, Path]:
    """从 导入总配置.ini 读取订单 Z 盘目录，失败则用默认。"""
    try:
        from common.config_loader import load_config
        from common.paths import MASTER_CONFIG

        return load_config(MASTER_CONFIG)["order"]["import_dirs"]
    except Exception:
        return default_order_import_dirs()


def order_excel_path(
    export_tag: str,
    start: str,
    end: str,
    import_dirs: dict[str, Path],
    *,
    order_stem: str = "订单数据表",
) -> Path:
    from common.file_importer import order_filename

    name = order_filename(export_tag, start, end, order_stem)
    return import_dirs["订单目录"] / name


def finance_excel_path(
    export_tag: str,
    kind: str,
    start: str,
    end: str,
    import_dirs: dict[str, Path],
    *,
    stems: dict[str, str] | None = None,
) -> Path:
    key = FINANCE_DIR_KEYS[kind]
    name = finance_export_filename(export_tag, kind, start, end, stems=stems)
    return import_dirs[key] / name


def excel_sheet_title(kind: str, *, finance: bool = False) -> str:
    titles = FINANCE_SHEET_TITLES if finance else ANALYTICS_SHEET_TITLES
    title = titles.get(kind, kind)
    return title[:31]


ADS_REPORT_SUFFIX: dict[str, str] = {
    "creative": "广告创意",
    "live": "直播广告",
    "cost": "总花费",
}


def cost_export_filename(advertiser_id: str, start: str, end: str, *, stamp: str | None = None) -> str:
    """站斧 Cost 表命名：Cost_{广告户ID}_{开始}_{结束}_{时间}.xlsx"""
    from datetime import datetime

    ts = stamp or datetime.now().strftime("%Y-%m-%d %H_%M_%S")
    adv = sanitize_filename_part(advertiser_id, max_len=32) or "adv"
    return f"Cost_{adv}_{start}_{end}_{ts}.xlsx"


def sanitize_filename_part(text: str, *, max_len: int = 48) -> str:
    """去掉 Windows 非法字符，供广告户名等拼进 Excel 文件名。"""
    s = (text or "").strip()
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    s = re.sub(r"\s+", " ", s)
    return s[:max_len].strip()


def ads_export_filename(
    shop_key: str,
    export_tag: str,
    region: str,
    advertiser_name: str,
    report_kind: str,
    start: str,
    end: str,
) -> str:
    """例：TKKJ1MY_TIKTOK跨境1号店MY_MY_广告创意_2026-06-21_2026-06-21.xlsx"""
    key = sanitize_filename_part((shop_key or "ads").lower(), max_len=24) or "ads"
    tag = sanitize_filename_part(export_tag or key, max_len=40) or key
    reg = sanitize_filename_part((region or "XX").upper(), max_len=4) or "XX"
    suffix = ADS_REPORT_SUFFIX.get(report_kind.strip().lower(), report_kind)
    adv = sanitize_filename_part(advertiser_name)
    if adv:
        return f"{key}_{tag}_{reg}_{adv}_{suffix}_{start}_{end}.xlsx"
    return f"{key}_{tag}_{reg}_{suffix}_{start}_{end}.xlsx"
