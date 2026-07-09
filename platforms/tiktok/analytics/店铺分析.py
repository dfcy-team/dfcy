# -*- coding: utf-8 -*-
"""
TikTok Shop 店铺分析 — Shop Analytics API
权限: data.shop_analytics.public.read

【推荐】两套独立入口（不同应用 API）:
  python 店铺分析_鼎峰API.py      — 鼎峰 app 6k2of5545ns13
  python 店铺分析_跨境2API.py     — 跨境2 app 6k3vv9pooutd9

或 --shop TK2PH / 正式环境\\店铺配置\\CURRENT_SHOP.txt

日期在 .env 的 TTS_ANALYTICS_START/END（按店铺当地自然日，PH/TH/MY 自动识别）。

默认（--type all）会导出 4 类 Excel 到 logs/<店名>/（中文文件名）：
  <店名>_产品数据表_<日期>_<日期>.xlsx
  <店名>_商品sku信息_<日期>_<日期>.xlsx
  <店名>_视频总和明细_<日期>_<日期>.xlsx
  <店名>_店铺数据_<日期>_<日期>.xlsx
加 --no-excel 可关闭；加 --no-all 可只导当前页（不全量翻页）。
产品数据表主图 URL: --product-images（预览可加 --product-images-limit 20 --type product --no-video-detail）。
逐条拉取规则: 每条 API 内重试 2 次（共 3 次）；商品表失败 ID 再补拉最多 5 轮；仍失败则不导出（宁缺毋滥）。

入库（与 Excel 列完全一致，不要 xlsx）:
  python 店铺分析.py --no-excel --save-tables
  → logs/<店名>/product_list_*.json 等，含 headers + records 字段，可直接导入数据库。

原始 API 响应（结构不同于 Excel）: 加 --save
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

# ==================== 顶部配置（改这里即可）====================
# 店铺配置文件
USE_CONFIG = "config_本土1PH店.env"

# 是否导出 Excel（命令行 --no-excel 可临时关掉）
EXPORT_EXCEL = True

# 是否保存入库 JSON（列与 Excel 相同；命令行 --save-tables 可临时打开）
SAVE_TABLES_JSON = False

# 是否拉取「每一条」视频详情（False=只用视频列表，快很多，视频表无详情列）
FETCH_VIDEO_DETAIL = True

# 加速：并发线程数（视频 330 条建议 4~6；SSL 经常断就改 2；1=最慢最稳）
VIDEO_DETAIL_WORKERS = 5
_vw = os.environ.get("TTS_VIDEO_DETAIL_WORKERS", "").strip()
if _vw.isdigit() and int(_vw) > 0:
    VIDEO_DETAIL_WORKERS = int(_vw)
PRODUCT_DETAIL_WORKERS = 2
_pw = os.environ.get("TTS_PRODUCT_DETAIL_WORKERS", "").strip()
if _pw.isdigit() and int(_pw) > 0:
    PRODUCT_DETAIL_WORKERS = int(_pw)

# 每条请求间隔秒（有并发时一般设 0；仍断网可改 0.1）
VIDEO_DETAIL_SLEEP = 0
PRODUCT_DETAIL_SLEEP = 0

# 产品数据表加主图 URL 列（需额外调 Product 详情 API；默认关，加 --product-images 开启）
PRODUCT_IMAGE_URLS = False
# 主图 URL API 并发
PRODUCT_IMAGE_WORKERS = 8
# 0=全部拉 URL；>0 仅前 N 个商品（预览时可设 20）
PRODUCT_IMAGES_LIMIT = 0

# Excel 写入失败时重试次数（如缺 openpyxl 会先尝试自动安装）
EXCEL_EXPORT_RETRIES = 3

# 导出版式: "站斧" = 对齐 Z:\Tk每日数据 表头/文件名； "api" = 原脚本格式
EXPORT_FORMAT = "站斧"
# 站斧文件名里的店铺名（例: TIKTOK1号店PH、TIKTOK跨境1号店PH）
# 跨境店请在 config_跨境2店.env 里设 TTS_EXPORT_SHOP_TAG，或跑 店铺分析_跨境2.py
EXPORT_SHOP_TAG = "TIKTOK1号店PH"
# 店铺类型: local=本土店  cross_border=跨境店（商品目录会多调全球商品 API）
# 也可在 .env 写 TTS_SHOP_MODE=cross_border，或配置名含「跨境」时自动识别
# ================================================================

_SCRIPT = Path(__file__).resolve()
_TIKTOK = _SCRIPT.parents[1]
_PROJECT = _SCRIPT.parents[3]
_TEST_ENV = _TIKTOK / "test_env"
if not (_TEST_ENV / "shop_tz.py").exists():
    _LEGACY = Path(r"C:\Users\Administrator\Desktop\api测试\测试环境")
    if (_LEGACY / "shop_tz.py").exists():
        _TEST_ENV = _LEGACY
if str(_TEST_ENV) not in sys.path:
    sys.path.insert(0, str(_TEST_ENV))
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))
from shop_tz import (
    default_analytics_api_range,
    infer_shop_region_from_cfg,
    get_shop_tz,
    pick_config_before_init,
    today_local,
    tz_label,
)
from tts_client import TikTokShopClient, cfg, get_shop_token, init_shop_config, is_ok, strip_config_argv
from common.excel_names import analytics_export_filename_by_cache_stem, excel_sheet_title
from common.paths import ensure_export_dirs, export_shop_dir, EXPORT_ANALYTICS_DIR
from common.shop_registry import load_filename_stems

BASE = Path(__file__).parent
ENV_ROOT = BASE.parent

# 每条 API 请求内重试次数（首次 + 再试 2 次 = 共 3 次）
ITEM_ATTEMPTS = 3
# 首轮结束后，失败商品 ID 再整轮补拉（每轮每条仍 ITEM_ATTEMPTS 次；不含「商品不存在」类）
PRODUCT_FAILED_EXTRA_ROUNDS = 5
PRODUCT_FAILED_EXTRA_SLEEP = 3.0
# 详情 API 返回此类 code 表示商品已下架/不属于当前店，重试无意义，用列表+rich 拼行
PRODUCT_DETAIL_SKIP_CODES = frozenset({28001007, "28001007"})


pick_config_before_init(ENV_ROOT, USE_CONFIG)
CONFIG_FILE = init_shop_config(ENV_ROOT)
SHOP_REGION = infer_shop_region_from_cfg(CONFIG_FILE)
SHOP_TZ = get_shop_tz(SHOP_REGION)
ensure_export_dirs()
LOG_DIR = export_shop_dir("analytics", cfg("TTS_CONFIG_LABEL", CONFIG_FILE.stem))

_env_tag = cfg("TTS_EXPORT_SHOP_TAG", "").strip()
if _env_tag:
    EXPORT_SHOP_TAG = _env_tag

APP_KEY = cfg("TTS_APP_KEY", "6k3vv9pooutd9")
APP_SECRET = cfg("TTS_APP_SECRET")
TOKEN = cfg("TTS_ACCESS_TOKEN")
REFRESH = cfg("TTS_REFRESH_TOKEN")
CIPHER = cfg("TTS_SHOP_CIPHER")
REGION = SHOP_REGION

ENDPOINTS = {
    "shop": "/analytics/202509/shop/performance",
    "video_overview": "/analytics/202509/shop_videos/overview_performance",
    "video_list": "/analytics/202509/shop_videos/performance",
    "video_detail": "/analytics/202509/shop_videos/{video_id}/performance",
    # 202509 列表/详情为「视频归因 GMV」；202409 列表/详情 interval.gmv 为「视频 GMV」(W)，用于算间接 GMV
    "video_list_direct": "/analytics/202409/shop_videos/performance",
    "video_detail_direct": "/analytics/202409/shop_videos/{video_id}/performance",
    "product_list": "/analytics/202405/shop_products/performance",
    "product_list_rich": "/analytics/202605/shop_products/performance",
    "product_detail": "/analytics/202405/shop_products/{product_id}/performance",
    "sku_list": "/analytics/202406/shop_skus/performance",
}

LIST_KEYS = {
    "video_list": ("videos", "shop_videos"),
    "video_list_direct": ("videos", "shop_videos"),
    "product_list": ("products", "shop_products"),
    "product_list_rich": ("products",),
    "sku_list": ("skus", "shop_skus"),
}


def parse_args() -> dict:
    args = {
        "days": 7,
        "start": "",
        "end": "",
        "type": "all",
        "size": 100,
        "all_pages": False,
        "video_id": "",
        "detail": False,
        "detail_n": 0,
        "print_limit": 0,
        "save": False,
        "save_tables": False,
        "export_excel": EXPORT_EXCEL,
        "save_tables": SAVE_TABLES_JSON,
        "no_video_detail": not FETCH_VIDEO_DETAIL,
        "video_workers": VIDEO_DETAIL_WORKERS,
        "product_workers": PRODUCT_DETAIL_WORKERS,
        "embed_images": PRODUCT_IMAGE_URLS,
        "image_workers": PRODUCT_IMAGE_WORKERS,
        "embed_images_limit": PRODUCT_IMAGES_LIMIT,
        "only_export_excel": False,
    }
    argv = strip_config_argv(sys.argv[1:])
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--days" and i + 1 < len(argv):
            args["days"] = int(argv[i + 1])
            i += 2
        elif a == "--start" and i + 1 < len(argv):
            args["start"] = argv[i + 1]
            i += 2
        elif a == "--end" and i + 1 < len(argv):
            args["end"] = argv[i + 1]
            i += 2
        elif a == "--type" and i + 1 < len(argv):
            args["type"] = argv[i + 1].lower()
            i += 2
        elif a == "--size" and i + 1 < len(argv):
            args["size"] = int(argv[i + 1])
            i += 2
        elif a in ("--all", "--all-pages"):
            args["all_pages"] = True
            i += 1
        elif a in ("--video-id", "--id") and i + 1 < len(argv):
            args["video_id"] = argv[i + 1]
            i += 2
        elif a == "--detail":
            args["detail"] = True
            args["detail_n"] = 0
            i += 1
        elif a == "--detail-n" and i + 1 < len(argv):
            args["detail"] = True
            args["detail_n"] = int(argv[i + 1])
            i += 2
        elif a == "--print" and i + 1 < len(argv):
            args["print_limit"] = int(argv[i + 1])
            i += 2
        elif a == "--save":
            args["save"] = True
            i += 1
        elif a == "--save-tables":
            args["save_tables"] = True
            i += 1
        elif a == "--export-excel":
            args["export_excel"] = True
            i += 1
        elif a == "--no-excel":
            args["export_excel"] = False
            i += 1
        elif a == "--no-all":
            args["all_pages"] = False
            i += 1
        elif a == "--no-video-detail":
            args["no_video_detail"] = True
            args["detail"] = False
            i += 1
        elif a == "--video-workers" and i + 1 < len(argv):
            args["video_workers"] = max(1, min(16, int(argv[i + 1])))
            i += 2
        elif a == "--product-workers" and i + 1 < len(argv):
            args["product_workers"] = max(1, min(16, int(argv[i + 1])))
            i += 2
        elif a in ("--embed-images", "--product-images"):
            args["embed_images"] = True
            i += 1
        elif a in ("--embed-images-limit", "--product-images-limit") and i + 1 < len(argv):
            args["embed_images_limit"] = max(0, int(argv[i + 1]))
            i += 2
        elif a == "--image-workers" and i + 1 < len(argv):
            args["image_workers"] = max(1, min(16, int(argv[i + 1])))
            i += 2
        elif a == "--only-export-excel":
            args["only_export_excel"] = True
            i += 1
        else:
            i += 1
    return args


def apply_top_config(args: dict) -> None:
    """命令行未指定时，采用文件顶部 EXPORT_EXCEL / SAVE_TABLES_JSON 等开关。"""
    argv = strip_config_argv(sys.argv[1:])
    if "--no-excel" not in argv and "--export-excel" not in argv:
        args["export_excel"] = EXPORT_EXCEL
    if "--save-tables" not in argv:
        args["save_tables"] = SAVE_TABLES_JSON
    if "--no-video-detail" not in argv and "--detail" not in argv and "--detail-n" not in argv:
        args["no_video_detail"] = not FETCH_VIDEO_DETAIL
    if not any(a == "--video-workers" for a in argv):
        args["video_workers"] = VIDEO_DETAIL_WORKERS
    if not any(a == "--product-workers" for a in argv):
        args["product_workers"] = PRODUCT_DETAIL_WORKERS
    if not any(a in ("--embed-images", "--product-images") for a in argv):
        args["embed_images"] = PRODUCT_IMAGE_URLS
    if not any(a in ("--embed-images-limit", "--product-images-limit") for a in argv):
        args["embed_images_limit"] = PRODUCT_IMAGES_LIMIT
    if not any(a == "--image-workers" for a in argv):
        args["image_workers"] = PRODUCT_IMAGE_WORKERS


def apply_export_defaults(args: dict) -> None:
    """导出 Excel / 入库 JSON 时默认全量翻页 + 拉视频详情。"""
    if not args["export_excel"] and not args["save_tables"]:
        return
    argv = strip_config_argv(sys.argv[1:])
    if not any(a in ("--all", "--all-pages", "--no-all") for a in argv):
        args["all_pages"] = True
    if not args["no_video_detail"] and not any(a in ("--detail", "--detail-n") for a in argv):
        args["detail"] = True


def date_range(args: dict) -> tuple[str, str, str]:
    """返回 (start_date_ge, end_date_lt, source说明)。"""
    cli_start = args["start"]
    cli_end = args["end"]
    if cli_start and cli_end:
        return cli_start, cli_end, "命令行 --start/--end"

    if not cli_start and not cli_end:
        start, end = default_analytics_api_range(SHOP_TZ)
        return start, end, "默认前两天（与网页一致）"

    days = args["days"]
    cfg_days = cfg("TTS_ANALYTICS_DAYS")
    if cfg_days.isdigit():
        days = int(cfg_days)

    end_d = today_local(SHOP_TZ)
    if cli_end:
        end_d = date.fromisoformat(cli_end)
    start_d = end_d - timedelta(days=days)
    if cli_start:
        start_d = date.fromisoformat(cli_start)
    src = "config.env TTS_ANALYTICS_DAYS" if cfg("TTS_ANALYTICS_DAYS") and not cli_start else f"--days {days}"
    return str(start_d), str(end_d), src


def base_params(start: str, end: str, page_size: int | None = None) -> dict:
    p = {"shop_cipher": CIPHER, "start_date_ge": start, "end_date_lt": end}
    if page_size is not None:
        p["page_size"] = min(max(page_size, 1), 100)
    return p


def money(v: dict | None) -> str:
    if not v:
        return "-"
    return f"{v.get('amount', '?')} {v.get('currency', '')}".strip()


def safe_print(text: str) -> None:
    """Windows 控制台 GBK 时避免 emoji 等字符导致崩溃。"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        ))


def extract_list(data: dict | None, section_key: str) -> list[dict]:
    if not data:
        return []
    for k in LIST_KEYS.get(section_key, ()):
        if data.get(k):
            return list(data[k])
    return []


def fetch_get(
    client: TikTokShopClient,
    token: str,
    path: str,
    start: str,
    end: str,
    extra: dict | None = None,
    page_size: int | None = None,
) -> dict:
    params = base_params(start, end, page_size)
    if extra:
        params.update(extra)
    return client.get(path, token, params)


def _is_transient_api_error(resp: dict) -> bool:
    if is_rate_limit_error(resp):
        return True
    code = str(resp.get("code", ""))
    if code in ("36009007", "36009002", "20001"):
        return True
    msg = str(resp.get("message") or "").lower()
    return "timeout" in msg or "timed out" in msg or "request timeout" in msg


def fetch_all_list(
    client: TikTokShopClient,
    token: str,
    section_key: str,
    start: str,
    end: str,
    page_size: int = 100,
    max_pages: int = 200,
) -> tuple[list[dict], dict]:
    """用 page_token 翻页直到拿完；返回 (合并列表, 元信息)。"""
    path = ENDPOINTS[section_key]
    merged: list[dict] = []
    page_token: str | None = None
    total_count: int | None = None
    pages = 0

    for _ in range(max_pages):
        extra: dict = {}
        if page_token:
            extra["page_token"] = page_token
        r = fetch_get(client, token, path, start, end, extra=extra, page_size=page_size)
        for attempt in range(3):
            if is_ok(r) or not _is_transient_api_error(r):
                break
            wait = 3.0 * (2**attempt) + random.uniform(0, 1.5)
            print(
                f"\n[{section_key}] API code={r.get('code')}，"
                f"{wait:.1f}s 后重试本页 ({attempt + 1}/3)..."
            )
            time.sleep(wait)
            r = fetch_get(client, token, path, start, end, extra=extra, page_size=page_size)
        if not is_ok(r):
            return merged, {
                "error": r,
                "pages": pages,
                "total_count": total_count,
                "complete": False,
            }

        data = r.get("data") or {}
        batch = extract_list(data, section_key)
        merged.extend(batch)
        pages += 1
        if total_count is None and data.get("total_count") is not None:
            total_count = int(data["total_count"])
        page_token = data.get("next_page_token") or ""
        if not page_token:
            break
        time.sleep(0.35)

    meta = {
        "pages": pages,
        "fetched": len(merged),
        "total_count": total_count,
        "complete": total_count is None or len(merged) >= total_count,
    }
    return merged, meta


_LIST_RETRY_WAITS = (3.0, 10.0, 20.0, 30.0, 60.0)


def fetch_all_list_with_retry(
    client: TikTokShopClient,
    token: str,
    section_key: str,
    start: str,
    end: str,
    page_size: int = 100,
    *,
    label: str | None = None,
) -> tuple[list[dict], dict]:
    """整表翻页失败或未拉全时，退避后整表重拉。"""
    display = label or section_key
    last_items: list[dict] = []
    last_meta: dict = {}
    for attempt, wait in enumerate((0.0, *_LIST_RETRY_WAITS)):
        if wait > 0:
            print(
                f"\n[{display}] 分页未完整或 API 失败，"
                f"{wait:.0f}s 后整表重拉 ({attempt}/{len(_LIST_RETRY_WAITS)})..."
            )
            time.sleep(wait)
        last_items, last_meta = fetch_all_list(
            client, token, section_key, start, end, page_size=page_size
        )
        if not last_meta.get("error") and last_meta.get("complete", True):
            return last_items, last_meta
    return last_items, last_meta


_SKU_RETRY_WAITS = (10.0, 30.0, 60.0, 60.0, 90.0, 90.0)


def product_sales_from_snapshot(log_dir: Path, start: str, end: str) -> dict[str, float | int]:
    """从产品缓存汇总 GMV/订单/Active 数，供 SKU 空列表时区分限流 vs 真无数据。"""
    summary: dict[str, float | int] = {"gmv": 0.0, "orders": 0, "active_count": 0, "row_count": 0}
    for path in (
        log_dir / f"product_list_{start}_{end}.json",
        log_dir / f".cache_product_list_{start}_{end}.json",
    ):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        headers = data.get("headers") or []
        rows = data.get("rows") or []
        if not rows:
            continue
        id_idx = next((headers.index(k) for k in ("商品ID", "ID") if k in headers), None)
        gmv_idx = headers.index("GMV") if "GMV" in headers else None
        ord_idx = headers.index("订单数") if "订单数" in headers else None
        status_idx = headers.index("状态") if "状态" in headers else None
        if id_idx is None:
            continue
        gmv_sum = 0.0
        ord_sum = 0
        active = 0
        for row in rows:
            if len(row) <= id_idx:
                continue
            if gmv_idx is not None and len(row) > gmv_idx:
                try:
                    gmv_sum += float(row[gmv_idx] or 0)
                except (TypeError, ValueError):
                    pass
            if ord_idx is not None and len(row) > ord_idx:
                try:
                    ord_sum += int(float(str(row[ord_idx] or 0).replace(",", "")))
                except (TypeError, ValueError):
                    pass
            if status_idx is not None and len(row) > status_idx:
                if str(row[status_idx] or "").strip().lower() == "active":
                    active += 1
        summary = {
            "gmv": gmv_sum,
            "orders": ord_sum,
            "active_count": active,
            "row_count": len(rows),
        }
        break
    return summary


def classify_sku_empty(
    meta: dict | None,
    *,
    product_gmv: float = 0.0,
    product_orders: int = 0,
    has_product_snapshot: bool = True,
) -> str:
    """区分限流空返回 vs 真无数据。返回 rate_limit_suspect | likely_no_data。

    原则：有成交却拉不到 SKU → 限流/异常；零成交日 SKU 为空 → 真无数据（即使有产品在架）。
    """
    if not meta:
        return "likely_no_data" if has_product_snapshot else "rate_limit_suspect"
    err = meta.get("error")
    if err and isinstance(err, dict) and is_rate_limit_error(err):
        return "rate_limit_suspect"
    tc = meta.get("total_count")
    if tc is not None and int(tc) > 0:
        return "rate_limit_suspect"
    if not meta.get("complete", True):
        return "rate_limit_suspect"
    if not has_product_snapshot:
        return "rate_limit_suspect"
    if product_orders > 0 or product_gmv > 0:
        return "rate_limit_suspect"
    return "likely_no_data"


def fetch_sku_list_with_retry(
    client: TikTokShopClient,
    token: str,
    start: str,
    end: str,
    page_size: int,
    *,
    product_gmv: float = 0.0,
    product_orders: int = 0,
    has_product_snapshot: bool = True,
    retries: int = 5,
) -> tuple[list[dict], dict]:
    """SKU 表现 API 在批量任务中偶发空列表（code=0），空结果时加长退避重试。"""
    skus, meta = fetch_all_list(client, token, "sku_list", start, end, page_size=page_size)
    if meta.get("error") or skus:
        return skus, meta

    sales_ctx = {
        "product_gmv": product_gmv,
        "product_orders": product_orders,
        "has_product_snapshot": has_product_snapshot,
    }
    empty_kind = classify_sku_empty(meta, **sales_ctx)
    waits = _SKU_RETRY_WAITS[: max(1, retries)]
    if empty_kind == "likely_no_data":
        waits = waits[:1]
    for attempt, wait in enumerate(waits):
        if empty_kind == "rate_limit_suspect":
            hint = (
                "疑似限流/异常空返回（code=0 无 SKU，但当日有成交或分页未完成）"
                f" GMV={product_gmv:.2f} 订单={product_orders}"
            )
        else:
            hint = f"零成交日空列表（GMV={product_gmv:.2f} 订单={product_orders}），确认性重试"
        print(f"\n[SKU表现] {hint}，{wait:.0f}s 后重试 ({attempt + 1}/{len(waits)})...")
        time.sleep(wait)
        skus2, meta2 = fetch_all_list(client, token, "sku_list", start, end, page_size=page_size)
        if meta2.get("error"):
            return skus2, meta2
        if skus2:
            print(f"\n[SKU表现] 重试第 {attempt + 1} 次成功，共 {len(skus2)} 条")
            return skus2, meta2
        meta = meta2
        empty_kind = classify_sku_empty(meta, **sales_ctx)

    final_kind = classify_sku_empty(meta, **sales_ctx)
    if not skus:
        tc = meta.get("total_count")
        if final_kind == "rate_limit_suspect":
            print(
                f"\n[SKU表现] 警告: {len(waits)} 次重试后仍为空，判定为【限流/异常】"
                + (f"（total_count={tc}）" if tc is not None else "")
                + f"（GMV={product_gmv:.2f} 订单={product_orders}）"
                + "；请分阶段跑 SKU 或加大店间间隔"
            )
            meta = {**meta, "rate_limit_suspect": True}
        else:
            print(
                f"\n[SKU表现] 判定为【真无数据】（零成交日，GMV={product_gmv:.2f} 订单={product_orders}）"
                + "，将写零数据标记"
            )
    if not list_fetch_complete(meta) and not skus:
        tc = meta.get("total_count")
        if final_kind == "rate_limit_suspect":
            meta = {**meta, "rate_limit_suspect": True}
        else:
            print(
                f"\n[SKU表现] 警告: API 返回空列表且分页未完成"
                + (f"（total_count={tc}）" if tc is not None else "")
                + "，按 0 条处理"
            )
            meta = {**meta, "complete": True}
    return skus, meta


def fetch_video_detail(
    client: TikTokShopClient,
    token: str,
    video_id: str,
    start: str,
    end: str,
    *,
    endpoint_key: str = "video_detail",
) -> dict:
    path = ENDPOINTS[endpoint_key].format(video_id=video_id)
    return fetch_get(client, token, path, start, end)


def fetch_video_detail_safe(
    client: TikTokShopClient,
    token: str,
    video_id: str,
    start: str,
    end: str,
    *,
    endpoint_key: str = "video_detail",
) -> tuple[dict, bool]:
    """单条视频详情：最多 ITEM_ATTEMPTS 次；成功=API code 0。"""
    from requests.exceptions import ChunkedEncodingError, ConnectionError, SSLError, Timeout

    last_err: Exception | None = None
    for attempt in range(ITEM_ATTEMPTS):
        try:
            r = fetch_video_detail(
                client, token, video_id, start, end, endpoint_key=endpoint_key
            )
            if is_ok(r):
                return r, True
            last_err = RuntimeError(r.get("message") or f"code={r.get('code')}")
        except (SSLError, ConnectionError, Timeout, ChunkedEncodingError) as e:
            last_err = e
        if attempt < ITEM_ATTEMPTS - 1:
            time.sleep(2.0 * (attempt + 1))
    return {"code": -1, "message": f"failed_after_{ITEM_ATTEMPTS}_tries: {last_err}"}, False


def video_direct_gmv_from_detail(data: dict) -> float:
    """202409 详情 intervals[].gmv = 平台「视频 GMV」(W)。"""
    perf = (data or {}).get("performance") or {}
    for iv in perf.get("intervals") or []:
        gmv = iv.get("gmv")
        if isinstance(gmv, dict) and str(gmv.get("amount", "")).strip() not in ("", "0", "0.00"):
            try:
                return float(gmv_amount(gmv) or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def video_direct_gmv_from_list_item(v: dict) -> float:
    try:
        return float(gmv_amount(v.get("gmv")) or 0)
    except (TypeError, ValueError):
        return 0.0


def video_attributed_gmv_from_list_item(v: dict) -> float:
    sales = v.get("sales") or {}
    overall = sales.get("overall") or {}
    overall_gmv = overall.get("gmv")
    if overall_gmv:
        try:
            return float(gmv_amount(overall_gmv) or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(gmv_amount(v.get("gmv")) or 0)
    except (TypeError, ValueError):
        return 0.0


def video_attributed_gmv_from_interval(iv: dict, list_item: dict | None = None) -> float:
    sales = iv.get("sales") or {}
    overall = sales.get("overall") or {}
    overall_gmv = overall.get("gmv")
    if overall_gmv:
        try:
            return float(gmv_amount(overall_gmv) or 0)
        except (TypeError, ValueError):
            return 0.0
    nested = (sales.get("gmv") or {}).get("overall")
    if nested:
        try:
            return float(gmv_amount(nested) or 0)
        except (TypeError, ValueError):
            return 0.0
    if list_item:
        return video_attributed_gmv_from_list_item(list_item)
    gmv = iv.get("gmv")
    if gmv:
        try:
            return float(gmv_amount(gmv if isinstance(gmv, dict) else None) or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def video_gmv_vwx(attributed: float, direct: float) -> tuple[float, float, float]:
    att = float(attributed or 0)
    dir_ = float(direct or 0)
    if att <= 0:
        return 0.0, 0.0, 0.0
    if dir_ <= 0:
        return att, 0.0, att
    if dir_ >= att - 0.01:
        return att, att, 0.0
    return att, dir_, round(max(att - dir_, 0), 2)


def merge_video_lists(primary: list[dict], secondary: list[dict] | None = None) -> list[dict]:
    """合并视频列表（以 primary 顺序为准，补上 secondary 独有 ID）。"""
    seen: set[str] = set()
    merged: list[dict] = []
    for v in primary:
        vid = str(v.get("id") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        merged.append(v)
    for v in secondary or []:
        vid = str(v.get("id") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        merged.append(v)
    return merged


def fetch_video_list_items(
    client: TikTokShopClient,
    token: str,
    start: str,
    end: str,
    *,
    endpoint_key: str = "video_list",
    page_size: int,
    all_pages: bool,
) -> tuple[list[dict], dict]:
    if all_pages:
        return fetch_all_list(client, token, endpoint_key, start, end, page_size=page_size)
    r = fetch_get(client, token, ENDPOINTS[endpoint_key], start, end, page_size=page_size)
    if not is_ok(r):
        return [], {"error": r, "complete": False}
    items = extract_list(r.get("data") or {}, endpoint_key)
    data = r.get("data") or {}
    return items, {
        "complete": not bool(data.get("next_page_token")),
        "fetched": len(items),
        "total_count": data.get("total_count"),
    }


def load_video_direct_gmv_map(
    client: TikTokShopClient,
    token: str,
    start: str,
    end: str,
    *,
    page_size: int,
    all_pages: bool,
) -> tuple[dict[str, float], list[dict], dict]:
    """拉 202409 视频列表：video_id -> 视频GMV(W)，并返回原始列表供合并。"""
    items, meta = fetch_video_list_items(
        client,
        token,
        start,
        end,
        endpoint_key="video_list_direct",
        page_size=page_size,
        all_pages=all_pages,
    )
    if meta.get("error"):
        print(f"  [视频GMV对照 202409] 翻页失败: {(meta['error'] or {}).get('message', '')[:80]}")
        return {}, items, meta
    if not all_pages and not meta.get("complete", True):
        print("  [视频GMV对照 202409] 仍有下一页，请加 --all")
    out: dict[str, float] = {}
    for v in items:
        vid = str(v.get("id") or "")
        if vid:
            out[vid] = video_direct_gmv_from_list_item(v)
    return out, items, meta


def print_shop(data: dict) -> None:
    perf = (data or {}).get("performance") or {}
    intervals = perf.get("intervals") or []
    latest = (data or {}).get("latest_available_date", "-")
    print(f"\n[店铺整体] 数据截至 {latest}  区间数={len(intervals)}")
    for iv in intervals:
        sales = iv.get("sales") or {}
        traffic = iv.get("traffic") or {}
        gmv = (sales.get("gmv") or {}).get("overall") or {}
        print(f"  {iv.get('start_date')} ~ {iv.get('end_date')}")
        print(f"    GMV={money(gmv)}  订单={sales.get('orders_count')}  件数={sales.get('items_sold')}")
        print(
            f"    访客≈{traffic.get('avg_visitors')}  浏览≈{traffic.get('avg_page_views')}  "
            f"转化率={traffic.get('avg_conversation_rate')}"
        )
        for b in (sales.get("gmv") or {}).get("breakdowns") or []:
            print(f"    GMV·{b.get('type')}: {money(b.get('gmv'))}")


SHOP_DATA_HEADERS = [
    "总GMV",
    "订单数",
    "客户数",
    "商品成交件数",
    "退款金额",
    "SKU订单数",
    "总成交额",
    "页面浏览次数",
    "商品访客数",
    "转化率",
    "直播GMV",
    "视频GMV",
    "商品卡GMV",
]


def gmv_breakdown_map(sales: dict) -> dict[str, float]:
    out = {"LIVE": 0.0, "VIDEO": 0.0, "PRODUCT_CARD": 0.0}
    gmv = (sales or {}).get("gmv") or {}
    for b in gmv.get("breakdowns") or []:
        key = str(b.get("type", "")).upper()
        if key in out:
            out[key] = float(gmv_amount(b.get("gmv")))
    return out


def build_shop_data_row(interval: dict) -> list:
    sales = interval.get("sales") or {}
    traffic = interval.get("traffic") or {}
    bd = gmv_breakdown_map(sales)
    overall = (sales.get("gmv") or {}).get("overall")
    gross = (sales.get("gross_revenue") or {}).get("overall")
    refunds = sales.get("refunds") or {}
    cvr = traffic.get("avg_conversation_rate")
    try:
        cvr_val = float(cvr) if cvr not in (None, "") else 0.0
    except (TypeError, ValueError):
        cvr_val = 0.0
    return [
        gmv_amount(overall),
        sales.get("orders_count", 0),
        sales.get("avg_customers_count", 0),
        sales.get("items_sold", 0),
        gmv_amount(refunds if isinstance(refunds, dict) else None),
        sales.get("sku_orders_count", 0),
        gmv_amount(gross if isinstance(gross, dict) else None),
        traffic.get("avg_page_views", 0),
        traffic.get("avg_visitors", 0),
        cvr_val,
        bd["LIVE"],
        bd["VIDEO"],
        bd["PRODUCT_CARD"],
    ]


def export_shop_data_excel(day: str, headers: list[str], row: list, path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = excel_sheet_title("shop")
    d = date.fromisoformat(day)
    ws.append([f"分析日期：{d.strftime('%d/%m/%Y')}"])
    ws.append(["数据概览"])
    ws.append([""] + headers)
    ws.append(["总计值", *row])
    wb.save(path)


def print_video_overview(data: dict) -> None:
    print("\n[视频概览]")
    if not data:
        print("  (无数据)")
        return
    for k, v in data.items():
        if k == "latest_available_date":
            print(f"  {k}={v}")
        elif isinstance(v, dict):
            print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:240]}")
        elif not isinstance(v, list):
            print(f"  {k}={v}")


def print_video_row(i: int, v: dict) -> None:
    safe_print(
        f"  {i:3}. id={v.get('id')}  views={v.get('views')}  gmv={money(v.get('gmv'))}  "
        f"orders={v.get('sku_orders')}  ctr={v.get('click_through_rate')}"
    )
    safe_print(f"       @{v.get('username')}  {str(v.get('title') or '')[:70]}")


def print_video_detail(video_id: str, data: dict) -> None:
    perf = (data or {}).get("performance") or {}
    eng = (data or {}).get("engagement_data") or {}
    print(f"\n[视频详情] id={video_id}  数据截至 {data.get('latest_available_date', '-')}")
    if eng:
        print(
            f"  播放(累计)={eng.get('total_views')}  赞={eng.get('total_likes')}  "
            f"评={eng.get('total_comments')}  分享={eng.get('total_shares')}"
        )
    print(f"  发布时间={perf.get('video_post_time')}")
    for iv in perf.get("intervals") or []:
        sales = iv.get("sales") or {}
        traffic = iv.get("traffic") or {}
        overall = sales.get("overall") or {}
        gmv_att = overall.get("gmv") or (sales.get("gmv") or {}).get("overall") or iv.get("gmv")
        extra = ""
        if gmv_att:
            items_sold = overall.get("items_sold", sales.get("items_sold", ""))
            extra = f"  归因GMV={money(gmv_att)}  件数={items_sold}"
        if traffic:
            extra += f"  播放={traffic.get('views')}"
        print(f"  区间 {iv.get('start_date')} ~ {iv.get('end_date')}{extra}")
        if not sales and not traffic and iv.keys() - {"start_date", "end_date"}:
            print(f"       {json.dumps(iv, ensure_ascii=False)[:200]}")


def print_product_list(rows: list[dict], limit: int) -> None:
    print(f"\n[商品表现] 共 {len(rows)} 条（= 店铺在售/历史商品总数，不是只有成交的）")
    print("  控制台仅摘要；商城/直播/视频等 38 列请看导出的 Excel")
    show = rows if limit <= 0 else rows[:limit]
    for i, p in enumerate(show, 1):
        imp = p.get("impressions", 0)
        imp_s = f"  曝光={imp}" if imp else ""
        safe_print(
            f"  {i:3}. id={p.get('id')}  gmv={p.get('gmv_fmt', money(p.get('gmv')))}  "
            f"units={p.get('units_sold', 0)}  orders={p.get('orders', 0)}{imp_s}  "
            f"status={p.get('status_label', '')}  "
            f"name={str(p.get('title') or '')[:45]}"
        )
    if limit > 0 and len(rows) > limit:
        print(f"  ... 还有 {len(rows) - limit} 条，加 --print 0 显示全部")


PRODUCT_EXCEL_HEADERS = [
    "商品ID", "商品", "状态", "GMV", "成交件数", "订单数",
    "商城页 GMV", "商城商品成交件数", "商城页发品曝光次数", "商城页面浏览次数",
    "商城页去重页面浏览次数", "商城页去重商品客户数", "商城点击率", "商城转化率",
    "直播归因 GMV", "直播归因成交件数", "直播曝光次数", "直播的页面浏览次数",
    "直播的去重页面浏览次数", "直播去重商品客户数", "直播点击率", "直播转化率",
    "视频归因 GMV", "视频归因成交件数", "视频曝光次数", "来自视频的页面浏览次数",
    "来自视频的去重页面浏览次数", "视频去重商品客户数", "视频点击率", "视频转化率",
    "商品卡归因 GMV", "商品卡归因成交件数", "商品卡曝光次数", "商品卡的页面浏览次数",
    "商品卡的去重页面浏览次数", "商品卡去重客户数", "商品卡点击率", "商品卡转化率",
]

STATUS_LABELS = {
    "ACTIVATE": "Active",
    "SELLER_DEACTIVATED": "Inactive",
    "PLATFORM_DEACTIVATED": "Inactive",
    "DELETED": "Deleted",
}

ZHANFU_SKU_HEADERS = [
    "SKU编号", "商品ID", "商品", "状态", "GMV", "SKU订单数", "成交件数",
]

ZHANFU_VIDEO_HEADERS = [
    "达人昵称", "达人ID", "视频信息", "视频ID", "发布时间", "商品",
    "播放量", "点赞数", "评论数", "分享数", "新增粉丝数", "引流次数",
    "商品曝光次数", "商品点击次数", "去重客户数",
    "归因SKU订单数", "视频SKU订单数", "视频间接SKU订单数",
    "视频归因成交件数", "视频商品成交件数", "视频间接成交件数",
    "视频归因GMV", "视频GMV", "视频间接GMV",
    "千次播放GMV", "视频点击率", "引流率", "视频完播率", "SKU订单转化率", "诊断",
]


def is_zhanfu_export() -> bool:
    return EXPORT_FORMAT.strip().lower() in ("站斧", "zhanfu", "daily", "tk")


def zhanfu_date_label(start: str, end: str) -> str:
    """API end 不含当天；站斧展示为 inclusive 单日或区间。"""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) - timedelta(days=1)
    return f"{s} ~ {e}"


def zhanfu_day_tag(start: str, end: str) -> str:
    e = date.fromisoformat(end) - timedelta(days=1)
    return e.isoformat()


def gmv_amount(gmv_obj: dict | str | int | float | None) -> str | float:
    if gmv_obj is None or gmv_obj == "":
        return 0
    if isinstance(gmv_obj, dict):
        v = gmv_obj.get("amount", 0)
    else:
        v = str(gmv_obj).replace("₱", "").replace("PHP", "").strip()
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def money_cell(gmv_obj: dict | None) -> str:
    if is_zhanfu_export():
        return gmv_amount(gmv_obj if isinstance(gmv_obj, dict) else None)
    return fmt_php(gmv_obj)


def export_filename(stem: str, start: str, end: str) -> str:
    tag = EXPORT_SHOP_TAG or cfg("TTS_CONFIG_LABEL", "shop")
    stems = load_filename_stems()
    return analytics_export_filename_by_cache_stem(
        tag,
        stem,
        start,
        end,
        stems=stems,
        zhanfu=is_zhanfu_export(),
    )


def active_headers(kind: str, with_image_url: bool = False) -> list[str]:
    if kind == "product" and with_image_url:
        return ["主图URL", *PRODUCT_EXCEL_HEADERS]
    if not is_zhanfu_export():
        return {
            "product": PRODUCT_EXCEL_HEADERS,
            "sku": SKU_EXCEL_HEADERS,
            "video": VIDEO_EXCEL_HEADERS,
        }[kind]
    if kind == "product":
        return PRODUCT_EXCEL_HEADERS
    if kind == "sku":
        return ZHANFU_SKU_HEADERS
    return ZHANFU_VIDEO_HEADERS


def build_sku_meta_map(catalog: dict[str, dict]) -> dict[str, dict]:
    """从商品目录拼 SKU -> 商品名/状态（站斧 SKU 表）。"""
    out: dict[str, dict] = {}
    for pid, prod in catalog.items():
        status = STATUS_LABELS.get(prod.get("status", ""), prod.get("status", ""))
        base = prod.get("title", "") or ""
        for sk in prod.get("skus") or []:
            sid = str(sk.get("id", ""))
            if not sid:
                continue
            variant = sk.get("seller_sku") or sk.get("name") or ""
            title = f"{base}: {variant}" if variant and base else (variant or base)
            out[sid] = {"product_id": pid, "title": title, "status": status}
    return out


def build_sku_excel_rows(
    skus: list[dict],
    sku_meta: dict[str, dict] | None = None,
    *,
    product_by_id: dict[str, dict] | None = None,
) -> list[list]:
    rows: list[list] = []
    for s in skus:
        gmv = s.get("gmv")
        if isinstance(gmv, dict) and "overall" in gmv:
            gmv = gmv.get("overall")
        sid = str(s.get("id", ""))
        pid = str(s.get("product_id", ""))
        meta = (sku_meta or {}).get(sid, {})
        if not meta.get("title") and product_by_id:
            pm = product_by_id.get(pid, {})
            meta = {
                **meta,
                "product_id": pid,
                "title": pm.get("title", ""),
                "status": pm.get("status", ""),
            }
        if is_zhanfu_export():
            rows.append(
                [
                    sid,
                    meta.get("product_id", pid),
                    meta.get("title", ""),
                    meta.get("status", ""),
                    gmv_amount(gmv if isinstance(gmv, dict) else None),
                    s.get("orders", ""),
                    s.get("units_sold", s.get("items_sold", "")),
                ]
            )
        else:
            rows.append(
                [
                    sid,
                    pid,
                    fmt_php(gmv if isinstance(gmv, dict) else None),
                    s.get("units_sold", s.get("items_sold", "")),
                    s.get("orders", ""),
                    s.get("impressions", ""),
                    s.get("clicks", s.get("product_clicks", "")),
                    fmt_rate(s.get("click_through_rate") or s.get("conversion_rate")),
                ]
            )
    return rows


def _parse_money_str(s: str) -> float:
    if not s:
        return 0.0
    try:
        return float(str(s).replace("₱", "").replace(",", "").strip())
    except ValueError:
        return 0.0


def format_video_products(v: dict) -> str:
    products = v.get("products") or []
    if isinstance(products, list) and products:
        names = []
        for p in products:
            if isinstance(p, dict):
                n = p.get("name") or p.get("title") or ""
                pid = p.get("id") or ""
                if n and pid:
                    names.append(f"{n}({pid})")
                elif n:
                    names.append(str(n))
        if names:
            return "; ".join(names)
    return str(v.get("product_name") or v.get("linked_product") or "")


def legacy_video_row_to_zhanfu(
    row: list,
    *,
    product: str = "",
    attributed_gmv: float | None = None,
    direct_gmv: float | None = None,
) -> list:
    """把旧版 17 列缓存行转成站斧 30 列（用于预览/重导）。"""
    if len(row) < 12:
        return [""] * len(ZHANFU_VIDEO_HEADERS)
    vid, title, user = row[0], row[1], row[2]
    vv = row[3]
    gmv_s = row[14] if len(row) > 14 and row[14] not in ("", None) else row[4]
    orders = row[5] if row[5] not in ("", None) else (row[15] if len(row) > 15 else "")
    ctr = row[6]
    likes, comments, shares = row[8], row[9], row[10]
    post_time = row[11]
    units = row[16] if len(row) > 16 else ""
    att = float(attributed_gmv) if attributed_gmv is not None else _parse_money_str(str(gmv_s))
    direct = float(direct_gmv) if direct_gmv is not None else att
    gmv_v, gmv_w, gmv_x = video_gmv_vwx(att, direct)
    try:
        vv_n = float(vv) if vv not in ("", None) else 0
    except (TypeError, ValueError):
        vv_n = 0
    gpm = round(gmv_w / vv_n * 1000, 2) if vv_n and gmv_w else ""
    ctor = ""
    if orders and vv_n:
        try:
            ctor = f"{float(orders) / float(vv) * 100:.2f}%"
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return [
        user, "", title, vid, post_time, product or "",
        vv, likes, comments, shares, "", "",
        "", "", "",
        orders, orders, 0,
        units, units, 0,
        gmv_v, gmv_w, gmv_x,
        gpm, ctr, "", "", ctor, "No issues",
    ]


def _video_zhanfu_row_from_parts(
    *,
    user: str,
    creator_id: str,
    title: str,
    vid: str,
    post_time: str,
    product: str,
    views,
    likes,
    comments,
    shares,
    new_followers,
    product_clicks,
    product_impressions,
    customers,
    orders,
    units,
    attributed_gmv: float,
    direct_gmv: float,
    ctr,
    gpm_val="",
) -> list:
    gmv_v, gmv_w, gmv_x = video_gmv_vwx(attributed_gmv, direct_gmv)
    try:
        vv_n = float(views or 0)
    except (TypeError, ValueError):
        vv_n = 0
    gpm = gpm_val
    if gpm in ("", None) and vv_n and gmv_w:
        gpm = round(float(gmv_w) / vv_n * 1000, 2)
    ctor = ""
    if orders and vv_n:
        try:
            ctor = f"{float(orders) / float(views) * 100:.2f}%"
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return [
        user, creator_id, title, vid, post_time, product,
        views, likes, comments, shares, new_followers,
        "", product_impressions, product_clicks, customers,
        orders, orders, 0,
        units, units, 0,
        gmv_v, gmv_w, gmv_x,
        gpm, ctr, "", "", ctor,
        "No issues",
    ]


def build_video_zhanfu_rows(
    details: list[dict],
    videos: list[dict] | None = None,
    *,
    video_direct_gmv: dict[str, float] | None = None,
) -> list[list]:
    rows: list[list] = []
    direct_map = video_direct_gmv or {}
    if details:
        for item in details:
            v = item.get("list") or {}
            api = item.get("api") or {}
            data = (api.get("data") or {}) if is_ok(api) else {}
            eng = data.get("engagement_data") or {}
            perf = data.get("performance") or {}
            iv = {}
            for it in perf.get("intervals") or []:
                if it.get("start_date"):
                    iv = it
                    break
            sales = iv.get("sales") or {}
            overall = sales.get("overall") or {}
            traffic = iv.get("traffic") or {}
            vid_key = str(item.get("video_id") or v.get("id") or "")
            attributed = video_attributed_gmv_from_interval(iv, v)
            direct = item.get("direct_gmv")
            if direct is None:
                api_d = item.get("api_direct") or {}
                if is_ok(api_d):
                    direct = video_direct_gmv_from_detail(api_d.get("data") or {})
                else:
                    direct = direct_map.get(vid_key, 0.0)
            else:
                direct = float(direct)
            orders = v.get("sku_orders", "")
            units = overall.get("items_sold", v.get("items_sold", ""))
            ctr = fmt_rate(overall.get("ctr") or iv.get("click_through_rate") or v.get("click_through_rate"))
            gpm_obj = overall.get("gpm") or v.get("gpm")
            gpm = gmv_amount(gpm_obj if isinstance(gpm_obj, dict) else None)
            if gpm == "" and isinstance(gpm_obj, dict):
                gpm = ""
            rows.append(
                _video_zhanfu_row_from_parts(
                    user=v.get("username", ""),
                    creator_id=str(v.get("creator_id") or v.get("author_id") or ""),
                    title=str(v.get("title") or ""),
                    vid=str(item.get("video_id") or v.get("id") or ""),
                    post_time=perf.get("video_post_time") or v.get("video_post_time", ""),
                    product=str(v.get("product_name") or v.get("linked_product") or format_video_products(v)),
                    views=traffic.get("views", v.get("views", 0)),
                    likes=traffic.get("likes", eng.get("total_likes", "")),
                    comments=traffic.get("comments", eng.get("total_comments", "")),
                    shares=traffic.get("shares", eng.get("total_shares", "")),
                    new_followers=traffic.get("new_followers", ""),
                    product_clicks=overall.get("product_clicks", ""),
                    product_impressions=overall.get("product_impressions", ""),
                    customers=overall.get("customers", v.get("avg_customers", "")),
                    orders=orders,
                    units=units,
                    attributed_gmv=attributed,
                    direct_gmv=direct,
                    ctr=ctr,
                    gpm_val=gpm,
                )
            )
        return rows
    for v in videos or []:
        vid = str(v.get("id") or "")
        attributed = video_attributed_gmv_from_list_item(v)
        direct = direct_map.get(vid, 0.0)
        user = str(v.get("username") or "").lstrip("@")
        rows.append(
            _video_zhanfu_row_from_parts(
                user=user,
                creator_id=str(v.get("creator_id") or v.get("author_id") or ""),
                title=str(v.get("title") or ""),
                vid=vid,
                post_time=v.get("video_post_time", ""),
                product=format_video_products(v),
                views=v.get("views", ""),
                likes="",
                comments="",
                shares="",
                new_followers="",
                product_clicks="",
                product_impressions="",
                customers=v.get("avg_customers", ""),
                orders=v.get("sku_orders", ""),
                units=v.get("items_sold", ""),
                attributed_gmv=attributed,
                direct_gmv=direct,
                ctr=fmt_rate(v.get("click_through_rate")),
                gpm_val=gmv_amount(v.get("gpm") if isinstance(v.get("gpm"), dict) else None),
            )
        )
    return rows


def build_video_excel_rows(
    details: list[dict],
    videos: list[dict] | None = None,
    *,
    video_direct_gmv: dict[str, float] | None = None,
) -> list[list]:
    if is_zhanfu_export():
        return build_video_zhanfu_rows(details, videos, video_direct_gmv=video_direct_gmv)
    return _build_video_excel_rows_api(details, videos, video_direct_gmv=video_direct_gmv)


def _build_video_excel_rows_api(
    details: list[dict],
    videos: list[dict] | None = None,
    *,
    video_direct_gmv: dict[str, float] | None = None,
) -> list[list]:
    """原 API 17 列视频表。"""
    if details:
        rows: list[list] = []
        for item in details:
            vid = item["video_id"]
            v = item.get("list") or {}
            api = item.get("api") or {}
            base = [
                vid,
                str(v.get("title") or ""),
                str(v.get("username") or ""),
                v.get("views", ""),
                fmt_php(v.get("gmv") if isinstance(v.get("gmv"), dict) else None),
                v.get("sku_orders", ""),
                fmt_rate(v.get("click_through_rate")),
            ]
            if not is_ok(api):
                rows.append(base + [""] * 11)
                continue
            data = api.get("data") or {}
            eng = data.get("engagement_data") or {}
            perf = data.get("performance") or {}
            eng_cols = [
                eng.get("total_views", ""),
                eng.get("total_likes", ""),
                eng.get("total_comments", ""),
                eng.get("total_shares", ""),
                perf.get("video_post_time", ""),
            ]
            intervals = perf.get("intervals") or []
            if not intervals:
                rows.append(base + eng_cols + ["", "", "", "", ""])
            else:
                for iv in intervals:
                    sales = iv.get("sales") or {}
                    gmv = (sales.get("gmv") or {}).get("overall")
                    rows.append(
                        base
                        + eng_cols
                        + [
                            iv.get("start_date", ""),
                            iv.get("end_date", ""),
                            fmt_php(gmv) if gmv else "",
                            sales.get("orders_count", ""),
                            sales.get("items_sold", ""),
                        ]
                    )
        return rows

    rows = []
    for v in videos or []:
        rows.append(
            [
                str(v.get("id") or ""),
                str(v.get("title") or ""),
                str(v.get("username") or ""),
                v.get("views", ""),
                fmt_php(v.get("gmv") if isinstance(v.get("gmv"), dict) else None),
                v.get("sku_orders", ""),
                fmt_rate(v.get("click_through_rate")),
                "", "", "", "", "", "", "", "", "",
            ]
        )
    return rows


def gmv_parts(gmv_obj: dict | None) -> tuple[str, str]:
    if not gmv_obj:
        return "0.00", "PHP"
    return str(gmv_obj.get("amount", "0.00")), str(gmv_obj.get("currency", "PHP"))


def fmt_php(gmv_obj: dict | None) -> str:
    amt, cur = gmv_parts(gmv_obj if isinstance(gmv_obj, dict) else None)
    if not isinstance(gmv_obj, dict):
        amt = str(gmv_obj or "0.00")
    if cur == "PHP":
        return f"₱{amt}"
    return f"{cur} {amt}"


def fmt_rate(val: str | float | int | None) -> str:
    if val is None or val == "":
        return "0.00%"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if 0 <= f <= 1:
        return f"{f * 100:.2f}%"
    return f"{f:.2f}%"


def bd_val(breakdowns: list | None, typ: str, key: str = "amount"):
    for b in breakdowns or []:
        if b.get("type") == typ:
            val = b.get(key, b.get("amount", 0))
            if isinstance(val, dict):
                return val.get("amount", 0)
            return val
    return 0


def bd_gmv_obj(breakdowns: list | None, typ: str) -> dict:
    for b in breakdowns or []:
        if b.get("type") == typ:
            if "currency" in b:
                return {"amount": b.get("amount", "0.00"), "currency": b.get("currency", "PHP")}
            return b.get("gmv") or {"amount": "0.00", "currency": "PHP"}
    return {"amount": "0.00", "currency": "PHP"}


def shop_mode() -> str:
    """local=本土店；cross_border=跨境店（商品名/状态走全球+本地目录）。"""
    m = cfg("TTS_SHOP_MODE", "").strip().lower()
    if m in ("cross_border", "crossborder", "global", "kj", "跨境"):
        return "cross_border"
    if "跨境" in cfg("TTS_CONFIG_LABEL", ""):
        return "cross_border"
    return "local"


def catalog_api_label() -> str:
    return "全球商品+本地已发布" if shop_mode() == "cross_border" else "本地商品"


def _product_title_from_payload(p: dict) -> str:
    title = p.get("title") or ""
    if not title and isinstance(p.get("title_info"), dict):
        title = (p["title_info"] or {}).get("title") or ""
    return str(title or "")


def _index_local_products_from_global_item(p: dict, title: str, status: str) -> dict[str, dict]:
    """全球商品条目里常含各站 local product_id。"""
    out: dict[str, dict] = {}
    nested_lists = (
        p.get("products"),
        p.get("local_products"),
        p.get("published_products"),
        p.get("product_publish_info"),
    )
    for group in nested_lists:
        if not isinstance(group, list):
            continue
        for local in group:
            if not isinstance(local, dict):
                continue
            lid = str(local.get("id") or local.get("product_id") or "")
            if not lid:
                continue
            local_title = _product_title_from_payload(local) or title
            out[lid] = {
                "id": lid,
                "title": local_title,
                "status": local.get("status", status),
            }
    return out


def load_catalog_titles_from_exports(log_dir: Path) -> dict[str, dict]:
    """从本店历史 product_list JSON 补商品名（目录 API 失败时的兜底）。"""
    out: dict[str, dict] = {}
    for path in sorted(log_dir.glob("product_list_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        headers = data.get("headers") or []
        if not headers:
            continue
        id_idx = next((headers.index(k) for k in ("商品ID", "ID") if k in headers), None)
        title_idx = headers.index("商品") if "商品" in headers else None
        status_idx = headers.index("状态") if "状态" in headers else None
        if id_idx is None or title_idx is None:
            continue
        for row in data.get("rows") or []:
            if len(row) <= max(id_idx, title_idx):
                continue
            pid = str(row[id_idx] or "")
            title = str(row[title_idx] or "").strip()
            if not pid or not title or pid in out:
                continue
            status = ""
            if status_idx is not None and len(row) > status_idx:
                status = str(row[status_idx] or "")
            out[pid] = {"id": pid, "title": title, "status": status}
    return out


def load_product_snapshot_for_sku(
    log_dir: Path, start: str, end: str
) -> tuple[int | None, dict[str, dict]]:
    """SKU 单独任务：复用当日 product_list 缓存，跳过目录 API（减轻 05:00 限流）。"""
    product_by_id: dict[str, dict] = {}
    row_count = 0
    for path in (
        log_dir / f"product_list_{start}_{end}.json",
        log_dir / f".cache_product_list_{start}_{end}.json",
    ):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        headers = data.get("headers") or []
        rows = data.get("rows") or []
        if not rows:
            continue
        id_idx = next((headers.index(k) for k in ("商品ID", "ID") if k in headers), None)
        title_idx = headers.index("商品") if "商品" in headers else None
        status_idx = headers.index("状态") if "状态" in headers else None
        if id_idx is None:
            continue
        row_count = len(rows)
        for row in rows:
            if len(row) <= id_idx:
                continue
            pid = str(row[id_idx] or "")
            if not pid:
                continue
            title = (
                str(row[title_idx] or "").strip()
                if title_idx is not None and len(row) > title_idx
                else ""
            )
            status = (
                str(row[status_idx] or "")
                if status_idx is not None and len(row) > status_idx
                else ""
            )
            product_by_id[pid] = {"id": pid, "title": title, "status": status}
        if product_by_id:
            return row_count, product_by_id
    return (row_count or None), product_by_id


def main_image_url_from_payload(p: dict) -> str:
    """从 Product 详情取主图 URL（优先原图链接）。"""
    for img in p.get("main_images") or p.get("images") or []:
        if not isinstance(img, dict):
            continue
        for key in ("urls", "thumb_urls"):
            urls = img.get(key) or []
            if urls:
                return str(urls[0])
    return ""


def fetch_one_product_info(client: TikTokShopClient, token: str, product_id: str) -> dict | None:
    path = f"/product/202309/products/{product_id}"
    for attempt in range(ITEM_ATTEMPTS):
        r = client.get(path, token, {"shop_cipher": CIPHER})
        if is_ok(r):
            p = r.get("data") or {}
            title = _product_title_from_payload(p)
            info = {
                "id": product_id,
                "title": title,
                "status": p.get("status", ""),
                "image_url": main_image_url_from_payload(p),
            }
            if title or info["image_url"]:
                return info
            return None
        if r.get("code") in PRODUCT_DETAIL_SKIP_CODES:
            return None
        time.sleep(0.3 * (attempt + 1))
    return None


def fetch_product_image_url(client: TikTokShopClient, token: str, product_id: str) -> str:
    """仅拉主图 URL（已有商品名、缺图时用）。"""
    path = f"/product/202309/products/{product_id}"
    for attempt in range(ITEM_ATTEMPTS):
        r = client.get(path, token, {"shop_cipher": CIPHER})
        if is_ok(r):
            return main_image_url_from_payload(r.get("data") or {})
        if r.get("code") in PRODUCT_DETAIL_SKIP_CODES:
            return ""
        time.sleep(0.2 * (attempt + 1))
    return ""


def enrich_product_images(
    client: TikTokShopClient,
    token: str,
    catalog: dict[str, dict],
    product_ids: list[str],
    workers: int = 8,
) -> dict[str, dict]:
    """并发补全 catalog 里的 image_url（与 enrich 商品名共用 Product 详情 API）。"""
    merged = dict(catalog)
    missing = [pid for pid in product_ids if not merged.get(pid, {}).get("image_url")]
    if not missing:
        return merged
    print(f"  拉取主图 URL: {len(missing)} 个（并发 {workers}）...")
    ok = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(fetch_product_image_url, client, token, pid): pid for pid in missing}
        for fut in as_completed(futs):
            pid = futs[fut]
            url = fut.result()
            if url:
                merged.setdefault(pid, {"id": pid})
                merged[pid]["image_url"] = url
                ok += 1
    print(f"  主图 URL: {ok}/{len(missing)}")
    return merged


def product_excel_rows_with_image_urls(
    product_rows: list[dict],
    catalog: dict[str, dict],
    *,
    limit: int = 0,
) -> list[list]:
    rows: list[list] = []
    for i, r in enumerate(product_rows):
        pid = str(r.get("id") or "")
        url = ""
        if limit <= 0 or i < limit:
            url = str(catalog.get(pid, {}).get("image_url") or "")
        rows.append([url, *r["excel"]])
    return rows


def enrich_product_catalog(
    client: TikTokShopClient,
    token: str,
    catalog: dict[str, dict],
    product_ids: list[str],
    log_dir: Path,
    workers: int = 4,
) -> dict[str, dict]:
    merged = dict(catalog)
    cached = load_catalog_titles_from_exports(log_dir)
    if cached:
        hit = 0
        for pid, info in cached.items():
            if pid not in merged or not merged[pid].get("title"):
                merged[pid] = {**merged.get(pid, {}), **info}
                hit += 1
        if hit:
            print(f"  历史导出缓存补全商品名: {hit} 个")

    missing = [str(pid) for pid in product_ids if not merged.get(str(pid), {}).get("title")]
    if not missing:
        return merged

    print(f"  商品名仍缺 {len(missing)} 个，逐个查 Product 详情 API ...")
    ok = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(fetch_one_product_info, client, token, pid): pid for pid in missing}
        for fut in as_completed(futs):
            info = fut.result()
            if info:
                merged[info["id"]] = {**merged.get(info["id"], {}), **info}
                ok += 1
            if PRODUCT_DETAIL_SLEEP:
                time.sleep(PRODUCT_DETAIL_SLEEP)
    print(f"  Product 详情补全: {ok}/{len(missing)}")
    return merged


# Product 目录 API 限流（如 36009002 downstream）；遇限流指数退避重试
_CATALOG_RATE_LIMIT_CODES = frozenset({36009002, "36009002", 20001, "20001"})
_CATALOG_RATE_LIMIT_RETRIES = 4
_CATALOG_RATE_LIMIT_BASE_WAIT = 5.0


def is_rate_limit_error(resp: dict) -> bool:
    code = resp.get("code")
    if code in _CATALOG_RATE_LIMIT_CODES or str(code) in {str(c) for c in _CATALOG_RATE_LIMIT_CODES}:
        return True
    msg = str(resp.get("message") or "").lower()
    return "too many request" in msg or "rate limit" in msg


def _post_catalog_page_with_retry(
    client: TikTokShopClient,
    path: str,
    token: str,
    extra: dict,
    *,
    label: str,
) -> dict:
    last: dict = {}
    for attempt in range(_CATALOG_RATE_LIMIT_RETRIES):
        r = client.post(path, token, {}, extra)
        if is_ok(r) or not is_rate_limit_error(r):
            return r
        last = r
        if attempt < _CATALOG_RATE_LIMIT_RETRIES - 1:
            wait = _CATALOG_RATE_LIMIT_BASE_WAIT * (2**attempt) + random.uniform(0, 1.5)
            print(
                f"  {label}: code={r.get('code')} 限流，"
                f"{wait:.1f}s 后重试 ({attempt + 1}/{_CATALOG_RATE_LIMIT_RETRIES - 1})..."
            )
            time.sleep(wait)
    return last


def fetch_product_catalog_local(client: TikTokShopClient, token: str) -> dict[str, dict]:
    """seller.product.basic → 本店已发布商品（分析里的 product_id 多为这类 ID）。"""
    catalog: dict[str, dict] = {}
    page_token: str | None = None
    for _ in range(50):
        extra: dict = {"shop_cipher": CIPHER, "page_size": 100}
        if page_token:
            extra["page_token"] = page_token
        r = _post_catalog_page_with_retry(
            client,
            "/product/202309/products/search",
            token,
            extra,
            label="本地商品目录",
        )
        if not is_ok(r):
            if not catalog:
                print(f"  本地商品目录: code={r.get('code')} {str(r.get('message', ''))[:100]}")
            break
        data = r.get("data") or {}
        for p in data.get("products") or []:
            catalog[str(p.get("id"))] = p
        page_token = data.get("next_page_token") or ""
        if not page_token:
            break
        time.sleep(0.2)
    return catalog


def fetch_product_catalog_global(client: TikTokShopClient, token: str) -> dict[str, dict]:
    """seller.global_product.info → 跨境全球商品库（与本地 product_id 可能不同，合并供匹配）。"""
    catalog: dict[str, dict] = {}
    page_token: str | None = None
    for _ in range(50):
        extra: dict = {"page_size": 100}
        if page_token:
            extra["page_token"] = page_token
        r = _post_catalog_page_with_retry(
            client,
            "/product/202309/global_products/search",
            token,
            extra,
            label="全球商品目录",
        )
        if not is_ok(r):
            if not catalog:
                print(f"  全球商品目录: code={r.get('code')} {str(r.get('message', ''))[:100]}")
            break
        data = r.get("data") or {}
        items = data.get("global_products") or data.get("products") or []
        for p in items:
            pid = str(p.get("id") or p.get("global_product_id") or "")
            if not pid:
                continue
            title = _product_title_from_payload(p)
            status = p.get("status", "")
            catalog[pid] = {
                "id": pid,
                "title": title,
                "status": status,
            }
            for lid, local in _index_local_products_from_global_item(p, title, status).items():
                catalog.setdefault(lid, local)
        page_token = data.get("next_page_token") or ""
        if not page_token:
            break
        time.sleep(0.2)
    return catalog


def fetch_product_catalog(client: TikTokShopClient, token: str) -> dict[str, dict]:
    if shop_mode() == "cross_border":
        global_cat = fetch_product_catalog_global(client, token)
        local_cat = fetch_product_catalog_local(client, token)
        merged = dict(global_cat)
        for k, v in local_cat.items():
            merged.setdefault(k, v)
        print(
            f"  目录: 全球 {len(global_cat)} + 本地已发布 {len(local_cat)} "
            f"→ 合并 {len(merged)} 个（分析 API 与本土店相同，仅目录接口不同）"
        )
        return merged
    return fetch_product_catalog_local(client, token)


def is_permanent_product_detail_error(resp: dict | None, msg: str = "") -> bool:
    """详情接口明确「查不到该商品」— 非网络问题，重试无效。"""
    if resp:
        code = resp.get("code")
        if code in PRODUCT_DETAIL_SKIP_CODES or str(code) in PRODUCT_DETAIL_SKIP_CODES:
            return True
        text = " ".join(
            str(resp.get(k) or "")
            for k in ("message", "msg")
        ).lower()
        detail = str((resp.get("data") or {}).get("detail") or "").lower()
        if "product not found" in text or "product not found" in detail:
            return True
    return "product not found" in (msg or "").lower()


def fetch_product_interval_405(
    client: TikTokShopClient, token: str, product_id: str, start: str, end: str
) -> dict:
    path = ENDPOINTS["product_detail"].format(product_id=product_id)
    r = fetch_get(client, token, path, start, end)
    if not is_ok(r):
        return {}
    intervals = ((r.get("data") or {}).get("performance") or {}).get("intervals") or []
    return intervals[0] if intervals else {}


def fetch_product_interval_405_safe(
    client: TikTokShopClient,
    token: str,
    product_id: str,
    start: str,
    end: str,
    verbose: bool = False,
) -> tuple[dict, bool, str, bool]:
    """单条商品详情：最多 ITEM_ATTEMPTS 次。

    返回 (interval, 成功?, 失败原因, use_list_fallback)。
    use_list_fallback=True：详情 API 无此商品（已下架/非本店），用列表+rich 拼行。
    """
    from requests.exceptions import ChunkedEncodingError, ConnectionError, SSLError, Timeout

    last_msg = ""
    last_r: dict | None = None
    for attempt in range(ITEM_ATTEMPTS):
        try:
            path = ENDPOINTS["product_detail"].format(product_id=product_id)
            r = fetch_get(client, token, path, start, end)
            last_r = r
            if is_ok(r):
                intervals = ((r.get("data") or {}).get("performance") or {}).get("intervals") or []
                if verbose and attempt > 0:
                    print(f"  商品 {product_id} 第 {attempt + 1} 次请求成功")
                return (intervals[0] if intervals else {}), True, "", False
            last_msg = f"API code={r.get('code')} {r.get('message', '')}"
            if is_permanent_product_detail_error(r, last_msg):
                if verbose:
                    print(
                        f"  商品 {product_id} 详情不可用(已下架或非本店有效商品)，"
                        f"改用列表+rich 数据，不重试"
                    )
                return {}, False, last_msg, True
        except (SSLError, ConnectionError, Timeout, ChunkedEncodingError) as e:
            last_msg = f"网络: {type(e).__name__}"
        if attempt < ITEM_ATTEMPTS - 1:
            wait = 2.0 * (attempt + 1)
            if verbose:
                print(f"  商品 {product_id} 第 {attempt + 1} 次失败({last_msg})，{wait:.0f}s 后重试...")
            time.sleep(wait)
    if is_permanent_product_detail_error(last_r, last_msg):
        return {}, False, last_msg, True
    return {}, False, last_msg or "未知错误", False


def _assemble_product_row(
    item: dict, iv: dict, catalog: dict[str, dict], rich_map: dict[str, dict]
) -> dict:
    pid = str(item.get("id"))
    cat = catalog.get(pid, {})
    rich = rich_map.get(pid, {})
    gmv = iv.get("gmv") or item.get("gmv") or {}
    units = iv.get("units_sold", item.get("units_sold", item.get("items_sold", 0)))
    orders = iv.get("orders", item.get("orders", 0))

    shop = rich.get("shop_tab_performance") or {}
    card = rich.get("seller_product_card_performance") or {}
    aff_vid = rich.get("affiliate_video_performance") or {}

    live_gmv = bd_gmv_obj(iv.get("gmv_breakdowns"), "LIVE")
    video_gmv_405 = bd_gmv_obj(iv.get("gmv_breakdowns"), "VIDEO")
    video_gmv = aff_vid.get("attributed_video_gmv") or video_gmv_405
    card_gmv = card.get("attributed_gmv") or bd_gmv_obj(iv.get("gmv_breakdowns"), "PRODUCT_CARD")

    imp_total = (rich.get("total_performance") or {}).get("product_impressions")
    if imp_total is None:
        imp_total = iv.get("impressions", 0)
    return {
        "id": pid,
        "title": cat.get("title", ""),
        "status_label": STATUS_LABELS.get(cat.get("status", ""), cat.get("status", "")),
        "gmv": gmv,
        "gmv_fmt": fmt_php(gmv),
        "units_sold": units,
        "orders": orders,
        "impressions": imp_total or 0,
        "excel": [
            pid,
            cat.get("title", ""),
            STATUS_LABELS.get(cat.get("status", ""), cat.get("status", "")),
            money_cell(gmv if isinstance(gmv, dict) else None),
            str(units),
            str(orders),
            money_cell(shop.get("shop_tab_gmv")),
            str(shop.get("shop_tab_sold_items", 0)),
            str(shop.get("shop_tab_product_impressions", 0)),
            str(shop.get("shop_tab_product_clicks", 0)),
            str(shop.get("unique_shop_tab_product_clicks", 0)),
            str(shop.get("estimated_shop_tab_customers", 0)),
            fmt_rate(shop.get("shop_tab_ctr")),
            fmt_rate(shop.get("shop_tab_ctor_sku")),
            money_cell(live_gmv),
            str(bd_val(iv.get("unit_sold_breakdowns"), "LIVE")),
            str(bd_val(iv.get("impression_breakdowns"), "LIVE")),
            str(bd_val(iv.get("page_view_breakdowns"), "LIVE")),
            str(bd_val(iv.get("page_view_breakdowns"), "LIVE")),
            str(bd_val(iv.get("avg_page_visitor_breakdowns"), "LIVE")),
            fmt_rate(bd_val(iv.get("click_through_rate_breakdowns"), "LIVE")),
            "0.00%",
            money_cell(video_gmv),
            str(bd_val(iv.get("unit_sold_breakdowns"), "VIDEO")),
            str(aff_vid.get("product_impressions", bd_val(iv.get("impression_breakdowns"), "VIDEO"))),
            str(aff_vid.get("product_clicks", bd_val(iv.get("page_view_breakdowns"), "VIDEO"))),
            str(aff_vid.get("unique_clicks", bd_val(iv.get("page_view_breakdowns"), "VIDEO"))),
            str(aff_vid.get("unique_product_impressions", bd_val(iv.get("avg_page_visitor_breakdowns"), "VIDEO"))),
            fmt_rate(aff_vid.get("ctr", bd_val(iv.get("click_through_rate_breakdowns"), "VIDEO"))),
            fmt_rate(aff_vid.get("click_order_rate")),
            money_cell(card_gmv),
            str(card.get("attributed_sold_items", bd_val(iv.get("unit_sold_breakdowns"), "PRODUCT_CARD"))),
            str(card.get("product_impressions", bd_val(iv.get("impression_breakdowns"), "PRODUCT_CARD"))),
            str(card.get("product_clicks", bd_val(iv.get("page_view_breakdowns"), "PRODUCT_CARD"))),
            str(card.get("unique_clicks", bd_val(iv.get("page_view_breakdowns"), "PRODUCT_CARD"))),
            str(card.get("estimated_customers", bd_val(iv.get("avg_page_visitor_breakdowns"), "PRODUCT_CARD"))),
            fmt_rate(card.get("ctr", bd_val(iv.get("click_through_rate_breakdowns"), "PRODUCT_CARD"))),
            fmt_rate(card.get("click_order_rate")),
        ],
    }


def _fetch_one_product_row(
    client: TikTokShopClient,
    token: str,
    start: str,
    end: str,
    item: dict,
    rich_map: dict[str, dict],
    catalog: dict[str, dict],
) -> tuple[dict | None, str | None, bool]:
    pid = str(item.get("id"))
    iv, ok, _, use_list = fetch_product_interval_405_safe(client, token, pid, start, end)
    if PRODUCT_DETAIL_SLEEP > 0:
        time.sleep(PRODUCT_DETAIL_SLEEP)
    if ok or use_list:
        return _assemble_product_row(item, iv if ok else {}, catalog, rich_map), None, use_list
    return None, pid, False


def retry_failed_products(
    client: TikTokShopClient,
    token: str,
    start: str,
    end: str,
    list_items: list[dict],
    rich_map: dict[str, dict],
    catalog: dict[str, dict],
    failed_ids: list[str],
    rows: list[dict],
) -> tuple[list[dict], list[str]]:
    """对失败 ID 单独补拉（串行，避免并发 SSL），每 ID 仍 ITEM_ATTEMPTS 次/轮。"""
    if not failed_ids:
        return rows, []
    by_id = {str(x.get("id")): x for x in list_items}
    still_failed: list[str] = []
    for rnd in range(1, PRODUCT_FAILED_EXTRA_ROUNDS + 1):
        if not failed_ids:
            break
        print(
            f"\n  【补拉失败商品】第 {rnd}/{PRODUCT_FAILED_EXTRA_ROUNDS} 轮，"
            f"待补 {len(failed_ids)} 个（每条最多再试 {ITEM_ATTEMPTS} 次）..."
        )
        still_failed = []
        for pid in failed_ids:
            item = by_id.get(pid)
            if not item:
                still_failed.append(pid)
                continue
            iv, ok, msg, use_list = fetch_product_interval_405_safe(
                client, token, pid, start, end, verbose=True
            )
            if ok:
                rows.append(_assemble_product_row(item, iv, catalog, rich_map))
                print(f"    ✓ {pid} 补拉成功")
            elif use_list:
                rows.append(_assemble_product_row(item, {}, catalog, rich_map))
                print(f"    ○ {pid} 详情无记录，已用列表+rich 数据（不重试）")
            else:
                still_failed.append(pid)
                print(f"    ✗ {pid} 仍失败: {msg}")
            time.sleep(max(PRODUCT_DETAIL_SLEEP, 0.3))
        failed_ids = still_failed
        if not failed_ids:
            print(f"  失败商品已全部补拉成功（共 {len(rows)} 条商品行）")
            break
        if rnd < PRODUCT_FAILED_EXTRA_ROUNDS:
            print(f"  本轮仍失败 {len(failed_ids)} 个，{PRODUCT_FAILED_EXTRA_SLEEP}s 后开始下一轮...")
            time.sleep(PRODUCT_FAILED_EXTRA_SLEEP)
    return rows, failed_ids


def build_product_rows(
    client: TikTokShopClient,
    token: str,
    start: str,
    end: str,
    list_items: list[dict],
    rich_map: dict[str, dict],
    catalog: dict[str, dict],
    workers: int = 1,
) -> tuple[list[dict] | None, list[str]]:
    total = len(list_items)
    failed: list[str] = []
    list_fallback_ids: list[str] = []
    rows: list[dict] = []
    workers = max(1, min(16, workers))

    def absorb(row: dict | None, fid: str | None, used_list: bool, pid: str) -> None:
        if row:
            rows.append(row)
            if used_list:
                list_fallback_ids.append(pid)
        elif fid:
            failed.append(fid)

    if workers <= 1:
        for i, item in enumerate(list_items, 1):
            pid = str(item.get("id"))
            row, fid, used_list = _fetch_one_product_row(
                client, token, start, end, item, rich_map, catalog
            )
            absorb(row, fid, used_list, pid)
            if i % 10 == 0 or i == total:
                print(f"  商品详情进度 {i}/{total}...（失败 {len(failed)} 条）")
    else:
        print(f"  商品详情并发 workers={workers} ...")
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(
                    _fetch_one_product_row, client, token, start, end, item, rich_map, catalog
                ): str(item.get("id"))
                for item in list_items
            }
            for fut in as_completed(futs):
                pid = futs[fut]
                row, fid, used_list = fut.result()
                done += 1
                absorb(row, fid, used_list, pid)
                if done % 20 == 0 or done == total:
                    print(f"  商品详情进度 {done}/{total}...（失败 {len(failed)} 条，并发={workers}）")

    if list_fallback_ids:
        show = ", ".join(list_fallback_ids[:5])
        extra = f" ...等{len(list_fallback_ids)}个" if len(list_fallback_ids) > 5 else ""
        print(
            f"\n  说明: {len(list_fallback_ids)} 个商品在详情 API 返回「不存在/非本店」"
            f"（多为已下架仍有历史归因），已用列表+rich 导出: {show}{extra}"
        )

    if failed:
        print(f"\n首轮商品详情完成: 成功 {len(rows)}，失败 {len(failed)} → 启动补拉...")
        rows, failed = retry_failed_products(
            client, token, start, end, list_items, rich_map, catalog, failed, rows
        )
    if failed:
        return None, failed
    return rows, []


VIDEO_EXCEL_HEADERS = [
    "视频ID", "标题", "作者", "列表播放量", "列表GMV", "列表订单数", "点击率",
    "累计播放", "累计点赞", "累计评论", "累计分享", "发布时间",
    "区间开始", "区间结束", "区间GMV", "区间订单数", "区间成交件数",
]

SKU_EXCEL_HEADERS = [
    "SKU编号", "商品ID", "GMV", "成交件数", "订单数", "曝光", "点击", "转化率",
]


def ensure_openpyxl() -> bool:
    try:
        import openpyxl  # noqa: F401

        return True
    except ImportError:
        pass
    print("\n  正在安装 openpyxl（导出 Excel 需要）...")
    subprocess.call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
    try:
        import openpyxl  # noqa: F401

        print("  openpyxl 安装成功")
        return True
    except ImportError:
        print(f"  安装失败，请手动运行: {sys.executable} -m pip install openpyxl")
        return False


def export_table_excel(
    headers: list[str],
    rows: list[list],
    start: str,
    end: str,
    path: Path,
    table_kind: str = "",
) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = excel_sheet_title(table_kind) if table_kind else "数据"
    label = zhanfu_date_label(start, end) if is_zhanfu_export() else f"{start} ~ {end}"
    if is_zhanfu_export() and table_kind == "video":
        ws.append([f"[日期范围]: {label}\n"])
    else:
        ws.append([label])
    ws.append([])
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def stem_to_kind(stem: str) -> str:
    return {"product_list": "product", "sku_list": "sku", "video_detail": "video"}.get(stem, stem)


def skip_excel_incomplete(label: str, failed_ids: list[str], total: int) -> None:
    print(
        f"\n[{label}] 数据未拉全 ({len(failed_ids)}/{total} 条失败，"
        f"已含 API 内 {ITEM_ATTEMPTS} 次/条 + 商品补拉 {PRODUCT_FAILED_EXTRA_ROUNDS} 轮)，不导出"
    )
    show = failed_ids[:8]
    print(f"  失败 ID: {', '.join(show)}" + (f" ...等{len(failed_ids)}条" if len(failed_ids) > 8 else ""))
    print("  请改善网络后重新运行；勿使用不完整数据。")


def list_fetch_complete(meta: dict | None, has_next_page: bool = False) -> bool:
    if has_next_page:
        return False
    if not meta:
        return True
    if meta.get("error"):
        return False
    return bool(meta.get("complete", True))


def save_table_json(
    path: Path, table_name: str, headers: list[str], rows: list[list], start: str, end: str
) -> None:
    """与 Excel 同列同值；records 为 dict 列表，便于 INSERT 入库。"""
    payload = {
        "table": table_name,
        "shop": cfg("TTS_SHOP_NAME"),
        "config_label": cfg("TTS_CONFIG_LABEL", CONFIG_FILE.stem),
        "range": {"start_date_ge": start, "end_date_lt": end},
        "headers": headers,
        "rows": rows,
        "records": [dict(zip(headers, row)) for row in rows],
        "row_count": len(rows),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_path(stem: str, start: str, end: str) -> Path:
    return LOG_DIR / f".cache_{stem}_{start}_{end}.json"


def save_rows_cache(
    stem: str,
    headers: list[str],
    rows: list[list],
    start: str,
    end: str,
    *,
    zero_data: bool = False,
) -> Path:
    """缓存已拉全的表数据，Excel 失败时可 --only-export-excel 重导，无需再请求 API。"""
    p = cache_path(stem, start, end)
    payload: dict = {"headers": headers, "rows": rows}
    if zero_data:
        payload["zero_data"] = True
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def deliver_table(
    label: str,
    headers: list[str],
    rows: list[list],
    start: str,
    end: str,
    stem: str,
    args: dict,
    excel_paths: list[str],
    json_paths: list[str],
) -> bool:
    """数据齐全时写入 Excel 和/或 JSON（列与 Excel 完全一致）。"""
    if not rows:
        return False
    save_rows_cache(stem, headers, rows, start, end)
    excel_ok = False
    if args["export_excel"]:
        xlsx = LOG_DIR / export_filename(stem, start, end)
        excel_ok = try_export_excel(
            label,
            headers,
            rows,
            start,
            end,
            xlsx,
            retries=EXCEL_EXPORT_RETRIES,
            table_kind=stem_to_kind(stem),
        )
        if excel_ok:
            excel_paths.append(str(xlsx))
        else:
            jp = LOG_DIR / f"{stem}_{start}_{end}.json"
            save_table_json(jp, stem, headers, rows, start, end)
            json_paths.append(str(jp))
            print(f"\n[{label}] Excel 重试 {EXCEL_EXPORT_RETRIES} 次仍失败，数据已存 JSON:")
            print(f"  {jp}")
            print(f"  安装 openpyxl 后仅重导 Excel: python 店铺分析.py --only-export-excel")
    json_ok = False
    if args["save_tables"]:
        jp = LOG_DIR / f"{stem}_{start}_{end}.json"
        save_table_json(jp, stem, headers, rows, start, end)
        print(f"\n[{label}] JSON(等同Excel): {jp}  （{len(rows)} 行）")
        json_paths.append(str(jp))
        json_ok = True
    return excel_ok or json_ok


def try_export_excel(
    label: str,
    headers: list[str],
    rows: list[list],
    start: str,
    end: str,
    path: Path,
    retries: int = 3,
    table_kind: str = "",
) -> bool:
    if not rows:
        print(f"\n[{label}] 无数据，跳过 Excel")
        return False
    if not ensure_openpyxl():
        return False
    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            export_table_excel(headers, rows, start, end, path, table_kind=table_kind)
            print(f"\n[{label}] Excel 已保存:")
            print(f"  {path.resolve()}")
            print(f"  （{len(rows)} 行）")
            return True
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                print(f"\n[{label}] Excel 写入失败，重试 {attempt + 2}/{retries} ... ({e})")
                time.sleep(1.5)
    print(f"\n[{label}] Excel 导出失败（已重试 {retries} 次）: {last_err}")
    return False


def only_export_excel_from_cache(start: str, end: str) -> int:
    """从 .cache_* 重导 xlsx，不访问 TikTok API。"""
    print("=" * 60)
    print("仅重导 Excel（读本地缓存，不请求 API）")
    print(f"目录: {LOG_DIR.resolve()}")
    print("=" * 60)
    if not ensure_openpyxl():
        return 1
    stems = [("product_list", "商品表现"), ("video_detail", "视频详情"), ("sku_list", "SKU表现")]
    n = 0
    for stem, label in stems:
        p = cache_path(stem, start, end)
        kind = stem_to_kind(stem)
        headers = active_headers(kind)
        rows: list[list] = []
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            rows = data.get("rows") or []
        if kind == "video" and rows and is_zhanfu_export() and len(rows[0]) <= 20:
            rows = [legacy_video_row_to_zhanfu(r) for r in rows]
        if kind == "sku" and rows and is_zhanfu_export() and len(rows[0]) > 7:
            rows = [r[:7] for r in rows]
        if not rows:
            continue
        xlsx = LOG_DIR / export_filename(stem, start, end)
        if try_export_excel(
            label, headers, rows, start, end, xlsx, retries=EXCEL_EXPORT_RETRIES, table_kind=kind
        ):
            n += 1
    if n:
        print(f"\n已从缓存导出 {n} 个 Excel -> {LOG_DIR.resolve()}")
        return 0
    print(f"\n未找到缓存文件（需先成功拉取数据）: {LOG_DIR}\\.cache_*_{start}_{end}.json")
    return 1


def export_product_excel(rows: list[dict], start: str, end: str, path: Path) -> None:
    export_table_excel(
        PRODUCT_EXCEL_HEADERS,
        [r["excel"] for r in rows],
        start,
        end,
        path,
    )


def print_sku_list(skus: list[dict], limit: int) -> None:
    print(f"\n[SKU 表现] 共 {len(skus)} 条")
    show = skus if limit <= 0 else skus[:limit]
    for i, s in enumerate(show, 1):
        gmv = s.get("gmv")
        if isinstance(gmv, dict) and "overall" in gmv:
            gmv = gmv.get("overall")
        print(
            f"  {i:3}. sku={s.get('id')}  product={s.get('product_id')}  "
            f"gmv={money(gmv if isinstance(gmv, dict) else None)}  units={s.get('units_sold')}"
        )


def _fetch_one_video_detail(
    client: TikTokShopClient,
    token: str,
    v: dict,
    start: str,
    end: str,
) -> tuple[dict | None, str | None]:
    vid = str(v.get("id") or "")
    if not vid:
        return None, None
    r, ok = fetch_video_detail_safe(client, token, vid, start, end)
    api_direct: dict = {}
    direct_gmv: float | None = None
    if ok:
        r409, ok409 = fetch_video_detail_safe(
            client, token, vid, start, end, endpoint_key="video_detail_direct"
        )
        if ok409:
            api_direct = r409
            direct_gmv = video_direct_gmv_from_detail(r409.get("data") or {})
    if VIDEO_DETAIL_SLEEP > 0:
        time.sleep(VIDEO_DETAIL_SLEEP)
    if not ok:
        return None, vid
    return {
        "video_id": vid,
        "list": v,
        "api": r,
        "api_direct": api_direct,
        "direct_gmv": direct_gmv,
    }, None


def fetch_video_details(
    client: TikTokShopClient,
    token: str,
    videos: list[dict],
    start: str,
    end: str,
    limit: int,
    workers: int = 1,
) -> tuple[list[dict] | None, list[str]]:
    """limit=0 表示全部；任一条失败则返回 (None, 失败id列表)。"""
    n = len(videos) if limit <= 0 else min(limit, len(videos))
    batch = videos[:n]
    failed: list[str] = []
    workers = max(1, min(16, workers))

    if workers <= 1:
        out: list[dict] = []
        for i, v in enumerate(batch, 1):
            row, fid = _fetch_one_video_detail(client, token, v, start, end)
            if fid:
                failed.append(fid)
            elif row:
                out.append(row)
            if i % 10 == 0 or i == n:
                print(f"  视频详情进度 {i}/{n}...（失败 {len(failed)} 条）")
    else:
        print(f"  视频详情并发 workers={workers} ...")
        out = []
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_fetch_one_video_detail, client, token, v, start, end) for v in batch]
            for fut in as_completed(futs):
                row, fid = fut.result()
                done += 1
                if fid:
                    failed.append(fid)
                elif row:
                    out.append(row)
                if done % 20 == 0 or done == n:
                    print(f"  视频详情进度 {done}/{n}...（失败 {len(failed)} 条，并发={workers}）")

    if failed:
        return None, failed
    return out, []


def main() -> int:
    args = parse_args()
    apply_top_config(args)
    apply_export_defaults(args)
    valid_types = {"all", "shop", "video", "product", "sku"}
    type_parts = {p.strip().lower() for p in args["type"].split(",") if p.strip()}
    if not type_parts or not type_parts <= valid_types:
        print(
            f"无效 --type={args['type']!r}，可选: all 或逗号组合 "
            f"{', '.join(sorted(valid_types - {'all'}))}"
        )
        return 1

    if not APP_SECRET or not CIPHER:
        print("错误: config.env 需配置 TTS_APP_SECRET 和 TTS_SHOP_CIPHER")
        return 1

    client = TikTokShopClient(APP_KEY, APP_SECRET)
    token = get_shop_token(client, CONFIG_FILE)
    if not token:
        return 1

    start, end, date_src = date_range(args)
    print_limit = args["print_limit"]

    if args.get("only_export_excel"):
        return only_export_excel_from_cache(start, end)

    print("=" * 60)
    mode = shop_mode()
    print(f"店铺分析 | {cfg('TTS_SHOP_NAME', 'WM Family Store')} | region={REGION} | 模式={mode}")
    print(f"时区 = {tz_label(SHOP_REGION)}（分析日期按当地自然日）")
    print(f"配置文件 = {CONFIG_FILE}")
    print(f"应用 app_key = {APP_KEY}  |  商品目录 API = {catalog_api_label()}")
    if mode == "cross_border" and (not TOKEN and not REFRESH):
        print("  ⚠ 跨境2 配置里 token/cipher 为空，请先授权: cd .. && python 正式测试.py --config 数据分析\\config_跨境2店.env")
    print(f"日志目录 = {LOG_DIR.resolve()}")
    print(f"日期(当地): {start} ~ {end}  （来源: {date_src}）")
    print(f"说明: end_date_lt={end} 不含该日；查单日请 START=当天 END=次日")
    print(
        f"开关: 格式={EXPORT_FORMAT}  Excel={args['export_excel']}  入库JSON={args['save_tables']}  "
        f"视频详情={not args['no_video_detail']}  视频并发={args['video_workers']}  "
        f"商品并发={args['product_workers']}  店名标签={EXPORT_SHOP_TAG}"
    )
    print("=" * 60)

    # 仅查单个视频详情
    if args["video_id"]:
        r = fetch_video_detail(client, token, args["video_id"], start, end)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if is_ok(r):
            print_video_detail(args["video_id"], r.get("data") or {})
        if args["save"]:
            p = LOG_DIR / f"video_{args['video_id']}.json"
            p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n已保存: {p}")
        return 0 if is_ok(r) else 1

    if "all" in type_parts:
        want = {"shop": True, "video": True, "product": True, "sku": True}
    else:
        want = {
            "shop": "shop" in type_parts,
            "video": "video" in type_parts,
            "product": "product" in type_parts,
            "sku": "sku" in type_parts,
        }

    out: dict = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "range": {"start_date_ge": start, "end_date_lt": end},
        "sections": {},
    }
    failed = 0
    excel_paths: list[str] = []
    json_paths: list[str] = []
    videos: list[dict] = []
    video_details: list[dict] = []
    video_list_meta: dict = {}
    skus: list[dict] = []
    sku_list_meta: dict = {}

    if want["shop"]:
        r = fetch_get(client, token, ENDPOINTS["shop"], start, end)
        out["sections"]["shop"] = r
        if is_ok(r):
            shop_data = r.get("data") or {}
            print_shop(shop_data)
            intervals = ((shop_data.get("performance") or {}).get("intervals") or [])
            if intervals and args["export_excel"]:
                day = zhanfu_day_tag(start, end)
                row = build_shop_data_row(intervals[0])
                xlsx = LOG_DIR / export_filename("shop_key_metrics", start, end)
                if ensure_openpyxl():
                    try:
                        export_shop_data_excel(day, SHOP_DATA_HEADERS, row, xlsx)
                        excel_paths.append(str(xlsx))
                        print(f"\n[店铺数据] Excel 已保存:")
                        print(f"  {xlsx.resolve()}")
                    except Exception as exc:
                        failed += 1
                        print(f"\n[店铺数据] Excel 导出失败: {exc}")
                if args["save_tables"]:
                    headers = ["分析日期", *SHOP_DATA_HEADERS]
                    rows = [[day, *row]]
                    save_rows_cache("shop_key_metrics", headers, rows, start, end)
                    jp = LOG_DIR / f"shop_key_metrics_{start}_{end}.json"
                    save_table_json(jp, "shop_key_metrics", headers, rows, start, end)
                    json_paths.append(str(jp))
                    print(f"\n[店铺数据] JSON: {jp}")
        else:
            failed += 1
            print(f"\n[店铺整体] 失败 code={r.get('code')} {r.get('message')}")

    if want["video"]:
        ro = fetch_get(client, token, ENDPOINTS["video_overview"], start, end)
        out["sections"]["video_overview"] = ro
        if is_ok(ro):
            print_video_overview(ro.get("data") or {})
        else:
            failed += 1
            print(f"\n[视频概览] 失败 code={ro.get('code')} {ro.get('message')}")

        if args["all_pages"]:
            videos, meta = fetch_video_list_items(
                client,
                token,
                start,
                end,
                endpoint_key="video_list",
                page_size=args["size"],
                all_pages=True,
            )
            out["sections"]["video_list"] = {
                "code": 0 if not meta.get("error") else (meta["error"] or {}).get("code"),
                "message": "paginated merge",
                "data": {"videos": videos, **{k: v for k, v in meta.items() if k != "error"}},
            }
            video_list_meta = meta
            if meta.get("error"):
                failed += 1
                print(f"\n[视频列表] 翻页中断: {meta['error'].get('message')}")
            else:
                tc = meta.get("total_count")
                print(
                    f"\n[视频列表] 已全部拉取: {len(videos)} 条"
                    + (f"（接口 total_count={tc}）" if tc is not None else "")
                    + f"，共 {meta.get('pages')} 页"
                )
        else:
            r = fetch_get(
                client, token, ENDPOINTS["video_list"], start, end, page_size=args["size"]
            )
            out["sections"]["video_list"] = r
            if is_ok(r):
                videos = extract_list(r.get("data"), "video_list")
                d = r.get("data") or {}
                nxt = d.get("next_page_token")
                video_list_meta = {"complete": not bool(nxt)}
                tc = d.get("total_count")
                print(f"\n[视频列表] 本页 {len(videos)} 条", end="")
                if tc is not None:
                    print(f" / 总计约 {tc}", end="")
                if nxt:
                    print("（仍有下一页，请加 --all 拉取全部）", end="")
                print()
            else:
                failed += 1
                print(f"\n[视频列表] 失败 code={r.get('code')} {r.get('message')}")

        plimit = print_limit if print_limit > 0 else (0 if args["all_pages"] else args["size"])
        show = videos if plimit <= 0 else videos[:plimit]
        for i, v in enumerate(show, 1):
            print_video_row(i, v)
        if plimit > 0 and len(videos) > plimit:
            print(f"  ... 还有 {len(videos) - plimit} 条，加 --print 0 打印全部")

        # 视频详情放到商品/SKU 导出之后，避免 SSL 中断导致整次无 Excel

    catalog_for_sku: dict[str, dict] | None = None

    if want["product"]:
        print(f"\n正在拉取商品目录（{catalog_api_label()}，名称/状态）...")
        catalog = fetch_product_catalog(client, token)
        print(f"  目录 {len(catalog)} 个 SKU")

        product_list_meta: dict = {}
        has_next = False
        if args["all_pages"]:
            list_items, product_list_meta = fetch_all_list_with_retry(
                client,
                token,
                "product_list",
                start,
                end,
                page_size=args["size"],
                label="商品表现",
            )
            if product_list_meta.get("error"):
                failed += 1
                list_items = list_items or []
        else:
            r = fetch_get(
                client, token, ENDPOINTS["product_list"], start, end, page_size=args["size"]
            )
            list_items = extract_list(r.get("data"), "product_list") if is_ok(r) else []
            if not is_ok(r):
                failed += 1
            d = r.get("data") or {}
            has_next = bool(d.get("next_page_token"))
            if has_next:
                print("  提示: 商品列表仍有下一页，导出 Excel 需加 --all")

        rich_items, rich_meta = fetch_all_list_with_retry(
            client,
            token,
            "product_list_rich",
            start,
            end,
            page_size=100,
            label="商品表现(分渠道)",
        )
        rich_map = {str(p.get("id")): p for p in rich_items}
        product_ids = [str(x.get("id")) for x in list_items if x.get("id")]
        catalog = enrich_product_catalog(
            client, token, catalog, product_ids, LOG_DIR, workers=args["product_workers"]
        )
        catalog_for_sku = catalog

        product_rows: list[dict] | None = None
        product_failed: list[str] = []
        list_ok = list_fetch_complete(product_list_meta, has_next) and list_fetch_complete(rich_meta)

        if list_ok and list_items:
            print(
                f"\n正在补全商品分渠道指标（共 {len(list_items)} 条，"
                f"每条 API 内重试 {ITEM_ATTEMPTS - 1} 次；失败后再补拉 {PRODUCT_FAILED_EXTRA_ROUNDS} 轮）..."
            )
            product_rows, product_failed = build_product_rows(
                client, token, start, end, list_items, rich_map, catalog, args["product_workers"]
            )
        elif args["export_excel"] or args["save_tables"]:
            print("\n[商品表现] 商品列表未翻页拉全，不导出（请加 --all）")
            failed += 1

        out["sections"]["product_rows"] = product_rows or []
        out["sections"]["product_failed_ids"] = product_failed

        if product_rows:
            plimit = print_limit if print_limit > 0 else (0 if args["all_pages"] else args["size"])
            print_product_list(product_rows, plimit)

        if args["export_excel"] or args["save_tables"]:
            if product_failed:
                skip_excel_incomplete("商品表现", product_failed, len(list_items))
                failed += 1
            elif product_rows:
                with_urls = bool(args.get("embed_images"))
                excel_rows = [r["excel"] for r in product_rows]
                if with_urls:
                    limit = int(args.get("embed_images_limit") or 0)
                    ids_for_img = [str(r["id"]) for r in product_rows if r.get("id")]
                    if limit > 0:
                        ids_for_img = ids_for_img[:limit]
                    catalog = enrich_product_images(
                        client,
                        token,
                        catalog,
                        ids_for_img,
                        workers=args.get("image_workers", PRODUCT_IMAGE_WORKERS),
                    )
                    excel_rows = product_excel_rows_with_image_urls(
                        product_rows, catalog, limit=limit
                    )
                deliver_table(
                    "商品表现",
                    active_headers("product", with_image_url=with_urls),
                    excel_rows,
                    start,
                    end,
                    "product_list",
                    args,
                    excel_paths,
                    json_paths,
                )
                nz_gmv = sum(
                    1 for r in product_rows if (r.get("gmv") or {}).get("amount", "0") not in ("0", "0.00")
                )
                nz_imp = sum(1 for r in product_rows if (r.get("impressions") or 0) > 0)
                print(f"  其中有 GMV>0 的商品: {nz_gmv} 条 | 有曝光的商品: {nz_imp} 条")
                if nz_gmv == 0:
                    print(
                        "  说明: 分析 API 该区间 GMV 均为 0，与「订单 API 有成交」可同时存在；"
                        "属 TikTok 归因/延迟口径差异，非脚本漏拉。"
                    )
            elif not list_ok:
                pass
            elif not list_items:
                print("\n[商品表现] 无商品数据，不导出")

    if want["sku"]:
        if want["product"]:
            product_hint = len(product_rows) if product_rows else len(list_items) if list_items else 0
            cooldown = float(os.environ.get("TTS_PRODUCT_SKU_COOLDOWN_SEC", "12") or "12")
            if cooldown > 0 and product_hint > 0:
                print(f"\n[SKU表现] 产品步骤已完成（{product_hint} 条），冷却 {cooldown:.0f}s 后再拉 SKU ...")
                time.sleep(cooldown)
        sku_meta: dict[str, dict] = {}
        sku_product_count: int | None = None
        product_by_id: dict[str, dict] = {}
        if want["product"]:
            sku_product_count = (
                len(product_rows)
                if product_rows
                else (len(list_items) if list_items else None)
            )
        elif is_zhanfu_export():
            snap_count, product_by_id = load_product_snapshot_for_sku(LOG_DIR, start, end)
            if snap_count and product_by_id:
                sku_product_count = snap_count
                print(
                    f"\n[SKU表现] 复用当日产品导出（{snap_count} 条 / {len(product_by_id)} 个商品），"
                    "跳过目录 API"
                )
        if is_zhanfu_export():
            if catalog_for_sku is not None:
                print("\nSKU 表复用产品步骤商品目录（跳过重复目录 API）")
                sku_meta = build_sku_meta_map(catalog_for_sku)
            elif product_by_id:
                sku_meta = {}
            else:
                print("\n正在拉取商品目录（SKU 表需要商品名/状态）...")
                catalog_raw = fetch_product_catalog(client, token)
                sku_meta = build_sku_meta_map(catalog_raw)
                catalog_size = len(sku_meta)
                if not want["product"] and catalog_size > 0:
                    sku_product_count = catalog_size
                    cooldown = float(os.environ.get("TTS_SKU_CATALOG_COOLDOWN_SEC", "15") or "15")
                    if cooldown > 0:
                        print(
                            f"\n[SKU表现] 目录已拉取（{catalog_size} 个商品），"
                            f"冷却 {cooldown:.0f}s 后再拉 SKU 表现（减轻限流）..."
                        )
                        time.sleep(cooldown)
        sku_has_next = False
        product_sales = product_sales_from_snapshot(LOG_DIR, start, end)
        has_product_snapshot = int(product_sales.get("row_count") or 0) > 0
        if args["all_pages"]:
            skus, sku_list_meta = fetch_sku_list_with_retry(
                client,
                token,
                start,
                end,
                args["size"],
                product_gmv=float(product_sales.get("gmv") or 0),
                product_orders=int(product_sales.get("orders") or 0),
                has_product_snapshot=has_product_snapshot,
            )
            out["sections"]["sku_list"] = {"data": {"skus": skus}, **sku_list_meta}
            if sku_list_meta.get("error"):
                failed += 1
        else:
            r = fetch_get(client, token, ENDPOINTS["sku_list"], start, end, page_size=args["size"])
            out["sections"]["sku_list"] = r
            skus = extract_list(r.get("data"), "sku_list") if is_ok(r) else []
            if not is_ok(r):
                failed += 1
            sku_has_next = bool((r.get("data") or {}).get("next_page_token"))
            sku_list_meta = {"complete": not sku_has_next}
        plimit = print_limit if print_limit > 0 else (0 if args["all_pages"] else args["size"])
        print_sku_list(skus, plimit)

        if args["export_excel"] or args["save_tables"]:
            sku_ok = list_fetch_complete(sku_list_meta, sku_has_next)
            if not sku_ok and skus:
                print("\n[SKU表现] 列表未拉全，不导出（请加 --all）")
                failed += 1
            elif not sku_ok and not skus:
                if sku_list_meta.get("rate_limit_suspect"):
                    print("\n[SKU表现] 限流导致无数据，标记失败（请加大店间间隔后重跑 SKU）")
                    failed += 1
                else:
                    print("\n[SKU表现] 无数据（分页未完整，按 0 条处理，不影响产品导出）")
            elif skus:
                deliver_table(
                    "SKU表现",
                    active_headers("sku"),
                    build_sku_excel_rows(skus, sku_meta, product_by_id=product_by_id or None),
                    start,
                    end,
                    "sku_list",
                    args,
                    excel_paths,
                    json_paths,
                )
            elif sku_list_meta.get("rate_limit_suspect"):
                print("\n[SKU表现] 限流导致无数据，标记失败（请加大店间间隔后重跑 SKU）")
                failed += 1
            else:
                save_rows_cache(
                    "sku_list",
                    active_headers("sku"),
                    [],
                    start,
                    end,
                    zero_data=True,
                )
                print("\n[SKU表现] API 零数据（已写缓存标记，入库时写占位行）")

    # 商品/SKU 之后再拉视频详情
    video_direct_gmv: dict[str, float] = {}
    if want["video"] and videos and (args["export_excel"] or args["save_tables"]):
        print("\n拉取 202409 视频列表（对照「视频GMV」/间接GMV）...")
        video_direct_gmv, videos_409, meta409 = load_video_direct_gmv_map(
            client,
            token,
            start,
            end,
            page_size=args["size"],
            all_pages=args["all_pages"],
        )
        if meta409.get("error"):
            failed += 1
        before = len(videos)
        videos = merge_video_lists(videos, videos_409)
        added = len(videos) - before
        print(
            f"  已对照 {len(video_direct_gmv)} 条直接 GMV"
            + (f"，从 202409 补全 {added} 条视频" if added else "")
            + f"；导出共 {len(videos)} 条"
        )

    if want["video"] and not videos and (args["export_excel"] or args["save_tables"]):
        if list_fetch_complete(video_list_meta):
            headers = active_headers("video")
            zp = cache_path("video_detail", start, end)
            zp.write_text(
                json.dumps({"headers": headers, "rows": [], "zero_data": True}, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\n[视频详情] API 零数据（已写缓存标记 {zp.name}）")
        else:
            print("\n[视频详情] 列表未拉全且无视频，不标记零数据")

    if want["video"] and videos:
        want_detail = (
            (args["detail"] or args["export_excel"] or args["save_tables"]) and not args["no_video_detail"]
        )
        video_failed: list[str] = []
        video_list_ok = list_fetch_complete(video_list_meta)

        if want_detail:
            n_detail = args["detail_n"] if args["detail_n"] > 0 else len(videos)
            print(
                f"\n正在拉取视频详情（{n_detail} 条，并发={args['video_workers']}，每条最多重试2次）..."
            )
            video_details, video_failed = fetch_video_details(
                client, token, videos, start, end, n_detail, args["video_workers"]
            )
            out["sections"]["video_details"] = video_details or []
            out["sections"]["video_failed_ids"] = video_failed
            if video_details:
                for i, item in enumerate(video_details[: min(5, len(video_details))], 1):
                    if is_ok(item["api"]):
                        print_video_detail(item["video_id"], item["api"].get("data") or {})
                if len(video_details) > 5:
                    print(f"  ... 另有 {len(video_details) - 5} 条（见 Excel）")
        elif args["no_video_detail"]:
            print("\n已跳过视频详情（--no-video-detail）")

        if args["export_excel"] or args["save_tables"]:
            if video_failed:
                skip_excel_incomplete("视频详情", video_failed, len(videos))
                failed += 1
            elif want_detail and video_details:
                if not deliver_table(
                    "视频详情",
                    active_headers("video"),
                    build_video_excel_rows(video_details, None, video_direct_gmv=video_direct_gmv),
                    start,
                    end,
                    "video_detail",
                    args,
                    excel_paths,
                    json_paths,
                ):
                    if args["export_excel"]:
                        failed += 1
            elif args["no_video_detail"]:
                if not video_list_ok:
                    print("\n[视频详情] 视频列表未拉全，不导出（请加 --all）")
                    failed += 1
                else:
                    deliver_table(
                        "视频详情(仅列表)",
                        active_headers("video"),
                        build_video_excel_rows([], videos, video_direct_gmv=video_direct_gmv),
                        start,
                        end,
                        "video_detail",
                        args,
                        excel_paths,
                        json_paths,
                    )

    summary_path = LOG_DIR / "analytics_last_summary.json"
    summary = {
        "time": out["time"],
        "range": out["range"],
        "video_count": len(videos) if want["video"] else 0,
        "product_count": len(out["sections"].get("product_rows") or []),
        "ok": failed == 0,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n摘要已保存: {summary_path}")

    if excel_paths:
        print(f"\n共 {len(excel_paths)} 个 Excel -> {LOG_DIR}")
        for p in excel_paths:
            print(f"  - {Path(p).name}")

    if json_paths:
        print(f"\n共 {len(json_paths)} 个入库 JSON（列同 Excel）-> {LOG_DIR}")
        for p in json_paths:
            print(f"  - {Path(p).name}")

    if args["save"]:
        p = LOG_DIR / f"analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完整 JSON: {p}")

    if failed:
        print(f"\n完成: 有 {failed} 项失败")
        if excel_paths or json_paths:
            print(f"已生成文件见: {LOG_DIR.resolve()}")
        if not excel_paths and json_paths:
            print("  （数据在 JSON / .cache 中，修复 openpyxl 后: python 店铺分析.py --only-export-excel）")
        return 1
    print(f"\n完成，文件目录: {LOG_DIR.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        err = str(e)
        print(f"错误: {e}")
        if "SSLError" in err or "UNEXPECTED_EOF" in err or "Connection" in err:
            print(
                "\n这是访问 open-api.tiktokglobalshop.com 时的网络/SSL 中断，"
                "不是日期或权限配错。请直接再运行一次；已自动加重试。"
                "\n每条已自动重试2次；仍失败则不会导出不完整 Excel。"
                "\n可换网络/VPN、关代理后重跑；或 --no-video-detail 仅导视频列表。"
            )
        sys.exit(1)
