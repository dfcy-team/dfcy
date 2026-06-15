# -*- coding: utf-8 -*-
"""切换当前默认店铺（写入 CURRENT_SHOP.txt）"""

from __future__ import annotations

import sys

from shop_hub import print_status, read_active_key, set_active_key


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print_status()
        key = input("\n输入店键切换 (如 TK2PH)，q 退出: ").strip()
        if key.lower() in ("q", ""):
            return 0
        argv = [key]

    try:
        p = set_active_key(argv[0])
    except KeyError as e:
        print(e)
        return 1
    print(f"已切换当前店 → {argv[0].upper()}")
    print(f"配置文件: {p}")
    print("\n各脚本使用方式:")
    print("  --shop", argv[0].upper())
    print("  或设置环境变量 TTS_SHOP=" + argv[0].upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
