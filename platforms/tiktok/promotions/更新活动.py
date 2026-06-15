# -*- coding: utf-8 -*-
"""更新促销活动标题/时间 — seller.promotion.write"""

from __future__ import annotations

import argparse
import sys

from promotion_api import (
    get_activity,
    ini_bool,
    ini_get,
    load_ini,
    parse_local_datetime,
    print_api_result,
    save_json,
    setup_client,
    update_activity,
)
from tts_client import is_ok


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="更新 TikTok 促销活动")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TKKJ3PH"))
    ap.add_argument("--id", default=ini_get(cp, "更新活动", "activity_id"))
    ap.add_argument("--title", default=ini_get(cp, "更新活动", "title"))
    ap.add_argument("--begin", default=ini_get(cp, "更新活动", "begin_time"))
    ap.add_argument("--end", default=ini_get(cp, "更新活动", "end_time"))
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if args.execute:
        args.dry_run = False

    if not args.id:
        print("请填写 activity_id（--id 或 促销配置.ini [更新活动]）")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)

    title = args.title
    begin_s = args.begin
    end_s = args.end
    act_type = ""
    level = ""

    if not title or not begin_s or not end_s:
        r0 = get_activity(client, token, cipher, args.id)
        if not is_ok(r0):
            print_api_result(r0, "读取活动")
            return 1
        act = (r0.get("data") or {}).get("activity") or r0.get("data") or {}
        title = title or act.get("title", "")
        begin_s = begin_s or str(act.get("begin_time", ""))
        end_s = end_s or str(act.get("end_time", ""))
        act_type = act.get("activity_type", "")
        level = act.get("product_level", "")
        if str(begin_s).isdigit():
            from datetime import datetime
            from promotion_api import local_tz

            begin_s = datetime.fromtimestamp(int(begin_s), tz=local_tz()).strftime("%Y-%m-%d %H:%M")
        if str(end_s).isdigit():
            from datetime import datetime
            from promotion_api import local_tz

            end_s = datetime.fromtimestamp(int(end_s), tz=local_tz()).strftime("%Y-%m-%d %H:%M")

    t0 = parse_local_datetime(begin_s) if begin_s and not str(begin_s).isdigit() else int(begin_s)
    t1 = parse_local_datetime(end_s) if end_s and not str(end_s).isdigit() else int(end_s)

    print(f"店铺: {cfg_path.name}")
    print(f"更新 activity_id={args.id}")

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute")
        return 0

    r = update_activity(
        client,
        token,
        cipher,
        args.id,
        title=title,
        begin_time=t0,
        end_time=t1,
        activity_type=act_type,
        product_level=level,
    )
    print_api_result(r, "更新活动")
    save_json("update_activity_last.json", r, args.shop)
    return 0 if is_ok(r) else 1


if __name__ == "__main__":
    sys.exit(main())
