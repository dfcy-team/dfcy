# -*- coding: utf-8 -*-
"""POST /product/202309/products/{id}/inventory/update — 需 seller.product.write"""

from __future__ import annotations

import argparse
import sys

from product_api import (
    get_product,
    ini_bool,
    ini_get,
    load_ini,
    print_api_result,
    save_json,
    setup_client,
    sku_inventory_hint,
    first_sku,
    update_inventory,
)


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="TikTok 商品改库存")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--product-id", default=ini_get(cp, "inventory", "product_id"))
    ap.add_argument("--sku-id", default=ini_get(cp, "inventory", "sku_id"))
    ap.add_argument("--warehouse-id", default=ini_get(cp, "inventory", "warehouse_id"))
    ap.add_argument("--quantity", type=int, default=int(ini_get(cp, "inventory", "quantity", "0") or "0"))
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False

    if not args.product_id or not args.sku_id:
        print("请填写 product_id / sku_id；warehouse_id 可留空则从商品详情自动取")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)

    warehouse_id = args.warehouse_id
    if not warehouse_id:
        detail = get_product(client, token, cipher, args.product_id)
        sku = first_sku(detail)
        if not sku:
            print("商品无 SKU，无法推断 warehouse_id")
            return 1
        if not args.sku_id:
            args.sku_id = str(sku.get("id") or "")
        warehouse_id, _ = sku_inventory_hint(sku)
        if not warehouse_id:
            print("详情里无 warehouse_id，请手动填写 --warehouse-id")
            return 1

    print(f"店铺: {cfg_path.name}")
    print(
        f"改库存: product={args.product_id} sku={args.sku_id} "
        f"warehouse={warehouse_id} qty={args.quantity}"
    )

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute")
        return 0

    r = update_inventory(
        client,
        token,
        cipher,
        args.product_id,
        args.sku_id,
        warehouse_id,
        args.quantity,
    )
    print_api_result(r, "改库存")
    save_json("inventory_update_last.json", r)
    return 0 if r.get("code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
