# -*- coding: utf-8 -*-
"""导出 TikTok 广告报表 Excel。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
EXPORT_DIR = MODULE_ROOT / "exports"

CREATIVE_HEADERS = [
    "广告计划名称",
    "广告计划 ID",
    "商品 ID",
    "创意作品类型",
    "视频标题",
    "视频 ID",
    "TikTok 账号",
    "发布时间",
    "状态",
    "授权类型",
    "成本",
    "SKU 订单数",
    "平均下单成本",
    "总收入",
    "ROI",
    "商品广告曝光数",
    "商品广告点击数",
    "商品广告点击率",
    "广告转化率",
    "广告视频播放达 2 秒播放率",
    "广告视频播放达 6 秒播放率",
    "广告视频播放达 25% 播放率",
    "广告视频播放达 50% 播放率",
    "广告视频播放达 75% 播放率",
    "广告视频完播率",
    "货币",
]

LIVE_HEADERS = [
    "直播名称",
    "启动时间",
    "状态",
    "广告计划名称",
    "广告计划 ID",
    "成本",
    "净成本",
    "SKU 订单数",
    "SKU 订单数（当前店铺）",
    "平均下单成本（当前店铺）",
    "总收入",
    "总收入（当前店铺）",
    "投资回报率 (ROI)（当前店铺）",
    "直播播放量",
    "直播播放平均成本",
    "直播播放达 10 秒播放量",
    "直播播放达 10 秒平均成本",
    "直播关注数",
    "货币",
]


def _ensure_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
    from openpyxl import Workbook

    return Workbook


def export_workbook(
    *,
    report_kind: str,
    rows: list[list],
    output_path: Path,
    headers: list[str] | None = None,
) -> Path:
    Workbook = _ensure_openpyxl()
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    hdr = headers or (CREATIVE_HEADERS if report_kind == "creative" else LIVE_HEADERS)
    ws.append(hdr)
    for row in rows:
        ws.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def run_export(
    *,
    advertiser_id: str,
    start_date: str,
    end_date: str,
    report_kind: str,
    file_prefix: str,
) -> Path:
    from report_client import (
        build_creative_rows,
        build_live_rows,
        fetch_ad_report,
        fetch_all_ads,
        fetch_all_campaigns,
        fetch_campaign_report,
    )

    kind = report_kind.strip().lower()
    if kind not in ("creative", "live"):
        raise ValueError(f"未知报表类型: {report_kind}")

    if kind == "creative":
        ads = fetch_all_ads(advertiser_id)
        report = fetch_ad_report(advertiser_id, start_date, end_date)
        rows = build_creative_rows(report, ads)
        suffix = "广告创意"
    else:
        camps = fetch_all_campaigns(advertiser_id)
        report = fetch_campaign_report(advertiser_id, start_date, end_date)
        rows = build_live_rows(report, camps)
        suffix = "直播广告"

    name = f"{file_prefix}_{suffix}_{start_date}_{end_date}.xlsx"
    out = EXPORT_DIR / name
    export_workbook(report_kind=kind, rows=rows, output_path=out)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="导出 TikTok 广告 Excel")
    p.add_argument("--advertiser", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--type", choices=["creative", "live"], required=True)
    p.add_argument("--prefix", default="ADS")
    args = p.parse_args()
    path = run_export(
        advertiser_id=args.advertiser,
        start_date=args.start,
        end_date=args.end,
        report_kind=args.type,
        file_prefix=args.prefix,
    )
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
