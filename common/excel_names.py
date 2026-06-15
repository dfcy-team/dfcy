# -*- coding: utf-8 -*-
"""Excel 导出中文文件名 / 工作表名（与 店铺配置.ini [导出文件名] 对齐）。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

DEFAULT_ANALYTICS_STEMS: dict[str, str] = {
    "product": "产品数据表",
    "sku": "商品sku信息",
    "video": "视频自营明细",
    "shop": "店铺数据",
}

DEFAULT_FINANCE_STEMS: dict[str, str] = {
    "statements": "结算单",
    "statement_tx": "结算单流水",
    "payments": "付款记录",
    "withdrawals": "提现流水",
    "unsettled": "未结算",
}

ANALYTICS_CACHE_STEM: dict[str, str] = {
    "product": "product_list",
    "sku": "sku_list",
    "video": "video_detail",
    "shop": "shop_key_metrics",
}

ANALYTICS_SHEET_TITLES: dict[str, str] = {
    "product": "产品数据表",
    "sku": "商品sku信息",
    "video": "视频自营明细",
    "shop": "店铺数据",
}

FINANCE_SHEET_TITLES: dict[str, str] = {
    "statements": "结算单",
    "statement_tx": "结算单流水",
    "payments": "付款记录",
    "withdrawals": "提现流水",
    "unsettled": "未结算",
}

# 与 导入总配置.ini [流水导入] 键名对应
FINANCE_DIR_KEYS: dict[str, str] = {
    "statements": "结算单目录",
    "statement_tx": "结算明细目录",
    "payments": "付款目录",
    "withdrawals": "提现目录",
    "unsettled": "未结算目录",
}


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
        day = zhanfu_day_tag(start, end)
        return f"{tag}_{name}_{day}_{day}.xlsx"
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
    """与订单/罗盘一致：TIKTOK4号店PH_结算单流水_2026-06-01_2026-06-02.xlsx"""
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
        "结算单目录": Z_API_INTERFACE / "结算单",
        "结算明细目录": Z_API_INTERFACE / "结算单流水",
        "付款目录": Z_API_INTERFACE / "付款记录",
        "提现目录": Z_API_INTERFACE / "提现流水",
        "未结算目录": Z_API_INTERFACE / "未结算",
        "流水_JSON目录": Z_JSON_CACHE / "店铺流水",
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
