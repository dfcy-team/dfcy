# -*- coding: utf-8 -*-
"""停用促销活动 — seller.promotion.write"""

from __future__ import annotations

import argparse
import sys

from promotion_api import (
    deactivate_activity,
    ini_bool,
    ini_get,
    load_ini,
    print_api_result,
    save_json,
    setup_client,
)
from tts_client import is_ok


def main() -> int:
    cp = load_ini()
    dry_default = ini_bool(cp, "common", "dry_run", True)

    ap = argparse.ArgumentParser(description="停用 TikTok 促销活动")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TKKJ3PH"))
    ap.add_argument("--id", default=ini_get(cp, "停用活动", "activity_id"))
    ap.add_argument("--dry-run", action="store_true", default=dry_default)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    if args.execute:
        args.dry_run = False

    if not args.id:
        print("请填写 activity_id（--id 或 促销配置.ini [停用活动]）")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")
    print(f"停用 activity_id={args.id}")

    if args.dry_run:
        print("[dry_run] 未调用 API。确认后加 --execute")
        return 0

    r = deactivate_activity(client, token, cipher, args.id)
    print_api_result(r, "停用活动")
    save_json("deactivate_activity_last.json", r, args.shop)
    return 0 if is_ok(r) else 1


if __name__ == "__main__":
    sys.exit(main())
