# -*- coding: utf-8 -*-
"""列出店铺商品（测试 seller.product.basic / search）。"""

from __future__ import annotations

import argparse
import sys

from product_api import (
    get_product,
    ini_get,
    load_ini,
    print_product_row,
    save_json,
    search_products,
    setup_client,
)


def main() -> int:
    cp = load_ini()
    ap = argparse.ArgumentParser(description="TikTok 商品列表 / 详情")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--status", default=ini_get(cp, "query", "status", ""))
    ap.add_argument("--page-size", type=int, default=int(ini_get(cp, "query", "page_size", "10") or "10"))
    ap.add_argument("--max-pages", type=int, default=int(ini_get(cp, "query", "max_pages", "2") or "2"))
    ap.add_argument("--detail", metavar="PRODUCT_ID", help="拉取单个商品详情")
    args = ap.parse_args()

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺配置: {cfg_path.name}")

    if args.detail:
        p = get_product(client, token, cipher, args.detail)
        print_product_row(p)
        save_json(f"product_{args.detail}.json", p)
        return 0

    products = search_products(
        client,
        token,
        cipher,
        status=args.status,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    print(f"共 {len(products)} 条（status={args.status or '全部'}）\n")
    for i, p in enumerate(products, 1):
        print_product_row(p, i)
        print()
    save_json("products_search_last.json", products)
    print(f"已保存: logs/products_search_last.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
