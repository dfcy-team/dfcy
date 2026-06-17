# -*- coding: utf-8 -*-
"""导出 TikTok 广告报表 Excel。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _resolve_export_dir() -> Path:
    try:
        import importlib

        paths_mod = importlib.import_module("common.paths")
        paths_mod = importlib.reload(paths_mod)
        export_dir = getattr(paths_mod, "EXPORT_ADS_DIR", None)
        if export_dir is None:
            export_dir = paths_mod.EXPORT_DATA_ROOT / "广告"
        paths_mod.ensure_export_dirs()
        return Path(export_dir)
    except Exception:
        export_dir = Path(r"C:\Users\Administrator\Desktop\下载\广告")
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir


EXPORT_DIR = _resolve_export_dir()


def _marketing_runtime():
    """按文件路径加载 runtime_loader，不依赖 sys.path。"""
    import importlib.util

    name = "tiktok_marketing_runtime_loader"
    if name in sys.modules:
        return sys.modules[name]
    path = MODULE_ROOT / "runtime_loader.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

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
    shop_label: str = "",
) -> Path:
    rt = _marketing_runtime()

    label = (shop_label or file_prefix or "").strip()
    if label:
        rt.marketing_oauth().set_active_shop_label(label)
    rc = rt.marketing_report_client()

    kind = report_kind.strip().lower()
    if kind not in ("creative", "live"):
        raise ValueError(f"未知报表类型: {report_kind}")

    if kind == "creative":
        try:
            rows = rc.fetch_product_creative_rows(
                advertiser_id,
                start_date,
                end_date,
                shop_tag=label or None,
            )
        except RuntimeError as e:
            msg = str(e)
            if "40001" in msg or "permission" in msg.lower() or "No permission" in msg:
                raise RuntimeError(
                    "广告 API 无权限或 token 已过期：权限变更后请在「广告数据」页对店铺重新授权，再导出。"
                ) from e
            raise
        suffix = "广告创意"
    else:
        camps = rc.fetch_all_campaigns(advertiser_id)
        report = rc.fetch_campaign_report(advertiser_id, start_date, end_date)
        rows = rc.build_live_rows(report, camps)
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
    p.add_argument("--shop", default="", help="店铺标签（用于选择 token）")
    args = p.parse_args()
    path = run_export(
        advertiser_id=args.advertiser,
        start_date=args.start,
        end_date=args.end,
        report_kind=args.type,
        file_prefix=args.prefix,
        shop_label=args.shop or args.prefix,
    )
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
