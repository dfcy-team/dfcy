# -*- coding: utf-8 -*-
"""
TikTok Shop 促销查询 — seller.promotion.info

  python 查促销.py --shop TKKJ3PH
  python 查促销.py --shop TKKJ3PH --save --detail 10
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from promotion_api import (
    activity_id_of,
    coupon_id_of,
    fetch_all_activities,
    fetch_all_coupons,
    get_activity,
    get_coupon,
    ini_bool,
    ini_get,
    load_ini,
    save_json,
    setup_client,
    is_ok,
)
from tts_client import cfg  # noqa: E402


def main() -> int:
    cp = load_ini()
    ap = argparse.ArgumentParser(description="促销查询（活动+优惠券）")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TKKJ3PH"))
    ap.add_argument("--save", action="store_true", default=ini_bool(cp, "查询", "保存完整json", True))
    ap.add_argument("--detail", type=int, default=int(ini_get(cp, "查询", "详情条数", "5") or "5"))
    args = ap.parse_args()

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    tag = cfg("TTS_EXPORT_SHOP_TAG", args.shop)
    print("=" * 60)
    print(f"促销查询 | {tag} | {cfg_path.name}")
    print("权限: seller.promotion.info")
    print("=" * 60)

    failed = 0
    out = {"shop": args.shop, "export_tag": tag, "time": datetime.now().isoformat(timespec="seconds")}

    print("\n[促销活动]")
    activities = fetch_all_activities(client, token, cipher)
    out["activities"] = activities
    print(f"合计 {len(activities)} 个")
    for j, act in enumerate(activities[:15], 1):
        print(
            f"  {j}. id={activity_id_of(act)}  type={act.get('activity_type')}  "
            f"status={act.get('status')}  title={str(act.get('title', ''))[:50]}"
        )

    details = []
    for act in activities[: max(0, args.detail)]:
        aid = activity_id_of(act)
        if not aid:
            continue
        r = get_activity(client, token, cipher, aid)
        if is_ok(r):
            d = (r.get("data") or {}).get("activity") or r.get("data") or {}
            details.append(d)
            n_prod = len(d.get("products") or [])
            print(f"  [详情] {aid} 商品数={n_prod}")
        else:
            print(f"  [详情失败] {aid} code={r.get('code')}")
            failed += 1
    out["activity_details"] = details

    print("\n[优惠券]")
    coupons = fetch_all_coupons(client, token, cipher)
    out["coupons"] = coupons
    print(f"合计 {len(coupons)} 张")
    for j, c in enumerate(coupons[:10], 1):
        print(
            f"  {j}. id={coupon_id_of(c)}  status={c.get('status')}  "
            f"title={str(c.get('title') or c.get('coupon_name', ''))[:50]}"
        )

    if args.save:
        save_json(f"promotion_query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", out, args.shop)

    print("\n完成" + (f"（详情失败 {failed}）" if failed else ""))
    return 0 if activities or coupons else 1


if __name__ == "__main__":
    sys.exit(main())
