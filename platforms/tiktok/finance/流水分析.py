# -*- coding: utf-8 -*-
"""
TikTok Shop 财务 API 导出 — Finance API（seller.finance.info）

【双击运行】改同目录 导出设置.ini，再双击 运行流水分析.bat
【命令行】python 流水分析.py --shop TK2PH --start 2026-05-01 --end 2026-05-21 --type all

默认 --type all 导出 6 类 Excel（命名对齐 Partner Center Finance API）:
  获取对账单、按对账单获取交易记录、按订单获取交易记录、
  获取付款记录、获取提现记录、获取未结算交易
（文件名示例 TIKTOK4号店PH_获取对账单_2026-05-01_2026-05-21.xlsx）
  同时在 Desktop\\下载\\财务\\<店名>\\ 留一份本地副本与摘要 JSON

Partner Center -> 应用 -> 管理 API -> 勾选 Finance information -> 店铺重新授权
"""

from __future__ import annotations

import configparser
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ========== 无 导出设置.ini / --shop 时的兜底 config 文件名 ==========
USE_CONFIG = "config_本土1PH店.env"
# ================================================================

BASE = Path(__file__).parent
ENV_ROOT = BASE.parent
SETTINGS_INI = BASE / "导出设置.ini"

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
    date_range_to_unix,
    infer_shop_region_from_cfg,
    get_shop_tz,
    pick_config_before_init,
    today_local,
    tz_label,
)
from tts_client import API_VERSION, TikTokShopClient, cfg, get_shop_token, init_shop_config, is_ok, strip_config_argv
from common.excel_names import (
    excel_sheet_title,
    finance_export_filename,
    finance_excel_path,
    finance_import_root,
    finance_label,
    load_finance_import_dirs,
)
from common.file_importer import finance_json_filename, finance_summary_json_filename
from common.paths import ensure_export_dirs, export_shop_dir, EXPORT_FINANCE_DIR
from common.shop_registry import load_filename_stems

FIN_VER = API_VERSION
UNSETTLED_VER = "202507"

ENDPOINTS = {
    "statements": f"/finance/{FIN_VER}/statements",
    "statement_tx": f"/finance/{FIN_VER}/statements/{{id}}/statement_transactions",
    "order_tx": f"/finance/{FIN_VER}/orders/{{id}}/statement_transactions",
    "payments": f"/finance/{FIN_VER}/payments",
    "withdrawals": f"/finance/{FIN_VER}/withdrawals",
    "unsettled": f"/finance/{UNSETTLED_VER}/orders/unsettled_transactions",
}

LIST_KEYS = {
    "statements": ("statements",),
    "statement_tx": ("statement_transactions", "transactions"),
    "order_tx": ("statement_transactions", "transactions"),
    "payments": ("payments",),
    "withdrawals": ("withdrawals",),
    "unsettled": ("transactions", "unsettled_transactions", "orders"),
}


def _yes(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "是", "on")


def load_finance_ini() -> dict:
    """读 导出设置.ini；无文件则用内置默认。"""
    d = {
        "shop_key": "",
        "start": "",
        "end": "",
        "days": 30,
        "type": "all",
        "size": 50,
        "all_pages": True,
        "export_excel": True,
        "save_json": False,
        "stmt_tx_limit": 0,
        "order_tx_limit": 0,
    }
    if not SETTINGS_INI.exists():
        return d
    cp = configparser.ConfigParser()
    cp.read(SETTINGS_INI, encoding="utf-8")
    sec = "店铺财务导出" if cp.has_section("店铺财务导出") else "流水导出"
    if not cp.has_section(sec):
        return d
    g = cp[sec]

    def _get(key: str, default: str = "") -> str:
        return g.get(key, fallback=default).strip()

    d["shop_key"] = _get("店铺键").upper()
    d["start"] = _get("开始日期")
    d["end"] = _get("结束日期")
    if _get("最近天数"):
        d["days"] = int(_get("最近天数", "30"))
    d["type"] = _get("导出类型", "all").lower() or "all"
    if _get("每页条数"):
        d["size"] = int(_get("每页条数", "50"))
    d["all_pages"] = _yes(_get("全部翻页", "是"))
    d["export_excel"] = _yes(_get("导出Excel", "是"))
    d["save_json"] = _yes(_get("保存JSON", "否"))
    if _get("对账单交易上限") or _get("结算单流水上限"):
        d["stmt_tx_limit"] = int(_get("对账单交易上限") or _get("结算单流水上限", "0"))
    if _get("按订单交易上限") or _get("订单交易上限"):
        d["order_tx_limit"] = int(_get("按订单交易上限") or _get("订单交易上限", "0"))
    return d


def _apply_ini_shop_to_argv() -> None:
    """ini 里填了店铺键且命令行未指定 --shop 时，自动加上。"""
    ini = load_finance_ini()
    shop = ini.get("shop_key", "")
    if not shop:
        return
    argv = sys.argv[1:]
    if any(a in ("--shop", "-s") for a in argv):
        return
    sys.argv[1:1] = ["--shop", shop]


_apply_ini_shop_to_argv()
pick_config_before_init(ENV_ROOT, USE_CONFIG)
CONFIG_FILE = init_shop_config(ENV_ROOT)
SHOP_REGION = infer_shop_region_from_cfg(CONFIG_FILE)
SHOP_TZ = get_shop_tz(SHOP_REGION)
REGION = SHOP_REGION
ensure_export_dirs()
LOG_DIR = export_shop_dir("finance", cfg("TTS_CONFIG_LABEL", CONFIG_FILE.stem))
_dbg = cfg("TTS_FINANCE_LOG_SUBDIR", "").strip()
if _dbg:
    LOG_DIR = LOG_DIR / _dbg
LOG_DIR.mkdir(parents=True, exist_ok=True)

APP_KEY = cfg("TTS_APP_KEY")
APP_SECRET = cfg("TTS_APP_SECRET")
TOKEN = cfg("TTS_ACCESS_TOKEN")
REFRESH = cfg("TTS_REFRESH_TOKEN")
CIPHER = cfg("TTS_SHOP_CIPHER")


def parse_args() -> dict:
    ini = load_finance_ini()
    args = {
        "type": ini["type"],
        "start": ini["start"],
        "end": ini["end"],
        "days": ini["days"],
        "page_size": ini["size"],
        "all_pages": ini["all_pages"],
        "stmt_tx_limit": ini["stmt_tx_limit"],
        "order_tx_limit": ini["order_tx_limit"],
        "export_excel": ini["export_excel"],
        "save_json": ini["save_json"],
        "from_ini": False,
    }
    argv = strip_config_argv(sys.argv[1:])
    if not argv:
        args["from_ini"] = True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--type" and i + 1 < len(argv):
            args["type"] = argv[i + 1].lower()
            i += 2
        elif a == "--start" and i + 1 < len(argv):
            args["start"] = argv[i + 1]
            i += 2
        elif a == "--end" and i + 1 < len(argv):
            args["end"] = argv[i + 1]
            i += 2
        elif a == "--days" and i + 1 < len(argv):
            args["days"] = int(argv[i + 1])
            i += 2
        elif a in ("--all", "--all-pages"):
            args["all_pages"] = True
            i += 1
        elif a == "--no-all":
            args["all_pages"] = False
            i += 1
        elif a == "--stmt-tx-limit" and i + 1 < len(argv):
            args["stmt_tx_limit"] = int(argv[i + 1])
            i += 2
        elif a == "--order-tx-limit" and i + 1 < len(argv):
            args["order_tx_limit"] = int(argv[i + 1])
            i += 2
        elif a == "--no-excel":
            args["export_excel"] = False
            i += 1
        elif a == "--save":
            args["save_json"] = True
            i += 1
        else:
            i += 1
    return args


def date_range(args: dict) -> tuple[str, str, int, int]:
    if args["start"] and args["end"]:
        start_s, end_s = args["start"], args["end"]
    else:
        fs, fe = cfg("TTS_FINANCE_START"), cfg("TTS_FINANCE_END")
        if not (fs and fe):
            fs, fe = cfg("TTS_ANALYTICS_START"), cfg("TTS_ANALYTICS_END")
        if fs and fe:
            start_s, end_s = fs, fe
        else:
            days = args["days"]
            fd = cfg("TTS_FINANCE_DAYS") or cfg("TTS_ANALYTICS_DAYS")
            if fd.isdigit():
                days = int(fd)
            end_d = today_local(SHOP_TZ)
            start_d = end_d - timedelta(days=days)
            start_s, end_s = start_d.isoformat(), end_d.isoformat()

    t0, t1 = date_range_to_unix(start_s, end_s, SHOP_TZ)
    return start_s, end_s, int(t0 or 0), int(t1 or 0)


def extract_list(data: dict | None, section: str) -> list:
    data = data or {}
    for k in LIST_KEYS.get(section, ()):
        if k in data and isinstance(data[k], list):
            return data[k]
    return []


def finance_query(cipher: str, t_start: int, t_end: int, sort_field: str) -> dict:
    return {
        "shop_cipher": cipher,
        "sort_field": sort_field,
        "page_size": 50,
        "statement_time_ge": t_start,
        "statement_time_lt": t_end,
    }


def fetch_pages(
    client: TikTokShopClient,
    token: str,
    path: str,
    section: str,
    base_query: dict,
    all_pages: bool,
    page_size: int = 50,
) -> tuple[list[dict], dict | None]:
    merged: list[dict] = []
    page_token: str | None = None
    last_err: dict | None = None
    max_pages = 200 if all_pages else 1

    for _ in range(max_pages):
        q = {**base_query, "page_size": page_size}
        if page_token:
            q["page_token"] = page_token
        r = client.get(path, token, q)
        if not is_ok(r):
            return merged, r
        data = r.get("data") or {}
        merged.extend(extract_list(data, section))
        page_token = data.get("next_page_token") or ""
        if not page_token:
            return merged, None
        time.sleep(0.25)

    return merged, {"code": -1, "message": "翻页达到上限，可能仍有下一页"}


def fetch_orders_in_range(
    client: TikTokShopClient,
    token: str,
    t_start: int,
    t_end: int,
    *,
    all_pages: bool,
    page_size: int,
) -> tuple[list[dict], dict | None]:
    merged: list[dict] = []
    page_token = ""
    max_pages = 200 if all_pages else 1
    body: dict = {}
    if t_start:
        body["create_time_ge"] = t_start
    if t_end:
        body["create_time_lt"] = t_end

    for page in range(1, max_pages + 1):
        q: dict = {
            "shop_cipher": CIPHER,
            "page_size": min(page_size, 100),
            "sort_field": "create_time",
            "sort_order": "DESC",
        }
        if page_token:
            q["page_token"] = page_token
        r = client.post(f"/order/{API_VERSION}/orders/search", token, body, q)
        if not is_ok(r):
            return merged, r
        data = r.get("data") or {}
        batch = data.get("orders") or []
        merged.extend(batch)
        page_token = data.get("next_page_token") or ""
        if page % 5 == 0 or not page_token:
            print(f"  订单列表 第{page}页 +{len(batch)} 条，累计 {len(merged)}")
        if not page_token:
            break
        time.sleep(0.2)
    return merged, None


def order_id_of(order: dict) -> str:
    return str(order.get("id") or order.get("order_id") or "")


def flatten_item(obj: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
        if isinstance(v, dict):
            out.update(flatten_item(v, key))
        elif isinstance(v, list):
            out[key] = json.dumps(v, ensure_ascii=False)
        elif v is not None:
            out[key] = str(v)
    return out


def items_to_rows(items: list[dict], extra: dict | None = None) -> tuple[list[str], list[list]]:
    if not items:
        return [], []
    flat = []
    for it in items:
        row = flatten_item(it)
        if extra:
            row.update(extra)
        flat.append(row)
    headers = sorted({k for r in flat for k in r})
    rows = [[r.get(h, "") for h in headers] for r in flat]
    return headers, rows


def export_excel(
    path: Path,
    title: str,
    headers: list[str],
    rows: list[list],
    start: str,
    end: str,
    *,
    sheet_kind: str = "",
) -> bool:
    if not rows:
        return False
    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = excel_sheet_title(sheet_kind, finance=True) if sheet_kind else title[:31]
        ws.append([f"{title}  {start} ~ {end}"])
        ws.append([])
        ws.append(headers)
        for row in rows:
            ws.append(row)
        wb.save(path)
        print(f"  Excel: {path}  ({len(rows)} 行)")
        return True
    except ImportError:
        print("  导出失败: pip install openpyxl")
        return False


def save_finance_excel(
    kind: str,
    title: str,
    headers: list[str],
    rows: list[list],
    start_s: str,
    end_s: str,
    *,
    export_tag: str,
    import_dirs: dict[str, Path],
    finance_stems: dict[str, str] | None = None,
) -> str | None:
    """主输出写到 Z 盘 店铺分析API接口\\<类型>\\，logs 目录留本地副本。"""
    fname = finance_export_filename(export_tag, kind, start_s, end_s, stems=finance_stems)
    z_path = finance_excel_path(export_tag, kind, start_s, end_s, import_dirs, stems=finance_stems)
    try:
        z_path.parent.mkdir(parents=True, exist_ok=True)
        if export_excel(z_path, title, headers, rows, start_s, end_s, sheet_kind=kind):
            try:
                local = LOG_DIR / fname
                if local.resolve() != z_path.resolve():
                    local.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(z_path, local)
            except OSError:
                pass
            return str(z_path)
    except OSError as e:
        print(f"  主目录写入失败 ({z_path.parent}): {e}")
    local = LOG_DIR / fname
    local.parent.mkdir(parents=True, exist_ok=True)
    if export_excel(local, title, headers, rows, start_s, end_s, sheet_kind=kind):
        return str(local)
    return None


def print_scope_hint(resp: dict, name: str) -> None:
    code = resp.get("code")
    print(f"\n[{name}] 失败 code={code} msg={resp.get('message')}")
    if code in (105005, 106001, 106013):
        print(
            "  需在 Partner Center -> 应用 -> 管理 API 勾选 "
            "「Finance information / seller.finance.info」后，让卖家重新授权。"
        )


def statement_id_of(st: dict) -> str:
    return str(st.get("id") or st.get("statement_id") or "")


def main() -> int:
    args = parse_args()
    valid = {
        "all",
        "all-no-unsettled",
        "statements",
        "transactions",
        "statement_tx",
        "order_tx",
        "payments",
        "withdrawals",
        "unsettled",
    }
    if args["type"] not in valid:
        print(f"无效 --type，可选: {', '.join(sorted(valid))}")
        return 1

    if not APP_SECRET or not CIPHER:
        print("错误: 需配置 TTS_APP_SECRET 和 TTS_SHOP_CIPHER")
        return 1

    client = TikTokShopClient(APP_KEY, APP_SECRET)
    token = get_shop_token(client, CONFIG_FILE)
    if not token:
        return 1

    start_s, end_s, t0, t1 = date_range(args)
    finance_stems = load_filename_stems()
    import_dirs = load_finance_import_dirs()
    export_tag = cfg("TTS_EXPORT_SHOP_TAG", "") or cfg("TTS_CONFIG_LABEL", CONFIG_FILE.stem)
    _all = args["type"] in ("all", "all-no-unsettled")
    want = {
        "statements": _all or args["type"] in ("statements", "transactions", "statement_tx"),
        "statement_tx": _all or args["type"] in ("transactions", "statement_tx"),
        "order_tx": _all or args["type"] == "order_tx",
        "payments": _all or args["type"] == "payments",
        "withdrawals": _all or args["type"] == "withdrawals",
        "unsettled": args["type"] in ("all", "unsettled"),
    }

    print("=" * 60)
    print(f"店铺财务 | {cfg('TTS_SHOP_NAME')} | region={REGION} | 配置={CONFIG_FILE.name}")
    print(f"时区 = {tz_label(SHOP_REGION)}（日期按当地时间筛选）")
    if args.get("from_ini"):
        print(f"参数来源 = {SETTINGS_INI.name}（可改开始/结束日期、导出类型）")
    print(f"日期(当地): {start_s} ~ {end_s}  (unix {t0} ~ {t1})")
    print(f"导出类型 = {args['type']}")
    print(f"导出标签 = {export_tag}")
    print(f"权限: seller.finance.info  Z盘→{finance_import_root(import_dirs)}")
    print(f"文件名示例 = {export_tag}_{finance_label('statements')}_{start_s}_{end_s}.xlsx 等 6 类")
    print(f"日志副本: {EXPORT_FINANCE_DIR / cfg('TTS_CONFIG_LABEL', CONFIG_FILE.stem)}/")
    print("=" * 60)

    failed = 0
    excel_paths: list[str] = []
    out: dict = {"range": {"start": start_s, "end": end_s}, "sections": {}}

    statements: list[dict] = []
    if want["statements"]:
        q = finance_query(CIPHER, t0, t1, "statement_time")
        statements, err = fetch_pages(
            client, token, ENDPOINTS["statements"], "statements", q, args["all_pages"], args["page_size"]
        )
        out["sections"]["statements"] = statements
        if err:
            print_scope_hint(err, finance_label("statements"))
            failed += 1
        else:
            print(f"\n[{finance_label('statements')}] {len(statements)} 条")
            for i, st in enumerate(statements[:10], 1):
                print(
                    f"  {i}. id={statement_id_of(st)}  "
                    f"time={st.get('statement_time')}  "
                    f"status={st.get('status')}  "
                    f"amount={st.get('settlement_amount') or st.get('total_amount')}"
                )
            if len(statements) > 10:
                print(f"  ... 共 {len(statements)} 条")
            if args["export_excel"] and statements:
                h, rows = items_to_rows(statements)
                saved = save_finance_excel(
                    "statements", finance_label("statements"), h, rows, start_s, end_s,
                    export_tag=export_tag, import_dirs=import_dirs, finance_stems=finance_stems,
                )
                if saved:
                    excel_paths.append(saved)

    all_tx: list[dict] = []
    all_order_tx: list[dict] = []
    if want["statement_tx"] and statements:
        limit = args["stmt_tx_limit"] or len(statements)
        targets = statements[:limit]
        print(f"\n[{finance_label('statement_tx')}] 拉取 {len(targets)} 个对账单 ...")
        for i, st in enumerate(targets, 1):
            sid = statement_id_of(st)
            if not sid:
                continue
            path = ENDPOINTS["statement_tx"].format(id=sid)
            q = {
                "shop_cipher": CIPHER,
                "sort_field": "order_create_time",
                "page_size": args["page_size"],
            }
            txs, err = fetch_pages(client, token, path, "statement_tx", q, args["all_pages"], args["page_size"])
            if err:
                print_scope_hint(err, f"{finance_label('statement_tx')} {sid}")
                failed += 1
                continue
            for tx in txs:
                tx["_statement_id"] = sid
            all_tx.extend(txs)
            if i % 5 == 0:
                print(f"  进度 {i}/{len(targets)}...")
            time.sleep(0.15)
        out["sections"]["statement_transactions"] = all_tx
        print(f"[{finance_label('statement_tx')}] 合计 {len(all_tx)} 条")
        if args["export_excel"] and all_tx:
            h, rows = items_to_rows(all_tx)
            saved = save_finance_excel(
                "statement_tx", finance_label("statement_tx"), h, rows, start_s, end_s,
                export_tag=export_tag, import_dirs=import_dirs, finance_stems=finance_stems,
            )
            if saved:
                excel_paths.append(saved)
    elif want["statement_tx"] and not statements:
        print(f"\n[{finance_label('statement_tx')}] 无对账单，跳过")

    if want["order_tx"]:
        print(f"\n[{finance_label('order_tx')}] 按日期拉订单列表，再逐单获取交易 ...")
        orders, order_err = fetch_orders_in_range(
            client, token, t0, t1, all_pages=args["all_pages"], page_size=args["page_size"]
        )
        if order_err:
            print_scope_hint(order_err, "订单列表")
            failed += 1
        elif not orders:
            print("  日期范围内无订单，跳过")
        else:
            limit = args["order_tx_limit"] or len(orders)
            targets = orders[:limit]
            print(f"  共 {len(orders)} 单，拉取前 {len(targets)} 单的交易明细 ...")
            for i, order in enumerate(targets, 1):
                oid = order_id_of(order)
                if not oid:
                    continue
                path = ENDPOINTS["order_tx"].format(id=oid)
                q = {
                    "shop_cipher": CIPHER,
                    "sort_field": "order_create_time",
                    "page_size": args["page_size"],
                }
                txs, err = fetch_pages(client, token, path, "order_tx", q, args["all_pages"], args["page_size"])
                if err:
                    print_scope_hint(err, f"{finance_label('order_tx')} {oid}")
                    failed += 1
                    continue
                for tx in txs:
                    tx["_order_id"] = oid
                all_order_tx.extend(txs)
                if i % 20 == 0:
                    print(f"  进度 {i}/{len(targets)}...")
                time.sleep(0.12)
            out["sections"]["order_transactions"] = all_order_tx
            print(f"[{finance_label('order_tx')}] 合计 {len(all_order_tx)} 条")
            if args["export_excel"] and all_order_tx:
                h, rows = items_to_rows(all_order_tx)
                saved = save_finance_excel(
                    "order_tx", finance_label("order_tx"), h, rows, start_s, end_s,
                    export_tag=export_tag, import_dirs=import_dirs, finance_stems=finance_stems,
                )
                if saved:
                    excel_paths.append(saved)
            elif args["export_excel"] and not all_order_tx:
                print("  有订单但无交易明细，不生成空 Excel")

    if want["payments"]:
        q = {
            "shop_cipher": CIPHER,
            "sort_field": "create_time",
            "page_size": args["page_size"],
            "create_time_ge": t0,
            "create_time_lt": t1,
        }
        payments, err = fetch_pages(
            client, token, ENDPOINTS["payments"], "payments", q, args["all_pages"], args["page_size"]
        )
        out["sections"]["payments"] = payments
        if err:
            print_scope_hint(err, finance_label("payments"))
            failed += 1
        else:
            print(f"\n[{finance_label('payments')}] {len(payments)} 条")
            if args["export_excel"] and payments:
                h, rows = items_to_rows(payments)
                saved = save_finance_excel(
                    "payments", finance_label("payments"), h, rows, start_s, end_s,
                    export_tag=export_tag, import_dirs=import_dirs, finance_stems=finance_stems,
                )
                if saved:
                    excel_paths.append(saved)

    if want["withdrawals"]:
        q = {
            "shop_cipher": CIPHER,
            "types": "WITHDRAW,SETTLE,TRANSFER,REVERSE",
            "page_size": args["page_size"],
            "create_time_ge": t0,
            "create_time_lt": t1,
        }
        wds, err = fetch_pages(
            client, token, ENDPOINTS["withdrawals"], "withdrawals", q, args["all_pages"], args["page_size"]
        )
        out["sections"]["withdrawals"] = wds
        if err:
            print_scope_hint(err, finance_label("withdrawals"))
            failed += 1
        else:
            print(f"\n[{finance_label('withdrawals')}] {len(wds)} 条")
            if args["export_excel"] and wds:
                h, rows = items_to_rows(wds)
                saved = save_finance_excel(
                    "withdrawals", finance_label("withdrawals"), h, rows, start_s, end_s,
                    export_tag=export_tag, import_dirs=import_dirs, finance_stems=finance_stems,
                )
                if saved:
                    excel_paths.append(saved)

    if want["unsettled"]:
        q = {"shop_cipher": CIPHER, "page_size": args["page_size"]}
        unsettled, err = fetch_pages(
            client, token, ENDPOINTS["unsettled"], "unsettled", q, args["all_pages"], args["page_size"]
        )
        out["sections"]["unsettled"] = unsettled
        if err:
            print_scope_hint(err, finance_label("unsettled"))
            code = err.get("code")
            if code in (36009009, "36009009"):
                print(f"  {finance_label('unsettled')} API 未对该应用开放，已跳过")
            elif code not in (0,):
                failed += 1
                print("  提示: 未结算接口为 202507 版，若应用未开通可忽略或联系 TikTok 开通。")
        else:
            print(f"\n[{finance_label('unsettled')}] {len(unsettled)} 条")
            if args["export_excel"] and unsettled:
                h, rows = items_to_rows(unsettled)
                saved = save_finance_excel(
                    "unsettled", finance_label("unsettled"), h, rows, start_s, end_s,
                    export_tag=export_tag, import_dirs=import_dirs, finance_stems=finance_stems,
                )
                if saved:
                    excel_paths.append(saved)

    summary = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "range": {"start": start_s, "end": end_s},
        "statements": len(statements),
        "statement_transactions": len(all_tx),
        "order_transactions": len(all_order_tx),
        "payments": len(out["sections"].get("payments") or []),
        "withdrawals": len(out["sections"].get("withdrawals") or []),
        "unsettled": len(out["sections"].get("unsettled") or []),
        "excel_files": [Path(p).name for p in excel_paths],
        "ok": failed == 0,
    }
    summary_text = json.dumps(summary, ensure_ascii=False, indent=2)
    (LOG_DIR / "finance_last_summary.json").write_text(summary_text, encoding="utf-8")
    json_dir = import_dirs.get("财务_JSON目录") or import_dirs.get("流水_JSON目录")
    if json_dir:
        try:
            json_dir.mkdir(parents=True, exist_ok=True)
            z_summary = json_dir / finance_summary_json_filename(export_tag, start_s, end_s)
            z_summary.write_text(summary_text, encoding="utf-8")
            print(f"\n摘要: {z_summary}")
        except OSError as e:
            print(f"\n摘要(Z盘写入失败，见本地): {LOG_DIR / 'finance_last_summary.json'} ({e})")
    else:
        print(f"\n摘要: {LOG_DIR / 'finance_last_summary.json'}")

    if excel_paths:
        print(f"\n共 {len(excel_paths)} 个 Excel -> {finance_import_root(import_dirs)}")
        for p in excel_paths:
            print(f"  - {p}")

    if args["save_json"]:
        json_dir = import_dirs.get("财务_JSON目录") or import_dirs.get("流水_JSON目录")
        if json_dir:
            try:
                json_dir.mkdir(parents=True, exist_ok=True)
                z_json = json_dir / finance_json_filename(export_tag, start_s, end_s)
                z_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"完整 JSON: {z_json}")
            except OSError as e:
                print(f"完整 JSON(Z盘写入失败): {e}")
        jp = LOG_DIR / f"finance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        jp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 副本: {jp}")

    if failed:
        print(f"\n完成（有 {failed} 项失败，请查 token 过期或 finance 权限）")
        return 1
    print("\n完成")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"错误: {e}")
        if "SSL" in str(e) or "Connection" in str(e):
            print("网络中断，请重试。")
        sys.exit(1)
