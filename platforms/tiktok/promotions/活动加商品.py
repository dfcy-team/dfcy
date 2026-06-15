# -*- coding: utf-8 -*-
"""往促销活动加商品/SKU — seller.promotion.write"""

from __future__ import annotations

import argparse
import sys

from promotion_api import (
    build_product_entry,
    get_activity,
    ini_bool,
    ini_get,
    load_ini,
    print_api_result,
    save_json,
    setup_client,
    update_activity_products,
)
from tts_client import is_ok


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="促销活动添加商品")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TKKJ3PH"))
    ap.add_argument("--id", default=ini_get(cp, "活动加商品", "activity_id"))
    ap.add_argument("--product-id", default=ini_get(cp, "活动加商品", "product_id"))
    ap.add_argument("--sku-id", default=ini_get(cp, "活动加商品", "sku_id"))
    ap.add_argument("--price", default=ini_get(cp, "活动加商品", "activity_price_amount"))
    ap.add_argument("--discount", default=ini_get(cp, "活动加商品", "discount"))
    ap.add_argument("--qty-limit", type=int, default=int(ini_get(cp, "活动加商品", "quantity_limit", "-1") or "-1"))
    ap.add_argument(
        "--qty-per-user",
        type=int,
        default=int(ini_get(cp, "活动加商品", "quantity_per_user", "-1") or "-1"),
    )
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if args.execute:
        args.dry_run = False

    if not args.id or not args.product_id:
        print("请填写 activity_id、product_id（VARIATION 级别还需 sku_id）")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)

    r0 = get_activity(client, token, cipher, args.id)
    if not is_ok(r0):
        print_api_result(r0, "读取活动")
        return 1
    act = (r0.get("data") or {}).get("activity") or r0.get("data") or {}
    at = str(act.get("activity_type", "FIXED_PRICE")).upper()
    pl = str(act.get("product_level", "VARIATION")).upper()

    if pl == "VARIATION" and not args.sku_id:
        print("product_level=VARIATION 时必须填写 sku_id")
        return 1
    if at == "DIRECT_DISCOUNT" and not args.discount:
        print("DIRECT_DISCOUNT 需填写 discount（百分比）")
        return 1
    if at in ("FIXED_PRICE", "FLASHSALE") and not args.price:
        print("FIXED_PRICE/FLASHSALE 需填写 activity_price_amount（活动价）")
        return 1

    product = build_product_entry(
        product_id=args.product_id,
        activity_type=at,
        product_level=pl,
        discount=args.discount,
        activity_price_amount=args.price,
        quantity_limit=args.qty_limit,
        quantity_per_user=args.qty_per_user,
        sku_id=args.sku_id,
        sku_price=args.price,
        sku_discount=args.discount,
        sku_qty_limit=args.qty_limit,
        sku_qty_per_user=args.qty_per_user,
    )

    print(f"店铺: {cfg_path.name}")
    print(f"活动 {args.id} ({at}/{pl}) 添加商品:")
    import json

    print(json.dumps(product, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute")
        return 0

    r = update_activity_products(client, token, cipher, args.id, [product])
    print_api_result(r, "活动加商品")
    save_json("add_activity_products_last.json", r, args.shop)
    return 0 if is_ok(r) else 1


if __name__ == "__main__":
    sys.exit(main())
