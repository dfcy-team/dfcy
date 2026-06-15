# -*- coding: utf-8 -*-
"""Exchange OAuth callback URL for shop tokens."""

from __future__ import annotations

import sys

from shop_hub import authorize_shop, find_shop, list_shops, parse_auth_input, print_status


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: python auth_shop.py TK2PH \"http://...callback?code=ROW_...\"")
        print_status()
        return 0

    if argv[0] in ("list", "ls"):
        print_status()
        return 0

    shop_key = argv[0]
    auth_input = ""
    pick = None

    if len(argv) >= 2:
        if argv[1] == "--pick" and len(argv) >= 3:
            pick = int(argv[2])
            auth_input = argv[3] if len(argv) >= 4 else ""
        else:
            auth_input = " ".join(argv[1:])

    if not auth_input:
        print(f"Shop key: {shop_key}")
        print("Paste full callback URL (with code=ROW_...):")
        auth_input = input().strip()

    if not find_shop(shop_key):
        print(f"Unknown shop: {shop_key}")
        print("Existing:", ", ".join(s["key"] for s in list_shops()))
        print("Create first: python new_shop.py TK3PH")
        return 1

    if not parse_auth_input(auth_input).get("code"):
        print("Error: no code in URL")
        return 1

    try:
        path = authorize_shop(shop_key, auth_input, pick_index=pick)
    except Exception as e:
        print(f"Failed: {e}")
        return 1

    print(f"\nOK -> {path.name}")
    print("Set as active shop. Use: --shop", shop_key.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
