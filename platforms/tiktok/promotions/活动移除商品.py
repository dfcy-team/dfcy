# -*- coding: utf-8 -*-
"""从促销活动移除商品/SKU — seller.promotion.write"""

from __future__ import annotations

import argparse
import sys

from promotion_api import (
    ini_bool,
    ini_get,
    load_ini,
    print_api_result,
    remove_activity_products,
    save_json,
    setup_client,
)
from tts_client import is_ok


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="促销活动移除商品")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TKKJ3PH"))
    ap.add_argument("--id", default=ini_get(cp, "活动移除商品", "activity_id"))
    ap.add_argument("--product-id", default=ini_get(cp, "活动移除商品", "product_id"))
    ap.add_argument("--sku-id", default=ini_get(cp, "活动移除商品", "sku_id"))
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if args.execute:
        args.dry_run = False

    if not args.id:
        print("请填写 activity_id")
        return 1
    if not args.product_id and not args.sku_id:
        print("请填写 product_id 或 sku_id 至少一项")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")
    print(f"移除 activity_id={args.id}")

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute")
        return 0

    pids = [args.product_id] if args.product_id else None
    sids = [args.sku_id] if args.sku_id else None
    r = remove_activity_products(
        client, token, cipher, args.id, product_ids=pids, sku_ids=sids
    )
    print_api_result(r, "活动移除商品")
    save_json("remove_activity_products_last.json", r, args.shop)
    return 0 if is_ok(r) else 1


if __name__ == "__main__":
    sys.exit(main())
