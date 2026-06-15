# -*- coding: utf-8
"""商品级上架 POST /product/202309/products/activate"""

from __future__ import annotations

import argparse
import sys

from product_api import (
    activate_product_listing,
    ini_bool,
    ini_get,
    load_ini,
    parse_id_list,
    save_json,
    setup_client,
)


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="TikTok 商品上架（整款）")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--product-id", default=ini_get(cp, "product_listing", "product_id"))
    ap.add_argument(
        "--product-ids",
        default=ini_get(cp, "product_listing", "product_ids", ""),
        help="多个 ID 逗号分隔，优先于 product_id",
    )
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False

    ids = parse_id_list(args.product_ids) or parse_id_list(args.product_id)
    if not ids:
        print("请在 测试设置.ini [product_listing] 填写 product_id 或 product_ids")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")

    if args.dry_run:
        print(f"[dry_run] 将上架商品: {', '.join(ids)}")
        print("确认后: run_product_activate.bat 或加 --execute")
        return 0

    exit_code = 0
    results = []
    for pid in ids:
        print(f"\n--- 商品上架 product_id={pid} ---")
        try:
            r = activate_product_listing(client, token, cipher, pid)
        except Exception as e:
            print(f"FAIL: {e}")
            exit_code = 1
            continue
        print(f"上架前: {r['status_before']}  ->  上架后: {r['status_after']}")
        print(r["message"])
        if r.get("activate_response") and r["activate_response"].get("code") not in (0, None):
            if not r.get("skipped"):
                exit_code = 1
        results.append(r)

    save_json("product_activate_last.json", results)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
