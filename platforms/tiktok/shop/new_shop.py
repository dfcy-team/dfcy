# -*- coding: utf-8 -*-
"""Create config_<KEY>.env and register in shops.json."""

from __future__ import annotations

import sys

from shop_hub import create_shop_config, print_status


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) < 1:
        print("Usage: python new_shop.py TK3PH [--tag TIKTOK3号店PH] [--label name]")
        return 1
    key = argv[0]
    tag = ""
    label = ""
    i = 1
    while i < len(argv):
        if argv[i] == "--tag" and i + 1 < len(argv):
            tag = argv[i + 1]
            i += 2
        elif argv[i] == "--label" and i + 1 < len(argv):
            label = argv[i + 1]
            i += 2
        else:
            i += 1
    try:
        p = create_shop_config(key, label=label or key, export_tag=tag)
    except Exception as e:
        print(f"Failed: {e}")
        return 1
    print(f"Created: {p.name}")
    print(f"Next: python auth_shop.py {key.upper()} \"paste callback URL\"")
    print_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
