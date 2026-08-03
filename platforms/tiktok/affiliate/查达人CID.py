# -*- coding: utf-8 -*-
"""
TikTok Shop 联盟达人：用户名 -> creator_id (cid)

用法:
  python 查达人CID.py jho_official.acc
  python 查达人CID.py --region ph jho_official.acc another.user
  python 查达人CID.py --region th user1 user2
  python 查达人CID.py --ids-only --region my user1 user2

影刀:
  from creator_lookup import get_creator_ids
  cids = get_creator_ids(["jho_official.acc"], region="ph")
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from creator_lookup import (
    DEFAULT_REGION,
    DEFAULT_SHOP_KEY,
    get_creator_ids,
    prepare_network,
    resolve_creators,
    resolve_shop_key,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="TikTok 联盟达人用户名 -> creator_id")
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
    parser.add_argument(
        "--ids-only",
        action="store_true",
        help="只输出 creator_id，每行一个（与输入顺序一致）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON",
    )
    args = parser.parse_args(argv)

    if not args.usernames:
        args.usernames = ["jho_official.acc"]

    proxy = prepare_network()
    shop = resolve_shop_key(args.shop or args.region)
    results = resolve_creators(args.usernames, region=args.region, shop_key=args.shop)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.ids_only:
        for r in results:
            print(r["creator_id"] if r["ok"] else "")
    else:
        if not args.ids_only:
            print(f"[网络] 代理: {proxy or '直连'}")
            print(f"[店铺] {shop} (region={args.region.upper()})")
            print("说明: user_id=TikTok账号ID；affiliate_cid=联盟前台详情页cid（Open API 可能无）")
        for r in results:
            print(
                f"{r['username']}\t{r['region']}\t"
                f"user_id={r['user_id'] or '-'}\t"
                f"affiliate_cid={r['affiliate_cid'] or '-'}\t"
                f"{'OK' if r['ok'] else 'FAIL'}\t{r['msg']}"
            )

    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
