# -*- coding: utf-8 -*-
"""读取 INI 配置（总配置 + 模块覆盖）。"""
from __future__ import annotations

import configparser
from datetime import date, datetime, timedelta
from pathlib import Path

from common.paths import (
    DEFAULT_ANALYTICS_LOGS,
    DEFAULT_ANALYTICS_SCRIPT,
    DEFAULT_FINANCE_LOGS,
    DEFAULT_FINANCE_SCRIPT,
    DEFAULT_ORDER_LOGS,
    DEFAULT_ORDER_SCRIPT,
    DEFAULT_SHOP_HUB,
    DEFAULT_Z_ROOT,
    MASTER_CONFIG,
    PROJECT_ROOT,
    RUN_SHOPS_INI,
    SCHEDULE_INI,
    SHOP_CONFIG_INI,
    Z_API_INTERFACE,
    Z_JSON_CACHE,
)
from common.timezone_util import today_in_tz


def _load_shop_registry() -> configparser.ConfigParser | None:
    if not SHOP_CONFIG_INI.exists():
        return None
    cp = _read_ini(SHOP_CONFIG_INI)
    return cp


def _parse_enabled_shops(raw: str) -> list[str] | str:
    val = raw.strip()
    if not val:
        return []
    upper = val.upper()
    if upper in ("ALL", "全部", "*"):
        return "all"
    if upper in ("AUTO", "RUNLIST", "LIST", "运行列表", "本次运行"):
        return "runlist"
    return [s.strip().upper() for s in val.replace("，", ",").split(",") if s.strip()]


def _yes(value: str, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "是", "on")


def _read_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    return cp


def _get(cp: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    if not cp.has_section(section):
        return default
    return cp.get(section, key, fallback=default).strip()


def _resolve_path(raw: str, base: Path) -> Path:
    p = Path(raw.strip())
    if not p.is_absolute():
        p = base / p
    return p


def _parse_days_back(raw: str, default: int = 2) -> int:
    s = str(raw or "").strip()
    if not s:
        return default
    if s.isdigit():
        return max(1, int(s))
    return default


def resolve_query_date(
    *,
    days_back: int = 2,
    tz_name: str = "Asia/Manila",
    fixed: str = "",
    explicit: str = "",
) -> str:
    """按「往前天数」算统计日：1=昨天，2=前天，3=大前天…"""
    if explicit:
        return date.fromisoformat(explicit).isoformat()
    if fixed:
        return date.fromisoformat(fixed).isoformat()
    today = today_in_tz(tz_name or "Asia/Manila").date()
    return (today - timedelta(days=days_back)).isoformat()


def load_schedule_days_back(default: int = 2) -> tuple[int, str]:
    """读 定时任务.ini → (往前天数, 时区)。"""
    if not SCHEDULE_INI.exists():
        return default, "Asia/Manila"
    cp = _read_ini(SCHEDULE_INI)
    days = _parse_days_back(_get(cp, "定时", "往前天数", str(default)), default)
    tz_name = _get(cp, "定时", "时区", "Asia/Manila") or "Asia/Manila"
    return days, tz_name


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or MASTER_CONFIG
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    cp = _read_ini(path)
    g = "全局"
    shop_cp = _load_shop_registry()

    hub_default = str(DEFAULT_SHOP_HUB)
    if shop_cp and shop_cp.has_section("目录"):
        hub_default = _get(shop_cp, "目录", "店铺配置目录", hub_default)
    shop_hub = _resolve_path(_get(cp, g, "店铺配置目录", hub_default), PROJECT_ROOT)
    z_root = _resolve_path(_get(cp, g, "导入根目录", str(DEFAULT_Z_ROOT)), PROJECT_ROOT)

    query_date = _get(cp, g, "查询日期")
    days_back_raw = _get(cp, g, "往前天数", "")
    tz_name = _get(cp, g, "统计时区", "") or load_schedule_days_back()[1]
    fixed_date = _get(cp, g, "固定日期", "")

    auto_date = query_date.lower() in ("auto", "自动", "relative", "相对", "定时")
    if auto_date or (not query_date and not _get(cp, g, "开始日期")):
        schedule_days, schedule_tz = load_schedule_days_back(2)
        days_back = _parse_days_back(days_back_raw, schedule_days) if days_back_raw else schedule_days
        tz_name = tz_name or schedule_tz
        start = resolve_query_date(days_back=days_back, tz_name=tz_name, fixed=fixed_date)
        end = start
    else:
        start = _get(cp, g, "开始日期") or query_date
        end = _get(cp, g, "结束日期") or query_date or start

        if not start:
            days_back, tz_name = load_schedule_days_back(2)
            if days_back_raw:
                days_back = _parse_days_back(days_back_raw, days_back)
            start = resolve_query_date(days_back=days_back, tz_name=tz_name, fixed=fixed_date)
            end = start
        if not end:
            end = start

    # API end_date_lt 不含结束日；查单日 5/30 → start=5/30, end=5/31
    api_end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()

    shops_raw = _get(cp, g, "启用店铺", "runlist")
    enabled_shops = _parse_enabled_shops(shops_raw)

    if enabled_shops == "runlist":
        if RUN_SHOPS_INI.exists():
            run_cp = _read_ini(RUN_SHOPS_INI)
            shops_raw = _get(run_cp, "本次运行", "店铺", "")
        else:
            shops_raw = ""
        enabled_shops = _parse_enabled_shops(shops_raw)
    elif enabled_shops == "all":
        pass
    elif shops_raw.upper() == "AUTO" and shop_cp and shop_cp.has_section("批量启用"):
        shops_raw = _get(shop_cp, "批量启用", "启用店铺", "")
        enabled_shops = _parse_enabled_shops(shops_raw)

    analytics_sec = "店铺罗盘API"
    finance_sec = "店铺流水"
    order_sec = "订单" if cp.has_section("订单") else "订单数据"

    def import_dirs(section: str, defaults: dict[str, str]) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for key, rel in defaults.items():
            raw = _get(cp, section, key, rel)
            if raw.startswith("根目录"):
                raw = raw.replace("根目录", str(z_root), 1)
            out[key] = _resolve_path(raw, PROJECT_ROOT)
        return out

    analytics_defaults = {
        "产品目录": str(z_root / "产品"),
        "SKU目录": str(z_root / "sku"),
        "视频目录": str(z_root / "视频自营"),
        "产品_API目录": str(Z_API_INTERFACE / "产品数据表"),
        "SKU_API目录": str(Z_API_INTERFACE / "商品sku信息"),
        "视频_API目录": str(Z_API_INTERFACE / "视频自营明细"),
        "产品_JSON目录": str(Z_JSON_CACHE / "产品"),
        "SKU_JSON目录": str(Z_JSON_CACHE / "商品sku信息"),
        "视频_JSON目录": str(Z_JSON_CACHE / "视频自营明细"),
        "店铺数据目录": str(z_root / "店铺数据"),
    }
    finance_defaults = {
        "结算单目录": str(Z_API_INTERFACE / "结算单"),
        "结算明细目录": str(Z_API_INTERFACE / "结算单流水"),
        "付款目录": str(Z_API_INTERFACE / "付款记录"),
        "提现目录": str(Z_API_INTERFACE / "提现流水"),
        "未结算目录": str(Z_API_INTERFACE / "未结算"),
        "流水_JSON目录": str(Z_JSON_CACHE / "店铺流水"),
    }
    order_defaults = {
        "订单目录": str(Z_API_INTERFACE / "订单数据表"),
        "订单_JSON目录": str(Z_JSON_CACHE / "订单数据表"),
    }

    data_types_raw = _get(cp, analytics_sec, "数据类型", "产品,SKU,视频")
    analytics_types = _parse_types(
        data_types_raw,
        {"产品": "product", "product": "product", "SKU": "sku", "sku": "sku", "视频": "video", "video": "video", "店铺": "shop", "shop": "shop"},
        default=("product", "sku", "video"),
    )

    finance_types_raw = _get(cp, finance_sec, "数据类型", "结算单,结算明细,付款,提现")
    finance_types = _parse_types(
        finance_types_raw,
        {
            "结算单": "statements",
            "statements": "statements",
            "结算明细": "statement_tx",
            "流水": "statement_tx",
            "transactions": "statement_tx",
            "付款": "payments",
            "payments": "payments",
            "提现": "withdrawals",
            "withdrawals": "withdrawals",
            "未结算": "unsettled",
            "unsettled": "unsettled",
        },
        default=("statements", "statement_tx", "payments", "withdrawals"),
    )

    return {
        "config_path": path,
        "shop_hub": shop_hub,
        "z_root": z_root,
        "query_date": query_date or start,
        "start": start,
        "end": end,
        "api_end": api_end,
        "enabled_shops": enabled_shops,
        "auto_import": _yes(_get(cp, g, "自动导入", "是"), True),
        "skip_existing": _yes(_get(cp, g, "跳过已存在", "否"), False),
        "import_db": _yes(_get(cp, g, "导入数据库", "否"), False),
        "export_excel": _yes(_get(cp, g, "导出Excel", "是"), True),
        "save_cache": _yes(_get(cp, g, "保存缓存", "是"), True),
        "local_logs": _resolve_path(_get(cp, g, "本地日志目录", "logs"), PROJECT_ROOT),
        "analytics": {
            "enabled": _yes(_get(cp, analytics_sec, "启用", "是"), True),
            "script": _resolve_path(_get(cp, analytics_sec, "脚本", str(DEFAULT_ANALYTICS_SCRIPT)), PROJECT_ROOT),
            "logs_dir": _resolve_path(_get(cp, analytics_sec, "日志目录", str(DEFAULT_ANALYTICS_LOGS)), PROJECT_ROOT),
            "data_types": analytics_types,
            "video_detail": _yes(_get(cp, analytics_sec, "拉视频详情", "是"), True),
            "import_dirs": import_dirs(analytics_sec, analytics_defaults),
            "copy_api_copy": _yes(_get(cp, analytics_sec, "复制到API接口目录", "是"), True),
        },
        "finance": {
            "enabled": _yes(_get(cp, finance_sec, "启用", "否"), False),
            "script": _resolve_path(_get(cp, finance_sec, "脚本", str(DEFAULT_FINANCE_SCRIPT)), PROJECT_ROOT),
            "logs_dir": _resolve_path(_get(cp, finance_sec, "日志目录", str(DEFAULT_FINANCE_LOGS)), PROJECT_ROOT),
            "data_types": finance_types,
            "import_dirs": import_dirs(finance_sec, finance_defaults),
        },
        "order": {
            "enabled": _yes(_get(cp, order_sec, "启用", "否"), False),
            "script": _resolve_path(_get(cp, order_sec, "脚本", str(DEFAULT_ORDER_SCRIPT)), PROJECT_ROOT),
            "logs_dir": _resolve_path(_get(cp, order_sec, "日志目录", str(DEFAULT_ORDER_LOGS)), PROJECT_ROOT),
            "import_dirs": import_dirs(order_sec, order_defaults),
            "order_status": _get(cp, order_sec, "订单状态"),
            "all_pages": _yes(_get(cp, order_sec, "全部翻页", "是"), True),
        },
    }


def _parse_types(raw: str, mapping: dict[str, str], default: tuple[str, ...]) -> set[str]:
    if not raw or raw.lower() in ("all", "全部", "*"):
        return set(default)
    out: set[str] = set()
    for part in raw.replace("，", ",").split(","):
        key = part.strip()
        if not key:
            continue
        val = mapping.get(key) or mapping.get(key.lower())
        if val:
            out.add(val)
    return out or set(default)


def analytics_run_type(types: set[str], video_detail: bool = True) -> tuple[str, bool]:
    """返回 (--type, no_video_detail)。

    注意: --type all 会拉店铺+视频+产品+SKU；多选子集时用逗号组合（如 product,sku），
    避免误跑视频列表/店铺数据。
    """
    all_types = {"shop", "product", "sku", "video"}
    if not types:
        return "shop", True
    if types == {"shop"}:
        return "shop", True
    if types == {"product"}:
        return "product", True
    if types == {"sku"}:
        return "sku", True
    if types == {"video"}:
        return "video", not video_detail
    if types >= all_types:
        return "all", not video_detail if "video" in types else True

    order = ("shop", "product", "sku", "video")
    type_str = ",".join(t for t in order if t in types)
    no_video_detail = "video" not in types or not video_detail
    return type_str or "shop", no_video_detail
