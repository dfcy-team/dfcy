# -*- coding: utf-8 -*-
"""POST /product/202309/products — 新增商品（单 SKU 或多 SKU）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from product_api import (
    activate_product_listing,
    build_create_product_body,
    create_product,
    default_sales_warehouse_id,
    get_product,
    ini_bool,
    ini_get,
    load_ini,
    load_json_file,
    parse_create_skus,
    parse_delivery_option_ids,
    parse_image_path_list,
    parse_product_attributes,
    print_api_result,
    save_json,
    setup_client,
    upload_product_image,
    upload_product_images,
    first_sku,
    product_status_label,
    sku_inventory_hint,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "create", "dry_run", ini_bool(cp, "common", "dry_run", True))

    ap = argparse.ArgumentParser(description="TikTok 创建商品（单 SKU / 多 SKU）")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    args = ap.parse_args()
    if args.execute:
        args.dry_run = False

    title = ini_get(cp, "create", "title")
    category_id = ini_get(cp, "create", "category_id")
    if not title or not category_id:
        print("请在 测试设置.ini [create] 填写 title、category_id")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)

    attrs_file = ini_get(cp, "create", "attributes_json", "create_attrs.json")
    attrs_path = SCRIPT_DIR / attrs_file
    if not attrs_path.exists():
        print(f"缺少属性文件 {attrs_file}，请先运行: python run_category.py --write-template")
        return 1
    product_attributes = parse_product_attributes(load_json_file(attrs_path))

    main_uri = ini_get(cp, "create", "main_image_uri")
    image_path = ini_get(cp, "create", "image_path")
    sub_image_paths = ini_get(cp, "create", "sub_image_paths", "")
    image_uris: list[str] = []
    if main_uri:
        image_uris = [main_uri]
    elif image_path:
        p = Path(image_path)
        if not p.is_absolute():
            p = SCRIPT_DIR / p
        if p.is_file():
            if args.dry_run:
                print(f"[dry_run] 将使用主图（未上传）: {p}")
                image_uris = ["DRY_RUN_REPLACE_WITH_REAL_URI_AFTER_UPLOAD"]
            else:
                print(f"自动上传主图: {p}")
                image_uris = [upload_product_image(
                    client, token, cipher, p,
                    ini_get(cp, "create", "image_use_case", "MAIN_IMAGE"),
                )]
                print(f"主图 uri: {image_uris[0]}")
        elif not args.dry_run:
            print(f"图片不存在: {p}")
            return 1

    if not args.dry_run and sub_image_paths:
        sub_files: list[Path] = []
        for raw in parse_image_path_list(sub_image_paths):
            sp = Path(raw)
            if not sp.is_absolute():
                sp = SCRIPT_DIR / sp
            if not sp.is_file():
                print(f"副图不存在: {sp}")
                return 1
            sub_files.append(sp)
        if sub_files:
            print(f"上传副图 x{len(sub_files)}")
            image_uris.extend(upload_product_images(client, token, cipher, sub_files))
    elif args.dry_run and sub_image_paths:
        print(f"[dry_run] 副图: {sub_image_paths}")

    if not image_uris:
        if args.dry_run:
            image_uris = ["DRY_RUN_REPLACE_WITH_REAL_URI_AFTER_UPLOAD"]
            print("[dry_run] 未配置主图，请求体里使用占位 uri")
        else:
            print("请填写 main_image_uri，或把图片放到 image_path 后重试")
            return 1

    main_uri = image_uris[0]

    warehouse_id = ini_get(cp, "create", "warehouse_id")
    if not warehouse_id:
        warehouse_id = default_sales_warehouse_id(client, token, cipher)
    if not warehouse_id:
        print("无法获取销售仓库 ID，请在 ini 填写 warehouse_id")
        return 1

    description = ini_get(cp, "create", "description") or f"<p>{title}</p>"
    seller_sku = ini_get(cp, "create", "seller_sku") or f"API-{category_id[:6]}"
    amount = ini_get(cp, "create", "price", "99")
    quantity = int(ini_get(cp, "create", "quantity", "10") or "10")
    save_mode = ini_get(cp, "create", "save_mode", "AS_DRAFT") or "AS_DRAFT"
    brand_id = ini_get(cp, "create", "brand_id", "")
    delivery_ids = parse_delivery_option_ids(ini_get(cp, "create", "delivery_option_ids", ""))
    is_cod = ini_get(cp, "create", "is_cod_allowed", "1").lower() in ("1", "true", "yes")

    sales_attrs_path = ini_get(cp, "create", "sales_attributes_json", "")
    sales_attributes = None
    if sales_attrs_path:
        sp = SCRIPT_DIR / sales_attrs_path
        if sp.exists():
            sales_attributes = load_json_file(sp)

    skus_list = None
    skus_file = ini_get(cp, "create", "skus_json", "")
    if skus_file:
        skus_path = SCRIPT_DIR / skus_file
        if not skus_path.exists():
            print(f"缺少 SKU 文件 {skus_file}")
            return 1
        skus_list = parse_create_skus(load_json_file(skus_path), warehouse_id)

    body = build_create_product_body(
        title=title,
        description=description,
        category_id=category_id,
        main_image_uri=main_uri,
        main_image_uris=image_uris,
        product_attributes=product_attributes,
        seller_sku=seller_sku,
        price_amount=amount,
        warehouse_id=warehouse_id,
        quantity=quantity,
        brand_id=brand_id,
        save_mode=save_mode,
        is_cod_allowed=is_cod,
        delivery_option_ids=delivery_ids or None,
        package_length=ini_get(cp, "create", "package_length", "10"),
        package_width=ini_get(cp, "create", "package_width", "10"),
        package_height=ini_get(cp, "create", "package_height", "5"),
        package_weight=ini_get(cp, "create", "package_weight", "0.3"),
        sales_attributes=sales_attributes,
        skus=skus_list,
    )

    sku_hint = f"{len(skus_list)} 个 SKU" if skus_list else f"单 SKU ({seller_sku})"
    print(f"店铺: {cfg_path.name}")
    print(f"创建商品: {title}")
    print(f"类目={category_id} 仓库={warehouse_id}  save_mode={save_mode}  {sku_hint}")
    save_json("create_product_request.json", body)
    print("请求体已保存: logs/create_product_request.json")

    if args.dry_run:
        print("\n[dry_run] 未调用创建 API。确认后加 --execute 或 ini dry_run=0")
        print(json.dumps(body, ensure_ascii=False, indent=2)[:3000])
        return 0

    r = create_product(client, token, cipher, body)
    print_api_result(r, "创建商品")
    save_json("create_product_last.json", r)
    if r.get("code") != 0:
        return 1

    data = r.get("data") or {}
    pid = str(data.get("product_id") or data.get("id") or "")
    sku_id = ""
    sku_ids = data.get("sku_ids") or data.get("skus") or []
    if sku_ids and isinstance(sku_ids[0], dict):
        sku_id = str(sku_ids[0].get("id") or "")
    elif sku_ids:
        sku_id = str(sku_ids[0])

    summary: dict = {
        "product_id": pid,
        "sku_id": sku_id,
        "seller_sku": seller_sku,
        "title": title,
        "price": amount,
        "quantity": quantity,
        "warehouse_id": warehouse_id,
        "save_mode": save_mode,
        "status": "",
        "activate_result": None,
        "skus": [],
    }

    if pid:
        print(f"\n新商品 product_id = {pid}")
        try:
            detail = get_product(client, token, cipher, pid)
            summary["status"] = product_status_label(detail)
            detail_skus = detail.get("skus") or []
            for sku in detail_skus:
                wh, qty = sku_inventory_hint(sku)
                entry = {
                    "sku_id": str(sku.get("id") or ""),
                    "seller_sku": sku.get("seller_sku") or "",
                    "price": (sku.get("price") or {}).get("amount"),
                    "quantity": qty,
                    "warehouse_id": wh,
                }
                summary["skus"].append(entry)
                attrs = sku.get("sales_attributes") or []
                spec = " / ".join(
                    f"{a.get('name') or ''}:{a.get('value_name') or ''}".strip(":")
                    for a in attrs
                    if a.get("name") or a.get("value_name")
                )
                print(
                    f"  SKU {entry['sku_id']}  {entry['seller_sku']}  "
                    f"PHP {entry['price']} x{entry['quantity']}  {spec or '-'}"
                )
            sku = first_sku(detail)
            if sku:
                sku_id = str(sku.get("id") or sku_id)
                summary["sku_id"] = sku_id
            print(f"商品状态       = {summary['status']}")
        except Exception as e:
            print(f"（创建成功，查详情略过: {e}）")

    auto_activate = ini_bool(cp, "create", "auto_activate", False)
    if auto_activate and pid and summary["status"] not in ("ACTIVATE", "PENDING"):
        print("\n--- 自动商品上架 ---")
        try:
            ar = activate_product_listing(client, token, cipher, pid)
            summary["activate_result"] = ar
            print(f"{ar['status_before']} -> {ar['status_after']}  {ar['message']}")
        except Exception as e:
            print(f"自动上架失败: {e}")

    save_json("create_product_summary.json", summary)
    print("\n已保存: logs/create_product_summary.json")
    print("可把 product_id / sku_id 填进 ini 的 [price] [sku_listing] 等段落")
    if save_mode.upper() == "AS_DRAFT" and not auto_activate:
        print("草稿未上架 → 双击 run_product_activate.bat 上架整款商品")
    return 0


if __name__ == "__main__":
    sys.exit(main())
