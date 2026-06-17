# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PLATFORMS_DIR = PROJECT_ROOT / "platforms"
TIKTOK_DIR = PLATFORMS_DIR / "tiktok"
SHOPEE_DIR = PLATFORMS_DIR / "shopee"
COMMON_DIR = PROJECT_ROOT / "common"

# TikTok 平台目录
TIKTOK_SHOP_DIR = TIKTOK_DIR / "shop"
TIKTOK_ANALYTICS_DIR = TIKTOK_DIR / "analytics"
TIKTOK_ORDERS_DIR = TIKTOK_DIR / "orders"
TIKTOK_FINANCE_DIR = TIKTOK_DIR / "finance"
TIKTOK_PRODUCTS_DIR = TIKTOK_DIR / "products"
TIKTOK_PROMOTIONS_DIR = TIKTOK_DIR / "promotions"
TIKTOK_CONTENT_DIR = TIKTOK_DIR / "content"
TIKTOK_TEST_ENV = TIKTOK_DIR / "test_env"

# 兼容旧变量名
ENV_ROOT = TIKTOK_DIR
TEST_ENV = TIKTOK_TEST_ENV
DEFAULT_SHOP_HUB = TIKTOK_SHOP_DIR
DEFAULT_ANALYTICS_SCRIPT = TIKTOK_ANALYTICS_DIR / "店铺分析.py"
DEFAULT_FINANCE_SCRIPT = TIKTOK_FINANCE_DIR / "流水分析.py"
DEFAULT_ORDER_SCRIPT = TIKTOK_ORDERS_DIR / "订单查询.py"
DEFAULT_PRODUCT_DIR = TIKTOK_PRODUCTS_DIR

# 顶层分类目录
CONFIG_DIR = PROJECT_ROOT / "config"
LAUNCH_DIR = PROJECT_ROOT / "launch"
TOOLS_DIR = PROJECT_ROOT / "tools"
BATCH_DIR = PROJECT_ROOT / "batch"

MASTER_CONFIG = CONFIG_DIR / "导入总配置.ini"
SHOP_CONFIG_INI = CONFIG_DIR / "店铺配置.ini"
RUN_SHOPS_INI = CONFIG_DIR / "运行店铺.ini"
SCHEDULE_INI = CONFIG_DIR / "定时任务.ini"
CONFIG_INDEX_INI = CONFIG_DIR / "配置文件索引.ini"

BATCH_ANALYTICS_DIR = BATCH_DIR / "analytics"
BATCH_FINANCE_DIR = BATCH_DIR / "finance"
BATCH_ORDERS_DIR = BATCH_DIR / "orders"
BATCH_ANALYTICS_SCRIPT = BATCH_ANALYTICS_DIR / "批量导入.py"
BATCH_FINANCE_SCRIPT = BATCH_FINANCE_DIR / "批量导入.py"
BATCH_ORDERS_SCRIPT = BATCH_ORDERS_DIR / "批量导入.py"
BATCH_FINANCE_CONFIG = BATCH_FINANCE_DIR / "导入配置.ini"
BATCH_ORDERS_CONFIG = BATCH_ORDERS_DIR / "导入配置.ini"

CHECK_ENV_SCRIPT = TOOLS_DIR / "check_env.py"
RUN_ALL_SCRIPT = TOOLS_DIR / "一键导入.py"
SHOW_SHOPS_SCRIPT = TOOLS_DIR / "查看店铺配置.py"

DEFAULT_Z_ROOT = Path(r"Z:\Tk每日数据")
Z_API_INTERFACE = DEFAULT_Z_ROOT / "店铺分析API接口"
Z_JSON_CACHE = Z_API_INTERFACE / "json缓存"

# 本地导出/下载目录（不进 git 仓库）
EXPORT_DATA_ROOT = Path(r"C:\Users\Administrator\Desktop\下载")
EXPORT_SHOP_DIR = EXPORT_DATA_ROOT / "店铺"
CURRENT_SHOP_FILE = EXPORT_SHOP_DIR / "CURRENT_SHOP.txt"
EXPORT_ORDERS_DIR = EXPORT_DATA_ROOT / "订单"
EXPORT_FINANCE_DIR = EXPORT_DATA_ROOT / "财务"
EXPORT_ANALYTICS_DIR = EXPORT_DATA_ROOT / "罗盘"
EXPORT_ADS_DIR = EXPORT_DATA_ROOT / "广告"
LEGACY_CURRENT_SHOP_FILE = TIKTOK_SHOP_DIR / "CURRENT_SHOP.txt"

DEFAULT_ANALYTICS_LOGS = EXPORT_ANALYTICS_DIR
DEFAULT_FINANCE_LOGS = EXPORT_FINANCE_DIR
DEFAULT_ORDER_LOGS = EXPORT_ORDERS_DIR


def ensure_export_dirs() -> Path:
    for d in (
        EXPORT_DATA_ROOT,
        EXPORT_SHOP_DIR,
        EXPORT_ORDERS_DIR,
        EXPORT_FINANCE_DIR,
        EXPORT_ANALYTICS_DIR,
        EXPORT_ADS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return EXPORT_DATA_ROOT


def migrate_current_shop_file() -> None:
    ensure_export_dirs()
    if CURRENT_SHOP_FILE.exists():
        return
    if LEGACY_CURRENT_SHOP_FILE.exists():
        key = LEGACY_CURRENT_SHOP_FILE.read_text(encoding="utf-8").strip()
        if key:
            CURRENT_SHOP_FILE.write_text(key + "\n", encoding="utf-8")


def resolve_current_shop_file() -> Path:
    migrate_current_shop_file()
    return CURRENT_SHOP_FILE


def export_shop_dir(module: str, shop_label: str) -> Path:
    """module: orders | finance | analytics"""
    mapping = {
        "orders": EXPORT_ORDERS_DIR,
        "finance": EXPORT_FINANCE_DIR,
        "analytics": EXPORT_ANALYTICS_DIR,
        "ads": EXPORT_ADS_DIR,
    }
    d = mapping[module] / shop_label
    d.mkdir(parents=True, exist_ok=True)
    return d


ALL_SHOP_KEYS = (
    "TKKJ1PH,TKKJ1TH,TKKJ1MY,TKKJ2PH,TKKJ2TH,TKKJ3PH,TKKJ3TH,TKKJ3MY,"
    "TKKJ4PH,TKKJ4TH,TKKJ5PH,TKKJ5TH,TKKJ6PH,TKKJ6TH,TKKJ6MY,"
    "TK1PH,TK2PH,TK3PH,TK4PH,TK5PH,TK6PH,TK7PH,TK8PH,TK1TH"
)
