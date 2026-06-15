# -*- coding: utf-8
"""SKU 级上架：先商品 activate（如需），再恢复 SKU 库存。"""

from __future__ import annotations

import argparse
import sys

from product_api import (
    activate_sku_listing,
    get_product,
    ini_bool,
    ini_get,
    load_ini,
    product_status_label,
    save_json,
    setup_client,
    sku_inventory_for,
    sku_status_label,
    find_sku,
)


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="TikTok SKU 上架")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--product-id", default=ini_get(cp, "sku_listing", "product_id"))
    ap.add_argument("--sku-id", default=ini_get(cp, "sku_listing", "sku_id"))
    ap.add_argument("--warehouse-id", default=ini_get(cp, "sku_listing", "warehouse_id"))
    qty_raw = ini_get(cp, "sku_listing", "quantity", "")
    ap.add_argument("--quantity", type=int, default=int(qty_raw) if qty_raw else -1)
    ap.add_argument(
        "--activate-product",
        action="store_true",
        default=ini_bool(cp, "sku_listing", "activate_product", True),
    )
    ap.add_argument("--no-activate-product", action="store_true")
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False
    if args.no_activate_product:
        args.activate_product = False

    if not args.product_id or not args.sku_id:
        print("请在 测试设置.ini [sku_listing] 填写 product_id / sku_id / quantity")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)

    detail = get_product(client, token, cipher, args.product_id)
    sku = find_sku(detail, args.sku_id)
    if not sku:
        print(f"未找到 SKU {args.sku_id}")
        return 1

    wh, cur_qty = sku_inventory_for(detail, args.sku_id)
    warehouse_id = args.warehouse_id or wh
    target_qty = cur_qty if args.quantity < 0 else args.quantity

    print(f"店铺: {cfg_path.name}")
    print(f"商品: {args.product_id}  status={product_status_label(detail)}")
    print(f"SKU:  {args.sku_id}  status={sku_status_label(sku)}  qty={cur_qty}  warehouse={warehouse_id}")

    if args.dry_run:
        print(f"[dry_run] 目标库存={target_qty}  先商品上架={args.activate_product}")
        print("确认后: run_sku_activate.bat 或加 --execute")
        return 0

    if target_qty <= 0:
        print("quantity 必须 > 0")
        return 1

    try:
        r = activate_sku_listing(
            client,
            token,
            cipher,
            args.product_id,
            args.sku_id,
            warehouse_id=warehouse_id,
            quantity=target_qty,
            activate_product=args.activate_product,
        )
    except Exception as e:
        print(f"FAIL: {e}")
        return 1

    print(f"商品状态: {r['product_status_before']} -> {r['product_status_after']}")
    print(f"SKU状态:  {r['sku_status_before']} -> {r['sku_status_after']}")
    print(f"库存:     {r['quantity_before']} -> {r['quantity_after']}")
    print(r["message"])
    save_json("sku_activate_last.json", r)
    ok = True
    for key in ("product_activate", "inventory_update"):
        resp = r.get(key)
        if resp and resp.get("code") not in (0, None):
            ok = False
            print(f"API 失败: {resp.get('message')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
