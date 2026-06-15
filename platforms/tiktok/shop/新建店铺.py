# -*- coding: utf-8 -*-
"""新建一家店的 config_<键>.env 并登记到 shops.json"""

from __future__ import annotations

import sys

from shop_hub import create_shop_config, print_status


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) < 1:
        print("用法: python 新建店铺.py TK3PH [--tag TIKTOK3号店PH] [--label 说明]")
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
        print(f"失败: {e}")
        return 1
    print(f"已创建: {p.name}")
    print(f"下一步: python 授权换token.py {key.upper()} \"粘贴回调URL\"")
    print_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
