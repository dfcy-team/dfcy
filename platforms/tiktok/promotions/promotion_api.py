# -*- coding: utf-8 -*-
"""TikTok Shop 促销 API — 读 seller.promotion.info / 写 seller.promotion.write"""

from __future__ import annotations

import configparser
import json
import sys
import time
from datetime import datetime
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_ROOT = SCRIPT_DIR.parent
_TIKTOK = ENV_ROOT
_PROJECT = SCRIPT_DIR.parents[3]
_TEST_ENV = _TIKTOK / "test_env"
_COMMON = _PROJECT / "common"
for p in (_TEST_ENV, _COMMON):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from timezone_util import REGION_IANA, get_timezone  # noqa: E402

from tts_client import API_VERSION, TikTokShopClient, cfg, init_shop_config, is_ok  # noqa: E402

ACTIVITY_VER = API_VERSION
COUPON_VER = "202406"
LOG_DIR = SCRIPT_DIR / "logs"

def ini_path() -> Path:
    p = SCRIPT_DIR / "促销配置.ini"
    return p if p.exists() else SCRIPT_DIR / "测试设置.ini"


def load_ini() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    if ini_path().exists():
        cp.read(ini_path(), encoding="utf-8")
    return cp


def ini_get(cp: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    if cp.has_option(section, key):
        return cp.get(section, key).strip()
    return default


def ini_bool(cp: configparser.ConfigParser, section: str, key: str, default: bool = True) -> bool:
    raw = ini_get(cp, section, key, "1" if default else "0").lower()
    return raw in ("1", "true", "yes", "on")


def setup_client(argv: list[str] | None = None) -> tuple[TikTokShopClient, str, str, Path]:
    argv = argv if argv is not None else sys.argv[1:]
    config_path = init_shop_config(ENV_ROOT, argv)
    client = TikTokShopClient(cfg("TTS_APP_KEY"), cfg("TTS_APP_SECRET"))
    token = cfg("TTS_ACCESS_TOKEN")
    cipher = cfg("TTS_SHOP_CIPHER")
    if not token or not cipher:
        raise RuntimeError(f"缺少 token 或 shop_cipher，请先授权: {config_path.name}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return client, token, cipher, config_path


def shop_extra(cipher: str) -> dict:
    return {"shop_cipher": cipher}


def shop_region() -> str:
    return (cfg("TTS_TARGET_REGION", "PH") or "PH").upper()


def local_tz():
    name = REGION_IANA.get(shop_region(), "Asia/Manila")
    return get_timezone(name)


def parse_local_datetime(s: str) -> int:
    """'2026-06-10 10:00' 或 '2026-06-10' → unix（店铺当地）。"""
    s = (s or "").strip()
    if not s:
        raise ValueError("日期时间为空")
    tz = local_tz()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=0, minute=0, second=0)
            return int(dt.replace(tzinfo=tz).timestamp())
        except ValueError:
            continue
    raise ValueError(f"无法解析日期时间: {s}")


def print_api_result(r: dict, label: str) -> None:
    code = r.get("code")
    ok = code == 0
    print(f"\n[{label}] {'成功' if ok else '失败'} code={code}")
    if r.get("message"):
        print(f"  {r.get('message')}")
    if ok and r.get("data"):
        print(json.dumps(r.get("data"), ensure_ascii=False, indent=2)[:3000])
    elif not ok:
        print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])


def save_json(name: str, data: dict, shop_key: str = "") -> Path:
    label = shop_key or cfg("TTS_CONFIG_LABEL", "shop")
    d = LOG_DIR / label
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已保存: {p}")
    return p


def activity_id_of(a: dict) -> str:
    return str(a.get("id") or a.get("activity_id") or "")


def coupon_id_of(c: dict) -> str:
    return str(c.get("id") or c.get("coupon_id") or "")


# ---------- 读 ----------

def search_activities_page(
    client: TikTokShopClient, token: str, cipher: str, body: dict | None = None
) -> dict:
    b = dict(body or {})
    if "page_size" not in b:
        b["page_size"] = 20
    return client.post(
        f"/promotion/{ACTIVITY_VER}/activities/search",
        token,
        b,
        shop_extra(cipher),
    )


def fetch_all_activities(client, token: str, cipher: str, page_size: int = 20) -> list[dict]:
    items: list[dict] = []
    page_token = ""
    for page in range(1, 51):
        body: dict = {"page_size": int(page_size)}
        if page_token:
            body["page_token"] = page_token
        r = search_activities_page(client, token, cipher, body)
        if not is_ok(r):
            return items
        data = r.get("data") or {}
        batch = data.get("activities") or data.get("activity_list") or []
        if isinstance(batch, dict):
            batch = list(batch.values())
        items.extend(batch)
        page_token = data.get("next_page_token") or ""
        if not page_token:
            break
        time.sleep(0.2)
    return items


def get_activity(client: TikTokShopClient, token: str, cipher: str, activity_id: str) -> dict:
    return client.get(
        f"/promotion/{ACTIVITY_VER}/activities/{activity_id}",
        token,
        shop_extra(cipher),
    )


def fetch_all_coupons(client, token: str, cipher: str, page_size: int = 20) -> list[dict]:
    items: list[dict] = []
    page_token = ""
    for page in range(1, 51):
        body: dict = {"page_size": int(page_size)}
        if page_token:
            body["page_token"] = page_token
        r = client.post(
            f"/promotion/{COUPON_VER}/coupons/search",
            token,
            body,
            shop_extra(cipher),
        )
        if not is_ok(r):
            break
        data = r.get("data") or {}
        batch = data.get("coupons") or data.get("coupon_list") or []
        if isinstance(batch, dict):
            batch = list(batch.values())
        items.extend(batch)
        page_token = data.get("next_page_token") or ""
        if not page_token:
            break
        time.sleep(0.2)
    return items


def get_coupon(client: TikTokShopClient, token: str, cipher: str, coupon_id: str) -> dict:
    return client.get(
        f"/promotion/{COUPON_VER}/coupons/{coupon_id}",
        token,
        shop_extra(cipher),
    )


# ---------- 写（需 seller.promotion.write）----------

def create_activity(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    *,
    title: str,
    activity_type: str,
    begin_time: int,
    end_time: int,
    product_level: str,
) -> dict:
    body = {
        "title": title,
        "activity_type": activity_type,
        "begin_time": int(begin_time),
        "end_time": int(end_time),
        "product_level": product_level,
    }
    return client.post(f"/promotion/{ACTIVITY_VER}/activities", token, body, shop_extra(cipher))


def update_activity(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    activity_id: str,
    *,
    title: str,
    begin_time: int,
    end_time: int,
    activity_type: str = "",
    product_level: str = "",
) -> dict:
    body: dict = {
        "title": title,
        "begin_time": int(begin_time),
        "end_time": int(end_time),
    }
    if activity_type:
        body["activity_type"] = activity_type
    if product_level:
        body["product_level"] = product_level
    return client.put(
        f"/promotion/{ACTIVITY_VER}/activities/{activity_id}",
        token,
        body,
        shop_extra(cipher),
    )


def deactivate_activity(
    client: TikTokShopClient, token: str, cipher: str, activity_id: str
) -> dict:
    return client.post(
        f"/promotion/{ACTIVITY_VER}/activities/{activity_id}/deactivate",
        token,
        {},
        shop_extra(cipher),
    )


def build_product_entry(
    *,
    product_id: str,
    activity_type: str,
    product_level: str,
    discount: str = "",
    activity_price_amount: str = "",
    quantity_limit: int = -1,
    quantity_per_user: int = -1,
    sku_id: str = "",
    sku_price: str = "",
    sku_discount: str = "",
    sku_qty_limit: int = -1,
    sku_qty_per_user: int = -1,
) -> dict:
    """按活动类型组装单个 product 节点。"""
    at = activity_type.upper()
    pl = product_level.upper()
    if pl == "VARIATION":
        sku: dict = {"id": str(sku_id)}
        if at == "DIRECT_DISCOUNT":
            sku["discount"] = str(sku_discount or discount)
        else:
            sku["activity_price_amount"] = str(sku_price or activity_price_amount)
        if sku_qty_limit != -1:
            sku["quantity_limit"] = int(sku_qty_limit)
        if sku_qty_per_user != -1:
            sku["quantity_per_user"] = int(sku_qty_per_user)
        return {
            "id": str(product_id),
            "quantity_limit": -1,
            "quantity_per_user": -1,
            "skus": [sku],
        }
    entry: dict = {"id": str(product_id)}
    if quantity_limit != -1:
        entry["quantity_limit"] = int(quantity_limit)
    if quantity_per_user != -1:
        entry["quantity_per_user"] = int(quantity_per_user)
    if at == "DIRECT_DISCOUNT":
        entry["discount"] = str(discount)
    else:
        entry["activity_price_amount"] = str(activity_price_amount)
    return entry


def update_activity_products(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    activity_id: str,
    products: list[dict],
) -> dict:
    body = {"activity_id": str(activity_id), "products": products}
    return client.put(
        f"/promotion/{ACTIVITY_VER}/activities/{activity_id}/products",
        token,
        body,
        shop_extra(cipher),
    )


def remove_activity_products(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    activity_id: str,
    *,
    product_ids: list[str] | None = None,
    sku_ids: list[str] | None = None,
) -> dict:
    body: dict = {}
    if product_ids:
        body["product_ids"] = [str(x) for x in product_ids]
    if sku_ids:
        body["sku_ids"] = [str(x) for x in sku_ids]
    return client.delete(
        f"/promotion/{ACTIVITY_VER}/activities/{activity_id}/products",
        token,
        body,
        shop_extra(cipher),
    )
