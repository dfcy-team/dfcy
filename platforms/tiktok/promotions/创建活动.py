# -*- coding: utf-8 -*-
"""创建促销活动（不含商品，创建后用 活动加商品.py）— seller.promotion.write"""

from __future__ import annotations

import argparse
import sys

from promotion_api import (
    create_activity,
    ini_bool,
    ini_get,
    load_ini,
    parse_local_datetime,
    print_api_result,
    save_json,
    setup_client,
)
from tts_client import is_ok


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="创建 TikTok 促销活动")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TKKJ3PH"))
    ap.add_argument("--title", default=ini_get(cp, "创建活动", "title"))
    ap.add_argument("--type", default=ini_get(cp, "创建活动", "activity_type", "FIXED_PRICE"))
    ap.add_argument("--level", default=ini_get(cp, "创建活动", "product_level", "VARIATION"))
    ap.add_argument("--begin", default=ini_get(cp, "创建活动", "begin_time"))
    ap.add_argument("--end", default=ini_get(cp, "创建活动", "end_time"))
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if args.execute:
        args.dry_run = False

    if not args.title or not args.begin or not args.end:
        print("请填写 促销配置.ini [创建活动]: title, begin_time, end_time")
        return 1

    t0 = parse_local_datetime(args.begin)
    t1 = parse_local_datetime(args.end)
    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")
    print(f"创建: {args.title} | {args.type} | {args.level}")
    print(f"时间(当地): {args.begin} ~ {args.end}  (unix {t0} ~ {t1})")

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute")
        return 0

    r = create_activity(
        client,
        token,
        cipher,
        title=args.title,
        activity_type=args.type.upper(),
        begin_time=t0,
        end_time=t1,
        product_level=args.level.upper(),
    )
    print_api_result(r, "创建活动")
    save_json("create_activity_last.json", r, args.shop)
    if is_ok(r):
        aid = (r.get("data") or {}).get("activity_id", "")
        if aid:
            print(f"\n下一步: 在 促销配置.ini [活动加商品] 填 activity_id={aid}，再运行 活动加商品.bat --execute")
    return 0 if is_ok(r) else 1


if __name__ == "__main__":
    sys.exit(main())
