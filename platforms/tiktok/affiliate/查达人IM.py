# -*- coding: utf-8 -*-
"""
TikTok Shop 联盟达人：用户名 -> IM 链接

用法:
  python 查达人IM.py jho_official.acc
  python 查达人IM.py --region ph jho_official.acc
  python 查达人IM.py --region th user1 user2

影刀:
  from creator_lookup import get_im_links, get_creator_ids
  im_links = get_im_links(["jho_official.acc"], region="ph")
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from creator_lookup import (
    DEFAULT_REGION,
    DEFAULT_SHOP_KEY,
    get_creator_ids,
    get_im_links,
    prepare_network,
    resolve_creators,
    resolve_shop_key,
)

# 影刀 / 外部 import 本模块时也能直接用
resolve_im_links = resolve_creators

__all__ = [
    "get_im_links",
    "get_creator_ids",
    "resolve_im_links",
    "resolve_creators",
    "prepare_network",
    "resolve_shop_key",
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TikTok 联盟达人用户名 -> IM 链接")
    parser.add_argument("usernames", nargs="*", help="用户名，可多个")
    parser.add_argument(
        "--region",
        "-r",
        default=DEFAULT_REGION,
        help=f"跨境国家 PH/TH/MY，默认 {DEFAULT_REGION}",
    )
    parser.add_argument(
        "--shop",
        default=None,
        help=f"完整店键（优先于 --region），如 {DEFAULT_SHOP_KEY}",
    )
    args = parser.parse_args(argv)

    if not args.usernames:
        args.usernames = ["jho_official.acc"]

    proxy = prepare_network()
    shop = resolve_shop_key(args.shop or args.region)
    print(f"[网络] 代理: {proxy or '直连'}")
    print(f"[店铺] {shop} (region={args.region.upper()})")

    results = resolve_creators(args.usernames, region=args.region, shop_key=args.shop)
    for r in results:
        print(
            f"{r['username']}\t{r['region']}\t{r['creator_id'] or '-'}\t{r['im_link'] or '-'}\t"
            f"{'OK' if r['ok'] else 'FAIL'}\t{r['msg']}"
        )
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
