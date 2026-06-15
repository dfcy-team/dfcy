# -*- coding: utf-8 -*-
"""Switch active shop (writes CURRENT_SHOP.txt)."""

from __future__ import annotations

import sys

from shop_hub import print_status, set_active_key


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print_status()
        key = input("\nShop key (e.g. TK2PH), q to quit: ").strip()
        if key.lower() in ("q", ""):
            return 0
        argv = [key]

    try:
        p = set_active_key(argv[0])
    except KeyError as e:
        print(e)
        return 1
    print(f"\nActive shop -> {argv[0].upper()}")
    print(f"Config: {p}")
    print("\nUse in scripts:  --shop", argv[0].upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
