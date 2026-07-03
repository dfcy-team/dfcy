# -*- coding: utf-8 -*-
"""导出广告户计划级消耗（对齐站斧 Cost 表格式）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from config import API_BASE  # noqa: E402
from oauth import get_access_token, load_shop_token, set_active_shop_label  # noqa: E402
from report_client import (  # noqa: E402
    GMV_MAX_REPORT_URL,
    REPORT_URL,
    _get_json,
    _paginate_list,
    fetch_all_campaigns,
)

COST_HEADERS = [
    "日期",
    "系列名称",
    "推广系列ID",
    "现金消耗",
    "信用额度消耗",
    "广告费用赠款消耗",
    "金额",
    "币种",
    "类型",
]

GMV_MAX_STORE_URL = f"{API_BASE}/gmv_max/store/list/"


def _resolve_export_dir() -> Path:
    try:
        from common.paths import EXPORT_ADS_DIR, ensure_export_dirs

        ensure_export_dirs()
        return Path(EXPORT_ADS_DIR)
    except Exception:
        export_dir = Path(r"C:\Users\Administrator\Desktop\下载\广告")
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir


def _day_key(stat_time_day: str) -> str:
    return (stat_time_day or "")[:10]


def _resolve_gmv_store_id(advertiser_id: str, access_token: str) -> str:
    resp = _get_json(GMV_MAX_STORE_URL, access_token, {"advertiser_id": advertiser_id})
    stores = (resp.get("data") or {}).get("store_list") or []
    for store in stores:
        auth = store.get("exclusive_authorized_advertiser_info") or {}
        if str(auth.get("advertiser_id") or "") == advertiser_id and store.get("is_gmv_max_available"):
            sid = str(store.get("store_id") or "")
            if sid:
                return sid
    for store in stores:
        if store.get("is_gmv_max_available"):
            sid = str(store.get("store_id") or "")
            if sid:
                return sid
    return ""


def _fetch_gmv_max_campaign_daily(
    advertiser_id: str,
    store_id: str,
    start_date: str,
    end_date: str,
    access_token: str,
) -> list[dict]:
    if not store_id:
        return []
    return _paginate_list(
        GMV_MAX_REPORT_URL,
        access_token,
        {
            "advertiser_id": advertiser_id,
            "store_ids": [store_id],
            "dimensions": ["campaign_id", "stat_time_day"],
            "metrics": ["cost"],
            "start_date": start_date,
            "end_date": end_date,
            "page_size": 1000,
        },
    )


def _fetch_auction_campaign_daily(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    access_token: str,
) -> list[dict]:
    return _paginate_list(
        REPORT_URL,
        access_token,
        {
            "advertiser_id": advertiser_id,
            "report_type": "BASIC",
            "service_type": "AUCTION",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": ["stat_time_day", "campaign_id"],
            "metrics": ["spend", "cash_spend", "voucher_spend"],
            "start_date": start_date,
            "end_date": end_date,
            "page_size": 1000,
        },
    )


def _cost_row(
    *,
    day: str,
    campaign_id: str,
    campaign_name: str,
    amount: float,
    currency: str = "USD",
    cost_type: str = "竞价",
) -> list:
    """与站斧 Cost 表一致：消耗记在信用额度列，金额为负。"""
    spend = round(float(amount or 0), 2)
    if spend <= 0:
        return []
    neg = round(-spend, 2)
    return [
        day,
        campaign_name or campaign_id,
        campaign_id,
        0.0,
        neg,
        0.0,
        neg,
        currency,
        cost_type,
    ]


def fetch_cost_rows(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    *,
    shop_label: str = "",
    access_token: str | None = None,
) -> list[list]:
    token = access_token or get_access_token(shop_label or None)
    campaigns = fetch_all_campaigns(advertiser_id, token)
    gmv_store_id = _resolve_gmv_store_id(advertiser_id, token)

    merged: dict[tuple[str, str], dict[str, float]] = {}
    gmv_campaign_ids: set[str] = set()

    for row in _fetch_gmv_max_campaign_daily(advertiser_id, gmv_store_id, start_date, end_date, token):
        dims = row.get("dimensions") or {}
        metrics = row.get("metrics") or {}
        cid = str(dims.get("campaign_id") or "")
        day = _day_key(str(dims.get("stat_time_day") or ""))
        cost = float(metrics.get("cost") or 0)
        if not cid or not day or cost <= 0:
            continue
        gmv_campaign_ids.add(cid)
        key = (day, cid)
        merged[key] = {"cash": 0.0, "credit": cost, "voucher": 0.0}

    for row in _fetch_auction_campaign_daily(advertiser_id, start_date, end_date, token):
        dims = row.get("dimensions") or {}
        metrics = row.get("metrics") or {}
        cid = str(dims.get("campaign_id") or "")
        day = _day_key(str(dims.get("stat_time_day") or ""))
        if not cid or not day or cid in gmv_campaign_ids:
            continue
        spend = float(metrics.get("spend") or 0)
        if spend <= 0:
            continue
        cash = float(metrics.get("cash_spend") or spend)
        voucher = float(metrics.get("voucher_spend") or 0)
        credit = max(spend - cash - voucher, 0.0)
        key = (day, cid)
        merged[key] = {"cash": cash, "credit": credit, "voucher": voucher}

    out: list[list] = []
    for day, cid in sorted(merged.keys()):
        parts = merged[(day, cid)]
        camp = campaigns.get(cid) or {}
        row = _cost_row(
            day=day,
            campaign_id=cid,
            campaign_name=str(camp.get("campaign_name") or cid),
            amount=parts["cash"] + parts["credit"] + parts["voucher"],
        )
        if row:
            out.append(row)
    return out


def export_cost_workbook(
    *,
    advertiser_id: str,
    start_date: str,
    end_date: str,
    shop_label: str = "",
    output_path: Path | None = None,
) -> Path:
    label = (shop_label or "").strip()
    if label:
        set_active_shop_label(label)

    rows = fetch_cost_rows(advertiser_id, start_date, end_date, shop_label=label)
    if not rows:
        raise RuntimeError(f"未拉取到 {start_date}~{end_date} 的消耗数据（advertiser={advertiser_id}）")

    credit_sum = sum(float(r[4] or 0) for r in rows)
    rows.append(["总计", None, None, 0.0, round(credit_sum, 2), 0.0, round(credit_sum, 2), None, None])

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
    from openpyxl import Workbook

    out = output_path
    if out is None:
        from common.excel_names import cost_export_filename

        out = _resolve_export_dir() / cost_export_filename(advertiser_id, start_date, end_date)

    wb = Workbook()
    ws = wb.active
    ws.title = "sheet0"
    ws.append(COST_HEADERS)
    for row in rows:
        ws.append(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def run_export(
    *,
    advertiser_id: str,
    start_date: str,
    end_date: str,
    shop_label: str = "",
) -> Path:
    """供网站 ads_exporter 调用，与 export_excel.run_export 签名一致。"""
    label = (shop_label or "").strip()
    if label:
        set_active_shop_label(label)

    adv = (advertiser_id or "").strip()
    if not adv and label:
        from oauth import resolve_default_advertiser_id

        adv = resolve_default_advertiser_id(label)
    if not adv:
        raise ValueError("未指定 advertiser_id，且未能解析店铺默认广告户")

    from common.excel_names import cost_export_filename

    out = _resolve_export_dir() / cost_export_filename(adv, start_date, end_date)
    return export_cost_workbook(
        advertiser_id=adv,
        start_date=start_date,
        end_date=end_date,
        shop_label=label,
        output_path=out,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="导出 TikTok 广告户计划级消耗（Cost 表格式）")
    p.add_argument("--advertiser", required=True, help="广告主 ID")
    p.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    p.add_argument("--shop", default="", help="店铺 token 标签")
    p.add_argument("--out", default="", help="输出路径（可选）")
    args = p.parse_args()

    out_path = Path(args.out) if args.out else None
    path = export_cost_workbook(
        advertiser_id=args.advertiser.strip(),
        start_date=args.start.strip(),
        end_date=args.end.strip(),
        shop_label=args.shop.strip(),
        output_path=out_path,
    )
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
