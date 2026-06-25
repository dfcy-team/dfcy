# -*- coding: utf-8 -*-
"""
TikTok Shop 直播表现明细导出（API 简化版）

数据来源:
  GET /analytics/202509/shop_lives/performance
  权限: data.shop_analytics.public.read

说明: 开放平台列表接口无观看/互动/曝光、无 GMV 三列拆分、无达人 ID。
      本导出为 API 能提供的字段，便于与联盟中心平台表对照。

用法:
  python 直播明细.py --shop TK2PH --start 2026-06-21 --end 2026-06-21
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_ROOT = SCRIPT_DIR.parent
_TEST_ENV = ENV_ROOT / "test_env"
_PROJECT = SCRIPT_DIR.parents[2]
if str(_TEST_ENV) not in sys.path:
    sys.path.insert(0, str(_TEST_ENV))
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from openpyxl import Workbook

from common.timezone_util import REGION_IANA, get_timezone
from tts_client import TikTokShopClient, cfg, get_shop_token, init_shop_config, is_ok

LIVE_LIST_PATH = "/analytics/202509/shop_lives/performance"

EXCEL_HEADERS = [
    "直播ID",
    "昵称",
    "直播标题",
    "开播时间",
    "结束时间",
    "直播时长",
    "GMV",
    "24h直播GMV",
    "成交件数",
    "去重客户数",
    "添加商品数",
    "动销商品数",
    "已创建订单数",
    "SKU订单数",
    "件单价",
    "点击成交转化率",
]


def infer_region() -> str:
    r = (cfg("TTS_TARGET_REGION", "") or "PH").strip().upper()
    if r in REGION_IANA:
        return r
    tag = (cfg("TTS_EXPORT_SHOP_TAG", "") or cfg("TTS_CONFIG_LABEL", "")).upper()
    for code in REGION_IANA:
        if tag.endswith(code):
            return code
    return "PH"


def parse_day(s: str) -> datetime:
    return datetime.strptime(s.strip()[:10], "%Y-%m-%d")


def api_end_date_exclusive(end: str) -> str:
    return (parse_day(end) + timedelta(days=1)).strftime("%Y-%m-%d")


def money_amount(obj) -> float:
    if obj is None:
        return 0.0
    if isinstance(obj, dict):
        try:
            return float(obj.get("amount") or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(obj)
    except (TypeError, ValueError):
        return 0.0


def fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0h 0min"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h {m}min"


def fmt_dt(ts: int | str | None, tz_name: str) -> str:
    if ts in (None, "", 0):
        return ""
    try:
        t = int(ts)
    except (TypeError, ValueError):
        return str(ts)
    tz = get_timezone(tz_name)
    return datetime.fromtimestamp(t, tz=tz).strftime("%Y/%m/%d/ %H:%M")


def fetch_all_live_sessions(
    client: TikTokShopClient, token: str, cipher: str, start: str, end: str
) -> list[dict]:
    end_lt = api_end_date_exclusive(end)
    out: list[dict] = []
    page_token: str | None = None
    page_number = 1
    for _ in range(200):
        extra: dict = {
            "shop_cipher": cipher,
            "start_date_ge": start[:10],
            "end_date_lt": end_lt,
            "page_size": 100,
        }
        if page_token:
            extra["page_token"] = page_token
        else:
            extra["page_number"] = page_number
        r = client.get(LIVE_LIST_PATH, token, extra)
        if not is_ok(r):
            raise RuntimeError(f"直播列表 API 失败: code={r.get('code')} {r.get('message')}")
        data = r.get("data") or {}
        batch = data.get("live_stream_sessions") or []
        out.extend(batch)
        page_token = data.get("next_page_token")
        if not batch or not page_token:
            break
        page_number += 1
    return out


def build_row(session: dict, tz_name: str) -> list:
    sp = session.get("sales_performance") or {}
    try:
        st = int(session.get("start_time") or 0)
        et = int(session.get("end_time") or 0)
    except (TypeError, ValueError):
        st = et = 0
    duration = max(0, et - st) if st and et else 0
    return [
        str(session.get("id") or ""),
        str(session.get("username") or ""),
        str(session.get("title") or ""),
        fmt_dt(st, tz_name),
        fmt_dt(et, tz_name),
        fmt_duration(duration),
        round(money_amount(sp.get("gmv")), 2),
        round(money_amount(sp.get("24h_live_gmv")), 2),
        sp.get("items_sold") or 0,
        sp.get("customers") or 0,
        sp.get("products_added") or 0,
        sp.get("different_products_sold") or 0,
        sp.get("created_sku_orders") or 0,
        sp.get("sku_orders") or 0,
        round(money_amount(sp.get("avg_price")), 2),
        str(sp.get("click_to_order_rate") or "0.00%"),
    ]


def export_excel(rows: list[list], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(EXCEL_HEADERS)
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description="直播表现明细 Excel 导出（API 简化版）")
    ap.add_argument("--shop", "-s", default="TK1PH")
    ap.add_argument("--start", default="", help="开始日期（含）")
    ap.add_argument("--end", default="", help="结束日期（含）")
    ap.add_argument(
        "--output-dir",
        default=str(Path.home() / "Desktop" / "下载" / "罗盘"),
        help="输出根目录，实际写入 <根目录>/<店键>/",
    )
    args = ap.parse_args()

    if not args.start or not args.end:
        from shop_tz import default_export_inclusive_range, get_shop_tz, infer_shop_region_from_cfg

        config_pre = init_shop_config(ENV_ROOT, ["--shop", args.shop])
        region_pre = infer_shop_region_from_cfg(config_pre)
        day, _ = default_export_inclusive_range(get_shop_tz(region_pre))
        args.start = args.start or day
        args.end = args.end or day

    config = init_shop_config(ENV_ROOT, ["--shop", args.shop])
    client = TikTokShopClient(cfg("TTS_APP_KEY"), cfg("TTS_APP_SECRET"))
    client.config_path = config
    token = get_shop_token(client, config)
    if not token:
        print("无法获取 access_token")
        return 1
    cipher = cfg("TTS_SHOP_CIPHER")
    if not cipher:
        print("缺少 TTS_SHOP_CIPHER")
        return 1

    region = infer_region()
    tz_name = REGION_IANA.get(region, "Asia/Manila")
    export_tag = cfg("TTS_EXPORT_SHOP_TAG") or args.shop

    print("=" * 60)
    print(f"直播明细 API 导出 | {export_tag} | {config.name}")
    print(f"日期: {args.start} ~ {args.end} ({tz_name})")
    print(f"接口: {LIVE_LIST_PATH}")
    print("=" * 60)

    sessions = fetch_all_live_sessions(client, token, cipher, args.start, args.end)
    rows = [build_row(s, tz_name) for s in sessions]
    rows.sort(key=lambda r: (r[3] or ""), reverse=True)

    out_dir = Path(args.output_dir) / args.shop
    stem = f"{export_tag}_直播明细_API_{args.start}_{args.end}.xlsx"
    out_path = out_dir / stem
    export_excel(rows, out_path)

    gmv_rows = sum(1 for r in rows if float(r[6] or 0) > 0)
    print(f"直播场次: {len(rows)} | 有 GMV: {gmv_rows}")
    print(f"已导出: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
