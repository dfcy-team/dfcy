# -*- coding: utf-8 -*-
"""
TikTok Shop 订单查询 — 列表 + 详情

【双击运行】改同目录 导出设置.ini，再双击 运行导出订单.bat
【命令行】python 订单查询.py --start 2026-05-01 --end 2026-05-21 --all

导出：Excel 主路径 Z:\\Tk每日数据\\店铺分析API接口\\订单数据表\\
      本地副本 Desktop\\下载\\订单\\<店键>\\
"""

from __future__ import annotations

import configparser
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import tzdata  # noqa: F401  # Windows 需安装 tzdata 才能用 IANA 时区名
except ImportError:
    pass

# 本脚本在 正式环境/订单/ 下；正式环境根目录用于找共享 config
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_NAME = "config_本土1PH店.env"
DEFAULT_CONFIG_REL = f"analytics/{DEFAULT_CONFIG_NAME}"

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
from tts_client import API_VERSION, TikTokShopClient, cfg, get_shop_token, init_shop_config, is_ok, strip_config_argv

_PROJECT_ROOT = _SCRIPT.parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from common.excel_names import load_order_import_dirs, order_excel_path  # noqa: E402
from common.file_importer import order_filename  # noqa: E402
from common.paths import ensure_export_dirs, export_shop_dir, resolve_current_shop_file  # noqa: E402
from common.shop_registry import load_filename_stems  # noqa: E402


def _default_config_path() -> Path | None:
    local = SCRIPT_DIR / DEFAULT_CONFIG_NAME
    if local.exists():
        return local
    shared = ENV_ROOT / DEFAULT_CONFIG_REL
    if shared.exists():
        return shared
    return None


def _pick_config() -> None:
    argv = sys.argv[1:]
    if any(a in ("--config", "-c", "--shop", "-s") for a in argv):
        return
    hub = ENV_ROOT / "shop"
    if hub.exists():
        try:
            if resolve_current_shop_file().exists():
                return
        except Exception:
            if (hub / "CURRENT_SHOP.txt").exists():
                return  # init_shop_config 会读 CURRENT_SHOP + app.env
    p = _default_config_path()
    if p:
        os.environ["TTS_CONFIG"] = str(p)


_pick_config()
CONFIG_FILE = init_shop_config(ENV_ROOT)
LABEL = cfg("TTS_CONFIG_LABEL", CONFIG_FILE.stem)
ORDER_IMPORT_DIRS = load_order_import_dirs()
ensure_export_dirs()
LOCAL_DIR = export_shop_dir("orders", LABEL)
LOG_DIR = LOCAL_DIR

APP_KEY = cfg("TTS_APP_KEY", "6k3vv9pooutd9")
APP_SECRET = cfg("TTS_APP_SECRET")
TOKEN = cfg("TTS_ACCESS_TOKEN")
REFRESH = cfg("TTS_REFRESH_TOKEN")
CIPHER = cfg("TTS_SHOP_CIPHER")

# 国家/地区 → IANA 时区（筛选日期与 Excel 显示均按店铺本地日界）
KNOWN_REGIONS = ("PH", "TH", "MY", "VN", "SG", "ID", "US", "GB", "MX", "BR")
REGION_IANA: dict[str, str] = {
    "PH": "Asia/Manila",
    "TH": "Asia/Bangkok",
    "MY": "Asia/Kuala_Lumpur",
    "VN": "Asia/Ho_Chi_Minh",
    "SG": "Asia/Singapore",
    "ID": "Asia/Jakarta",
    "US": "America/Los_Angeles",
    "GB": "Europe/London",
    "MX": "America/Mexico_City",
    "BR": "America/Sao_Paulo",
}
REGION_UTC_OFFSET: dict[str, int] = {
    "PH": 8,
    "TH": 7,
    "MY": 8,
    "VN": 7,
    "SG": 8,
    "ID": 7,
}


def infer_shop_region() -> str:
    """优先 config 的 TTS_TARGET_REGION，否则从店键/标签后缀推断，如 TK2PH → PH。"""
    r = cfg("TTS_TARGET_REGION", "").strip().upper()
    if r in KNOWN_REGIONS:
        return r
    for src in (
        cfg("TTS_CONFIG_LABEL", ""),
        LABEL,
        CONFIG_FILE.stem,
        cfg("TTS_EXPORT_SHOP_TAG", ""),
    ):
        u = str(src).upper().replace("-", "_")
        if u in KNOWN_REGIONS:
            return u
        for code in KNOWN_REGIONS:
            if u.endswith(code) or u.endswith(f"_{code}"):
                return code
    return "PH"


def get_shop_tz(region: str) -> timezone | ZoneInfo:
    region = (region or "PH").upper()
    name = REGION_IANA.get(region)
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    hours = REGION_UTC_OFFSET.get(region, 8)
    return timezone(timedelta(hours=hours))


SHOP_REGION = infer_shop_region()
SHOP_TZ = get_shop_tz(SHOP_REGION)
REGION = SHOP_REGION

STATUSES = {
    "UNPAID", "AWAITING_SHIPMENT", "AWAITING_COLLECTION",
    "PARTIALLY_SHIPPING", "IN_TRANSIT", "DELIVERED", "COMPLETED", "CANCELLED",
}

EXPORT_EXCEL = True
ORDER_DETAIL_CHUNK = 50
SETTINGS_INI = SCRIPT_DIR / "导出设置.ini"
MAX_PAGES_UNLIMITED = 10000  # 全部导出时的翻页上限（约 100 万单）


def _yes(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "是", "on")


def load_export_settings() -> dict:
    """双击运行时读 导出设置.ini；无文件则用内置默认。"""
    d = {
        "start": "",
        "end": "",
        "status": "",
        "size": 100,
        "all_pages": True,
        "export_excel": True,
        "save": False,
        "detail_n": 0,
        "summary_print": 10,
    }
    if not SETTINGS_INI.exists():
        return d
    cp = configparser.ConfigParser()
    cp.read(SETTINGS_INI, encoding="utf-8")
    sec = "订单导出"
    if not cp.has_section(sec):
        return d
    g = cp[sec]

    def _get(key: str, default: str = "") -> str:
        return g.get(key, fallback=default).strip()

    d["start"] = _get("开始日期")
    d["end"] = _get("结束日期")
    d["status"] = _get("订单状态").upper()
    if _get("每页条数"):
        d["size"] = int(_get("每页条数", "100"))
    d["all_pages"] = _yes(_get("全部导出", "是"))
    d["export_excel"] = _yes(_get("导出Excel", "是"))
    d["save"] = _yes(_get("保存JSON", "否"))
    if _get("控制台摘要条数"):
        d["summary_print"] = int(_get("控制台摘要条数", "10"))
    return d


def parse_local_date(s: str, tz: timezone | ZoneInfo | None = None) -> datetime | None:
    """将 YYYY-MM-DD 解析为店铺当地 00:00:00。"""
    s = (s or "").strip()
    if not s:
        return None
    z = tz or SHOP_TZ
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=z)


def date_range_to_unix(
    start: str, end: str, tz: timezone | ZoneInfo | None = None
) -> tuple[int | None, int | None]:
    """按店铺当地日界：开始日 00:00 含，结束日 23:59:59 含（lt=结束日次日 0 点）。"""
    z = tz or SHOP_TZ
    ge = lt = None
    ds = parse_local_date(start, z)
    de = parse_local_date(end, z)
    if ds:
        ge = int(ds.timestamp())
    if de:
        lt = int((de + timedelta(days=1)).timestamp())
    return ge, lt


def tz_label(region: str | None = None) -> str:
    r = (region or SHOP_REGION).upper()
    name = REGION_IANA.get(r, "")
    if name:
        return f"{r} ({name})"
    off = REGION_UTC_OFFSET.get(r, 8)
    return f"{r} (UTC+{off})"

ORDER_EXCEL_HEADERS = [
    "订单ID", "状态", "创建时间", "更新时间", "币种", "订单金额",
    "买家邮箱", "物流单号", "SKU行数", "买家留言",
]
LINE_EXCEL_HEADERS = [
    "订单ID", "订单状态", "卖家SKU", "商品ID", "商品名", "数量", "行金额", "币种",
]


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email or "-"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        return f"**@{domain}"
    return f"{name[:2]}***@{domain}"


def order_summary(o: dict) -> dict:
    payment = o.get("payment") or {}
    return {
        "order_id": o.get("id"),
        "status": o.get("status"),
        "create_time": o.get("create_time"),
        "update_time": o.get("update_time"),
        "currency": payment.get("currency") or o.get("currency"),
        "total_amount": payment.get("total_amount") or payment.get("original_total_product_price"),
        "buyer_email_masked": mask_email(o.get("buyer_email", "")),
        "tracking": o.get("tracking_number"),
        "item_count": len(o.get("line_items") or []),
    }


def fmt_ts(ts, tz: timezone | ZoneInfo | None = None, region: str | None = None) -> str:
    if ts in (None, "", 0, "0"):
        return ""
    try:
        t = int(ts)
        z = tz or SHOP_TZ
        r = (region or SHOP_REGION).upper()
        return datetime.fromtimestamp(t, tz=z).strftime("%Y-%m-%d %H:%M:%S") + f" {r}"
    except (TypeError, ValueError):
        return str(ts)


def ensure_openpyxl() -> bool:
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        pass
    print("\n  正在安装 openpyxl...")
    subprocess.call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        print(f"  请手动安装: {sys.executable} -m pip install openpyxl")
        return False


def order_excel_row(o: dict) -> list:
    payment = o.get("payment") or {}
    return [
        str(o.get("id") or ""),
        str(o.get("status") or ""),
        fmt_ts(o.get("create_time")),
        fmt_ts(o.get("update_time")),
        str(payment.get("currency") or o.get("currency") or ""),
        str(payment.get("total_amount") or payment.get("original_total_product_price") or ""),
        str(o.get("buyer_email") or ""),
        str(o.get("tracking_number") or ""),
        str(len(o.get("line_items") or [])),
        str(o.get("buyer_message") or ""),
    ]


def line_item_quantity(li: dict) -> str:
    """TikTok 订单 line_items 通常无 quantity 字段，同 SKU 多件会拆成多行，每行=1 件。"""
    for key in ("quantity", "item_quantity", "sku_quantity", "count", "qty"):
        v = li.get(key)
        if v is not None and v != "":
            return str(v)
    return "1"


def line_excel_rows(o: dict) -> list[list]:
    oid = str(o.get("id") or "")
    status = str(o.get("status") or "")
    payment = o.get("payment") or {}
    currency = str(payment.get("currency") or o.get("currency") or "")
    rows: list[list] = []
    for li in o.get("line_items") or []:
        price = li.get("sale_price") or li.get("original_price") or ""
        rows.append([
            oid,
            status,
            str(li.get("seller_sku") or ""),
            str(li.get("product_id") or ""),
            str(li.get("product_name") or ""),
            line_item_quantity(li),
            str(price),
            currency,
        ])
    return rows


def export_orders_excel(path: Path, orders: list[dict], title: str) -> bool:
    if not orders:
        print("  [Excel] 无订单数据，跳过导出")
        return False
    if not ensure_openpyxl():
        return False
    from openpyxl import Workbook

    order_rows = [order_excel_row(o) for o in orders]
    line_rows: list[list] = []
    for o in orders:
        line_rows.extend(line_excel_rows(o))

    wb = Workbook()
    ws0 = wb.active
    ws0.title = "订单"
    ws0.append([title])
    ws0.append([])
    ws0.append(ORDER_EXCEL_HEADERS)
    for row in order_rows:
        ws0.append(row)

    ws1 = wb.create_sheet("订单明细")
    ws1.append(LINE_EXCEL_HEADERS)
    for row in line_rows:
        ws1.append(row)

    wb.save(path)
    print(f"\n[Excel] 已保存: {path}")
    print(f"  订单 {len(order_rows)} 行 | 明细 {len(line_rows)} 行")
    print("  说明: Excel 含买家邮箱等敏感字段，请妥善保管")
    return True


def excel_filename(start: str = "", end: str = "", sheet_name: str = "订单数据表") -> Path:
    """主输出 Z:\\Tk每日数据\\店铺分析API接口\\订单数据表\\<标签>_订单数据表_开始_结束.xlsx"""
    tag = cfg("TTS_EXPORT_SHOP_TAG", "") or LABEL
    stems = load_filename_stems()
    stem = stems.get("order", sheet_name)
    d0 = (start or "").strip()
    d1 = (end or "").strip()
    if d0 and not d1:
        d1 = d0
    elif d1 and not d0:
        d0 = d1
    elif not d0 and not d1:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        d0 = d1 = today
    return order_excel_path(tag, d0, d1, ORDER_IMPORT_DIRS, order_stem=stem)


def mirror_order_file(z_path: Path) -> Path | None:
    """Z 盘主输出 + 本地 logs 副本（供批量 import_order_files 兜底）。"""
    import shutil

    local_name = z_path.name
    local_path = LOCAL_DIR / local_name
    z_path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.resolve() == z_path.resolve():
        return local_path
    try:
        shutil.copy2(z_path, local_path)
        return local_path
    except OSError:
        return None


def fetch_orders_detail(
    client: TikTokShopClient, token: str, order_ids: list[str]
) -> list[dict]:
    """按批拉取订单详情（含 line_items）。"""
    out: list[dict] = []
    for i in range(0, len(order_ids), ORDER_DETAIL_CHUNK):
        chunk = order_ids[i : i + ORDER_DETAIL_CHUNK]
        r = order_detail(client, token, chunk)
        if not is_ok(r):
            print(f"  订单详情拉取失败: {json.dumps(r, ensure_ascii=False)[:200]}")
            continue
        out.extend((r.get("data") or {}).get("orders") or [])
    return out


def search_orders_page(
    client: TikTokShopClient,
    token: str,
    page_size: int,
    status: str,
    page_token: str = "",
    create_time_ge: int | None = None,
    create_time_lt: int | None = None,
) -> dict:
    body: dict = {}
    if status:
        body["order_status"] = status
    if create_time_ge is not None:
        body["create_time_ge"] = create_time_ge
    if create_time_lt is not None:
        body["create_time_lt"] = create_time_lt
    q: dict = {
        "shop_cipher": CIPHER,
        "page_size": min(page_size, 100),
        "sort_field": "create_time",
        "sort_order": "DESC",
    }
    if page_token:
        q["page_token"] = page_token
    return client.post(f"/order/{API_VERSION}/orders/search", token, body, q)


def fetch_all_orders(
    client: TikTokShopClient,
    token: str,
    page_size: int,
    status: str,
    max_pages: int = MAX_PAGES_UNLIMITED,
    create_time_ge: int | None = None,
    create_time_lt: int | None = None,
) -> tuple[list[dict], int | None]:
    merged: list[dict] = []
    total: int | None = None
    page_token = ""
    for page in range(1, max_pages + 1):
        r = search_orders_page(
            client, token, page_size, status, page_token, create_time_ge, create_time_lt
        )
        if not is_ok(r):
            print(json.dumps(r, ensure_ascii=False, indent=2))
            break
        data = r.get("data") or {}
        if total is None and data.get("total_count") is not None:
            total = int(data["total_count"])
        batch = data.get("orders") or []
        merged.extend(batch)
        page_token = data.get("next_page_token") or ""
        print(f"  订单列表 第{page}页 +{len(batch)} 条，累计 {len(merged)}")
        if not page_token:
            break
        time.sleep(0.2)
    return merged, total


def parse_args() -> dict:
    ini = load_export_settings()
    args = {
        "size": ini["size"],
        "detail_n": ini["detail_n"],
        "order_id": "",
        "status": ini["status"],
        "start": ini["start"],
        "end": ini["end"],
        "save": ini["save"],
        "export_excel": ini["export_excel"],
        "all_pages": ini["all_pages"],
        "summary_print": ini["summary_print"],
        "from_ini": False,
    }
    argv = strip_config_argv(sys.argv[1:])
    if not argv:
        args["from_ini"] = True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--size" and i + 1 < len(argv):
            args["size"] = int(argv[i + 1])
            i += 2
        elif a in ("--start", "--from") and i + 1 < len(argv):
            args["start"] = argv[i + 1]
            i += 2
        elif a in ("--end", "--to") and i + 1 < len(argv):
            args["end"] = argv[i + 1]
            i += 2
        elif a == "--id" and i + 1 < len(argv):
            args["order_id"] = argv[i + 1]
            i += 2
        elif a == "--status" and i + 1 < len(argv):
            args["status"] = argv[i + 1].upper()
            i += 2
        elif a == "--save":
            args["save"] = True
            i += 1
        elif a == "--excel":
            args["export_excel"] = True
            i += 1
        elif a == "--no-excel":
            args["export_excel"] = False
            i += 1
        elif a in ("--all", "--all-pages"):
            args["all_pages"] = True
            i += 1
        elif a == "--detail" and i + 1 < len(argv):
            args["detail_n"] = int(argv[i + 1])
            i += 2
        else:
            i += 1
    return args


def print_order_summaries(orders: list[dict], limit: int) -> None:
    if limit <= 0 or not orders:
        return
    print("\n--- 列表摘要（邮箱已打码）---")
    n = len(orders)
    show = min(limit, n)
    for i, o in enumerate(orders[:show], 1):
        s = order_summary(o)
        print(f"{i:2}. id={s['order_id']}  status={s['status']}  amount={s['total_amount']} {s['currency']}")
        print(f"    tracking={s['tracking']}  email={s['buyer_email_masked']}")
    if n > show:
        print(f"    ... 另有 {n - show} 单未在控制台列出")


def order_detail(client: TikTokShopClient, token: str, order_ids: list[str]) -> dict:
    ids = ",".join(order_ids)
    return client.get(
        f"/order/{API_VERSION}/orders",
        token,
        {"shop_cipher": CIPHER, "ids": ids},
    )


def main() -> int:
    args = parse_args()
    if args["status"] and args["status"] not in STATUSES:
        print(f"无效状态，可选: {', '.join(sorted(STATUSES))}")
        return 1

    if not APP_SECRET or not CIPHER:
        print("错误: config.env 需配置 TTS_APP_SECRET 和 TTS_SHOP_CIPHER")
        return 1

    client = TikTokShopClient(APP_KEY, APP_SECRET)
    token = get_shop_token(client, CONFIG_FILE)
    if not token:
        return 1

    print("=" * 60)
    print(f"订单查询 | {cfg('TTS_SHOP_NAME', 'shop')} | region={REGION}")
    print(f"时区 = {tz_label()}（导出设置.ini 日期按此当地时间）")
    print(f"脚本目录 = {SCRIPT_DIR}")
    print(f"配置文件 = {CONFIG_FILE}")
    print(f"app_key = {APP_KEY}")
    print(f"Z盘导出 = {ORDER_IMPORT_DIRS['订单目录']}")
    print(f"本地副本 = {LOCAL_DIR.resolve()}")
    print(f"shop_cipher={CIPHER[:20]}...")
    if args["from_ini"]:
        print(f"参数来源 = {SETTINGS_INI.name}（双击运行模式）")
    if args["start"] or args["end"]:
        print(f"下单时间段(当地) = {args['start'] or '不限'} ~ {args['end'] or '不限'}  [{SHOP_REGION}]")
    print(f"全部翻页 = {'是' if args['all_pages'] else '否'} | 导出Excel = {'是' if args['export_excel'] else '否'}")
    print("=" * 60)

    create_time_ge, create_time_lt = date_range_to_unix(args["start"], args["end"])
    if args["start"] and create_time_ge is None:
        print(f"错误: 开始日期格式应为 YYYY-MM-DD，当前: {args['start']}")
        return 1
    if args["end"] and create_time_lt is None:
        print(f"错误: 结束日期格式应为 YYYY-MM-DD，当前: {args['end']}")
        return 1

    out: dict = {"time": datetime.now().isoformat(timespec="seconds"), "list": None, "details": []}

    if args["order_id"]:
        r = order_detail(client, token, [args["order_id"]])
        print(f"\n[订单详情] id={args['order_id']}")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if not is_ok(r):
            return 1
        orders = (r.get("data") or {}).get("orders") or []
        out["details"] = orders
        if orders:
            print("\n--- 摘要 ---")
            print(json.dumps(order_summary(orders[0]), ensure_ascii=False, indent=2))
        if args["save"]:
            p = LOG_DIR / f"order_{args['order_id']}.json"
            p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n完整数据(含敏感字段): {p}")
        if args["export_excel"] and orders:
            shop = cfg("TTS_SHOP_NAME", "shop")
            o0 = orders[0]
            ct = o0.get("create_time")
            day = ""
            if ct:
                try:
                    day = datetime.fromtimestamp(int(ct), tz=SHOP_TZ).strftime("%Y-%m-%d")
                except (TypeError, ValueError):
                    pass
            xlsx = excel_filename(start=day, end=day, sheet_name="订单数据表")
            export_orders_excel(
                xlsx,
                orders,
                f"{shop} | 订单 {args['order_id']}",
            )
            mirror_order_file(xlsx)
        return 0

    range_note = ""
    if args["start"] or args["end"]:
        range_note = f" 时间={args['start'] or '*'}~{args['end'] or '*'}"

    if args["all_pages"]:
        print(f"\n[订单列表] 翻页拉取全部 page_size={args['size']}" + range_note + (f" status={args['status']}" if args["status"] else ""))
        orders, total = fetch_all_orders(
            client, token, args["size"], args["status"],
            create_time_ge=create_time_ge, create_time_lt=create_time_lt,
        )
        if not orders and total is None:
            return 1
    else:
        r = search_orders_page(
            client, token, args["size"], args["status"],
            create_time_ge=create_time_ge, create_time_lt=create_time_lt,
        )
        print(f"\n[订单列表] page_size={args['size']}" + range_note + (f" status={args['status']}" if args["status"] else ""))
        if not is_ok(r):
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return 1
        data = r.get("data") or {}
        orders = data.get("orders") or []
        total = data.get("total_count", len(orders))
    print(f"共 {len(orders)} 条 | 店铺订单总数约 {total}")

    summaries = [order_summary(o) for o in orders]
    print_order_summaries(orders, args["summary_print"])

    out["list"] = {"total_count": total, "summaries": summaries, "raw_count": len(orders)}

    detail_ids = [str(o.get("id")) for o in orders[: args["detail_n"]] if o.get("id")]
    if detail_ids:
        dr = order_detail(client, token, detail_ids)
        print(f"\n[订单详情] 共 {len(detail_ids)} 单")
        if is_ok(dr):
            detail_orders = (dr.get("data") or {}).get("orders") or []
            out["details"] = detail_orders
            for o in detail_orders:
                print(f"\n>> order_id={o.get('id')} status={o.get('status')}")
                print(json.dumps(order_summary(o), ensure_ascii=False, indent=2))
                items = o.get("line_items") or []
                for li in items[:5]:
                    print(f"   SKU: {li.get('seller_sku')}  name={str(li.get('product_name',''))[:40]}  qty={line_item_quantity(li)}")
        else:
            print(json.dumps(dr, ensure_ascii=False, indent=2))

    if args["save"]:
        p = LOCAL_DIR / f"orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        full = {"orders": orders, "details": out.get("details"), "total_count": total}
        p.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完整 JSON(含买家敏感信息): {p}")

    summary_path = LOCAL_DIR / "orders_last_summary.json"
    summary_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n摘要已保存: {summary_path}")

    if args["export_excel"]:
        all_ids = [str(o.get("id")) for o in orders if o.get("id")]
        if all_ids:
            print(f"\n正在拉取 {len(all_ids)} 单详情（含 line_items，供 Excel）...")
            excel_orders = fetch_orders_detail(client, token, all_ids)
            if not excel_orders:
                excel_orders = orders
            shop = cfg("TTS_SHOP_NAME", "shop")
            tag = cfg("TTS_EXPORT_SHOP_TAG", "TIKTOK1号店PH")
            status_note = f" status={args['status']}" if args["status"] else ""
            range_title = ""
            if args["start"] or args["end"]:
                range_title = f" | {args['start'] or '...'}~{args['end'] or '...'}"
            xlsx = excel_filename(start=args["start"], end=args["end"])
            export_orders_excel(
                xlsx,
                excel_orders,
                f"{tag} | {shop} | {len(excel_orders)} 单{range_title}{status_note}",
            )
            mirror_order_file(xlsx)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
