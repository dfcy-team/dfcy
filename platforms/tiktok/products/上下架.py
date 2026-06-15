# -*- coding: utf-8 -*-
"""POST activate / deactivate — 需 seller.product.write"""

from __future__ import annotations

import argparse
import sys

from product_api import (
    activate_products,
    deactivate_products,
    ini_bool,
    ini_get,
    load_ini,
    print_api_result,
    save_json,
    setup_client,
)


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="TikTok 商品上架 / 下架")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--product-id", default=ini_get(cp, "listing", "product_id"))
    ap.add_argument(
        "--action",
        choices=("activate", "deactivate"),
        default=ini_get(cp, "listing", "action", "deactivate") or "deactivate",
    )
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False

    if not args.product_id:
        print("请填写 product_id（测试设置.ini [listing] 或 --product-id）")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")
    print(f"{args.action}: product_id={args.product_id}")

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute")
        return 0

    ids = [args.product_id]
    if args.action == "activate":
        r = activate_products(client, token, cipher, ids)
        label = "上架"
    else:
        r = deactivate_products(client, token, cipher, ids)
        label = "下架"

    print_api_result(r, label)
    save_json(f"listing_{args.action}_last.json", r)
    return 0 if r.get("code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
