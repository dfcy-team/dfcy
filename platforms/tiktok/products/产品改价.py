# -*- coding: utf-8 -*-
"""POST /product/202309/products/{id}/prices/update — 需 seller.product.write"""

from __future__ import annotations

import argparse
import sys

from product_api import (
    ini_bool,
    ini_get,
    load_ini,
    print_api_result,
    save_json,
    setup_client,
    update_price,
)


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="TikTok 商品改价")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--product-id", default=ini_get(cp, "price", "product_id"))
    ap.add_argument("--sku-id", default=ini_get(cp, "price", "sku_id"))
    ap.add_argument("--amount", default=ini_get(cp, "price", "amount"))
    ap.add_argument("--currency", default="")
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true", help="真实调用 API（覆盖 dry_run）")
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False

    if not args.product_id or not args.sku_id or not args.amount:
        print("请在 测试设置.ini [price] 或命令行填写 product_id / sku_id / amount")
        print("示例: python 产品改价.py --product-id xxx --sku-id yyy --amount 199.00 --execute")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")
    print(f"改价: product={args.product_id} sku={args.sku_id} -> {args.amount}")

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute 或 ini 里 dry_run=0")
        return 0

    r = update_price(
        client,
        token,
        cipher,
        args.product_id,
        args.sku_id,
        args.amount,
        args.currency or None,
    )
    print_api_result(r, "改价")
    save_json("price_update_last.json", r)
    return 0 if r.get("code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
