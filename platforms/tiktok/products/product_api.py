# -*- coding: utf-8 -*-
"""TikTok Shop 商品写接口公共模块（改价 / 库存 / 上下架）。"""

from __future__ import annotations

import configparser
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_ROOT = SCRIPT_DIR.parent
_TEST_ENV = ENV_ROOT / "test_env"
if not (_TEST_ENV / "tts_client.py").exists():
    _LEGACY = Path(r"C:\Users\Administrator\Desktop\api测试\测试环境")
    if (_LEGACY / "tts_client.py").exists():
        _TEST_ENV = _LEGACY
if str(_TEST_ENV) not in sys.path:
    sys.path.insert(0, str(_TEST_ENV))

from tts_client import API_VERSION, TikTokShopClient, cfg, init_shop_config, is_ok  # noqa: E402

def _resolve_ini_path() -> Path:
    primary = SCRIPT_DIR / "商品配置.ini"
    legacy = SCRIPT_DIR / "测试设置.ini"
    return primary if primary.exists() else legacy


INI_PATH = _resolve_ini_path()
LOG_DIR = SCRIPT_DIR / "logs"

REGION_CURRENCY = {
    "PH": "PHP",
    "TH": "THB",
    "MY": "MYR",
    "VN": "VND",
    "SG": "SGD",
    "ID": "IDR",
}


def load_ini() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    if INI_PATH.exists():
        cp.read(INI_PATH, encoding="utf-8")
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


def shop_extra(cipher: str, page_size: int | None = None, page_token: str | None = None) -> dict:
    extra: dict = {"shop_cipher": cipher}
    if page_size is not None:
        extra["page_size"] = page_size
    if page_token:
        extra["page_token"] = page_token
    return extra


def default_currency() -> str:
    region = cfg("TTS_TARGET_REGION", "PH").upper()
    return REGION_CURRENCY.get(region, "PHP")


def search_products(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    *,
    status: str = "",
    page_size: int = 20,
    max_pages: int = 3,
) -> list[dict]:
    items: list[dict] = []
    page_token: str | None = None
    for _ in range(max_pages):
        body: dict = {}
        if status:
            body["status"] = status
        extra = shop_extra(cipher, page_size=page_size, page_token=page_token)
        r = client.post(f"/product/{API_VERSION}/products/search", token, body, extra)
        if not is_ok(r):
            raise RuntimeError(f"商品搜索失败: code={r.get('code')} {r.get('message')}")
        data = r.get("data") or {}
        items.extend(data.get("products") or [])
        page_token = data.get("next_page_token") or ""
        if not page_token:
            break
    return items


def get_product(client: TikTokShopClient, token: str, cipher: str, product_id: str) -> dict:
    r = client.get(
        f"/product/{API_VERSION}/products/{product_id}",
        token,
        shop_extra(cipher),
    )
    if not is_ok(r):
        raise RuntimeError(f"商品详情失败: code={r.get('code')} {r.get('message')}")
    return r.get("data") or {}


def update_price(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    product_id: str,
    sku_id: str,
    amount: str,
    currency: str | None = None,
) -> dict:
    body = {
        "skus": [
            {
                "id": sku_id,
                "price": {
                    "amount": str(amount),
                    "currency": currency or default_currency(),
                },
            }
        ]
    }
    return client.post(
        f"/product/{API_VERSION}/products/{product_id}/prices/update",
        token,
        body,
        shop_extra(cipher),
    )


def update_inventory(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    product_id: str,
    sku_id: str,
    warehouse_id: str,
    quantity: int,
) -> dict:
    body = {
        "skus": [
            {
                "id": sku_id,
                "inventory": [{"warehouse_id": warehouse_id, "quantity": int(quantity)}],
            }
        ]
    }
    return client.post(
        f"/product/{API_VERSION}/products/{product_id}/inventory/update",
        token,
        body,
        shop_extra(cipher),
    )


def activate_products(client: TikTokShopClient, token: str, cipher: str, product_ids: list[str]) -> dict:
    return client.post(
        f"/product/{API_VERSION}/products/activate",
        token,
        {"product_ids": product_ids},
        shop_extra(cipher),
    )


def deactivate_products(client: TikTokShopClient, token: str, cipher: str, product_ids: list[str]) -> dict:
    return client.post(
        f"/product/{API_VERSION}/products/deactivate",
        token,
        {"product_ids": product_ids},
        shop_extra(cipher),
    )


def product_status_label(product: dict) -> str:
    return str(
        product.get("status")
        or product.get("product_status")
        or (product.get("audit") or {}).get("status")
        or ""
    )


def find_sku(product: dict, sku_id: str) -> dict | None:
    sid = str(sku_id or "").strip()
    if not sid:
        return None
    for sku in product.get("skus") or []:
        if str(sku.get("id") or "") == sid:
            return sku
    return None


def sku_status_label(sku: dict) -> str:
    info = sku.get("status_info") or {}
    return str(info.get("status") or "UNKNOWN")


def sku_inventory_for(product: dict, sku_id: str) -> tuple[str, int]:
    sku = find_sku(product, sku_id)
    if not sku:
        return "", 0
    return sku_inventory_hint(sku)


def parse_id_list(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts: list[str] = []
    for chunk in text.replace(";", ",").replace("\n", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def activate_product_listing(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    product_id: str,
) -> dict:
    """商品级上架 POST /products/activate"""
    detail_before = get_product(client, token, cipher, product_id)
    status_before = product_status_label(detail_before)
    result: dict = {
        "product_id": product_id,
        "status_before": status_before,
        "status_after": status_before,
        "activate_response": None,
        "skipped": False,
        "message": "",
    }
    if status_before == "ACTIVATE":
        result["skipped"] = True
        result["message"] = "商品已在售(ACTIVATE)，无需重复上架"
        return result
    if status_before == "PENDING":
        result["skipped"] = True
        result["message"] = "商品审核中(PENDING)，请等待审核通过"
        return result

    r = activate_products(client, token, cipher, [product_id])
    result["activate_response"] = r
    if not is_ok(r):
        result["message"] = str(r.get("message") or "activate failed")
        return result

    detail_after = get_product(client, token, cipher, product_id)
    result["status_after"] = product_status_label(detail_after)
    result["message"] = "商品上架请求已提交"
    return result


def activate_sku_listing(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    product_id: str,
    sku_id: str,
    *,
    warehouse_id: str = "",
    quantity: int | None = None,
    activate_product: bool = True,
) -> dict:
    """
    SKU 级上架（TikTok 无单独 SKU activate 接口）：
    1. 必要时先商品 activate
    2. 恢复该 SKU 库存（库存>0 才可售）
    """
    detail = get_product(client, token, cipher, product_id)
    product_status = product_status_label(detail)
    sku = find_sku(detail, sku_id)
    if not sku:
        raise ValueError(f"商品 {product_id} 下未找到 SKU {sku_id}")

    wh, current_qty = sku_inventory_hint(sku)
    warehouse_id = warehouse_id or wh
    if not warehouse_id:
        warehouse_id = default_sales_warehouse_id(client, token, cipher)
    if not warehouse_id:
        raise ValueError("无法确定 warehouse_id，请在配置里填写")

    target_qty = current_qty if quantity is None else int(quantity)
    if target_qty <= 0:
        raise ValueError("SKU 上架需要 quantity > 0，请填写库存数量")

    result: dict = {
        "product_id": product_id,
        "sku_id": sku_id,
        "product_status_before": product_status,
        "product_status_after": product_status,
        "sku_status_before": sku_status_label(sku),
        "sku_status_after": sku_status_label(sku),
        "warehouse_id": warehouse_id,
        "quantity_before": current_qty,
        "quantity_after": current_qty,
        "product_activate": None,
        "inventory_update": None,
        "message": "",
    }

    if activate_product and product_status in ("SELLER_DEACTIVATED", "DRAFT", "FREEZE"):
        ar = activate_products(client, token, cipher, [product_id])
        result["product_activate"] = ar
        if not is_ok(ar):
            result["message"] = f"商品上架失败: {ar.get('message')}"
            return result
        detail = get_product(client, token, cipher, product_id)
        result["product_status_after"] = product_status_label(detail)
        sku = find_sku(detail, sku_id) or sku

    if current_qty != target_qty:
        ir = update_inventory(client, token, cipher, product_id, sku_id, warehouse_id, target_qty)
        result["inventory_update"] = ir
        if not is_ok(ir):
            result["message"] = f"SKU 库存更新失败: {ir.get('message')}"
            return result
        result["quantity_after"] = target_qty
    else:
        result["quantity_after"] = current_qty

    detail_after = get_product(client, token, cipher, product_id)
    sku_after = find_sku(detail_after, sku_id) or sku
    result["product_status_after"] = product_status_label(detail_after)
    result["sku_status_after"] = sku_status_label(sku_after)
    _, qty_after = sku_inventory_hint(sku_after)
    result["quantity_after"] = qty_after
    result["message"] = "SKU 上架完成（商品可售 + 库存已恢复）"
    return result


def first_sku(product: dict) -> dict | None:
    skus = product.get("skus") or []
    return skus[0] if skus else None


def sku_price_amount(sku: dict) -> str:
    price = sku.get("price") or {}
    if isinstance(price, dict):
        return str(price.get("amount") or price.get("sale_price") or "")
    return ""


def sku_inventory_hint(sku: dict) -> tuple[str, int]:
    inv_list = sku.get("inventory") or []
    if not inv_list:
        return "", 0
    inv = inv_list[0] if isinstance(inv_list[0], dict) else {}
    return str(inv.get("warehouse_id") or ""), int(inv.get("quantity") or 0)


def print_product_row(p: dict, index: int | None = None) -> None:
    pid = p.get("id") or p.get("product_id") or ""
    title = (p.get("title") or "")[:60]
    status = p.get("status") or ""
    prefix = f"[{index}] " if index is not None else ""
    sku = first_sku(p)
    sku_id = (sku or {}).get("id") or ""
    price = sku_price_amount(sku) if sku else ""
    wh, qty = sku_inventory_hint(sku) if sku else ("", 0)
    print(f"{prefix}id={pid}  status={status}")
    print(f"    title={title}")
    if sku_id:
        print(f"    sku={sku_id}  price={price}  warehouse={wh}  qty={qty}")


def save_json(name: str, data: object) -> Path:
    path = LOG_DIR / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def api_result_ok(r: dict) -> bool:
    return is_ok(r)


def print_api_result(r: dict, label: str = "") -> None:
    tag = f"{label} " if label else ""
    if api_result_ok(r):
        print(f"{tag}OK code=0")
        if r.get("data"):
            print(json.dumps(r.get("data"), ensure_ascii=False, indent=2)[:2000])
    else:
        print(f"{tag}FAIL code={r.get('code')} message={r.get('message')}")
        print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])


def get_sales_warehouses(client: TikTokShopClient, token: str, cipher: str) -> list[dict]:
    r = client.get(f"/logistics/{API_VERSION}/warehouses", token, shop_extra(cipher))
    if not is_ok(r):
        raise RuntimeError(f"仓库列表失败: code={r.get('code')} {r.get('message')}")
    whs = (r.get("data") or {}).get("warehouses") or []
    return [w for w in whs if w.get("type") == "SALES_WAREHOUSE" and w.get("effect_status") == "ENABLED"]


def default_sales_warehouse_id(client: TikTokShopClient, token: str, cipher: str) -> str:
    whs = get_sales_warehouses(client, token, cipher)
    for w in whs:
        if w.get("is_default"):
            return str(w.get("id") or "")
    if whs:
        return str(whs[0].get("id") or "")
    return ""


def get_category_attributes(
    client: TikTokShopClient, token: str, cipher: str, category_id: str, category_version: str = "v2"
) -> list[dict]:
    r = client.get(
        f"/product/{API_VERSION}/categories/{category_id}/attributes",
        token,
        {**shop_extra(cipher), "category_version": category_version},
    )
    if not is_ok(r):
        raise RuntimeError(f"类目属性失败: code={r.get('code')} {r.get('message')}")
    return (r.get("data") or {}).get("attributes") or []


def get_categories(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    category_version: str = "v2",
    locale: str = "",
) -> list[dict]:
    """GET /categories — 店铺可用类目树（含 is_leaf）。locale=zh-CN 返回中文名称。"""
    extra: dict = {**shop_extra(cipher), "category_version": category_version}
    if locale:
        extra["locale"] = locale
    r = client.get(
        f"/product/{API_VERSION}/categories",
        token,
        extra,
    )
    if not is_ok(r):
        raise RuntimeError(f"获取类目失败: code={r.get('code')} {r.get('message')}")
    return (r.get("data") or {}).get("categories") or []


def recommend_category(
    client: TikTokShopClient, token: str, cipher: str, title: str, description: str = ""
) -> dict:
    body = {
        "product_title": title,
        "description": description or title,
        "images": [],
        "category_version": "v2",
    }
    return client.post(
        f"/product/{API_VERSION}/categories/recommend",
        token,
        body,
        shop_extra(cipher),
    )


def upload_product_image(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    image_path: Path,
    use_case: str = "MAIN_IMAGE",
) -> str:
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在: {path}")
    mime = "image/jpeg"
    if path.suffix.lower() in (".png",):
        mime = "image/png"
    with path.open("rb") as f:
        files = {"data": (path.name, f, mime)}
        form = {"use_case": use_case}
        r = client.post_multipart(
            f"/product/{API_VERSION}/images/upload",
            token,
            files,
            form,
            None,
        )
    if not is_ok(r):
        raise RuntimeError(f"上传图片失败: code={r.get('code')} {r.get('message')}")
    data = r.get("data") or {}
    uri = data.get("uri") or ""
    if not uri and data.get("img"):
        uri = (data.get("img") or {}).get("uri") or ""
    if not uri:
        raise RuntimeError(f"上传成功但未返回 uri: {r}")
    return str(uri)


def parse_image_path_list(text: str) -> list[str]:
    """解析主图/副图路径：支持逗号、分号、竖线、换行分隔。"""
    text = (text or "").strip()
    if not text:
        return []
    for sep in (";", "|", "\n", "\r"):
        text = text.replace(sep, ",")
    return [x.strip() for x in text.split(",") if x.strip()]


def upload_product_images(
    client: TikTokShopClient,
    token: str,
    cipher: str,
    image_paths: list[Path],
    use_case: str = "MAIN_IMAGE",
) -> list[str]:
    uris: list[str] = []
    for path in image_paths:
        uris.append(upload_product_image(client, token, cipher, path, use_case))
    return uris


def load_json_file(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def attributes_template_from_api(attrs: list[dict]) -> list[dict]:
    """按类目接口生成可编辑的属性模板（每属性取第一个可选值）。"""
    out: list[dict] = []
    for a in attrs:
        values = a.get("values") or []
        if not values:
            continue
        v = values[0]
        out.append(
            {
                "id": str(a.get("id") or ""),
                "values": [{"id": str(v.get("id") or ""), "name": str(v.get("name") or "")}],
            }
        )
    return out


def parse_product_attributes(raw: object) -> list[dict]:
    if isinstance(raw, list):
        return raw
    raise ValueError("product_attributes 必须是 JSON 数组")


def parse_delivery_option_ids(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    return [x.strip() for x in text.replace(";", ",").split(",") if x.strip()]


def parse_create_skus(raw: object, warehouse_id: str, currency: str | None = None) -> list[dict]:
    """create_skus.json → API skus 数组。"""
    if not isinstance(raw, list):
        raise ValueError("create_skus.json 必须是数组")
    cur = currency or default_currency()
    out: list[dict] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"SKU 第 {i} 项必须是对象")
        seller = str(item.get("seller_sku") or "").strip()
        if not seller:
            raise ValueError(f"SKU 第 {i} 项缺少 seller_sku")
        price = str(item.get("price") or item.get("amount") or "99")
        qty = int(item.get("quantity") or 1)
        sku: dict = {
            "seller_sku": seller,
            "price": {"amount": price, "currency": cur},
            "inventory": [{"warehouse_id": warehouse_id, "quantity": qty}],
        }
        attrs = item.get("sales_attributes")
        if attrs:
            sku["sales_attributes"] = attrs
        out.append(sku)
    return out


def build_create_product_body(
    *,
    title: str,
    description: str,
    category_id: str,
    main_image_uri: str,
    product_attributes: list[dict],
    seller_sku: str,
    price_amount: str,
    warehouse_id: str,
    quantity: int,
    currency: str | None = None,
    brand_id: str = "",
    save_mode: str = "AS_DRAFT",
    is_cod_allowed: bool = True,
    delivery_option_ids: list[str] | None = None,
    package_length: str = "10",
    package_width: str = "10",
    package_height: str = "5",
    package_weight: str = "0.3",
    sales_attributes: list[dict] | None = None,
    skus: list[dict] | None = None,
    main_image_uris: list[str] | None = None,
    category_version: str = "v2",
) -> dict:
    if skus:
        sku_list = skus
    else:
        sku: dict = {
            "seller_sku": seller_sku,
            "price": {"amount": str(price_amount), "currency": currency or default_currency()},
            "inventory": [{"warehouse_id": warehouse_id, "quantity": int(quantity)}],
        }
        if sales_attributes:
            sku["sales_attributes"] = sales_attributes
        sku_list = [sku]

    images = [u for u in (main_image_uris or []) if u]
    if not images and main_image_uri:
        images = [main_image_uri]

    body: dict = {
        "title": title,
        "description": description,
        "category_id": str(category_id),
        "category_version": category_version,
        "main_images": [{"uri": u} for u in images],
        "product_attributes": product_attributes,
        "package_dimensions": {
            "length": str(package_length),
            "width": str(package_width),
            "height": str(package_height),
            "unit": "CENTIMETER",
        },
        "package_weight": {"value": str(package_weight), "unit": "KILOGRAM"},
        "is_cod_allowed": bool(is_cod_allowed),
        "save_mode": save_mode,
        "skus": sku_list,
    }
    if brand_id:
        body["brand_id"] = brand_id
    if delivery_option_ids:
        body["delivery_option_ids"] = delivery_option_ids
    return body


def create_product(client: TikTokShopClient, token: str, cipher: str, body: dict) -> dict:
    return client.post(f"/product/{API_VERSION}/products", token, body, shop_extra(cipher))
