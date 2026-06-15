# -*- coding: utf-8 -*-
"""
多店授权 — 粘贴 Partner 回调完整 URL 即可（code 只能用一次）

用法:
  python 授权换token.py TK2PH "http://dingfengchuangyu.top/callback?app_key=...&code=ROW_..."
  python 授权换token.py TK2PH
  python 授权换token.py              # 交互：先选店键，再粘贴 URL

新建店:
  python 新建店铺.py TK3PH --tag TIKTOK3号店PH
"""

from __future__ import annotations

import sys

from shop_hub import authorize_shop, find_shop, list_shops, parse_auth_input, print_status


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
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
        print(f"店铺键: {shop_key}")
        print("请粘贴完整授权回调 URL（含 code=ROW_...），回车:")
        auth_input = input().strip()

    if not find_shop(shop_key):
        print(f"错误: 未找到店铺 [{shop_key}]")
        print("已有:", ", ".join(s["key"] for s in list_shops()))
        print("新建: python 新建店铺.py TK3PH")
        return 1

    parsed = parse_auth_input(auth_input)
    if not parsed.get("code"):
        print("错误: URL 里未找到 code")
        return 1

    try:
        path = authorize_shop(shop_key, auth_input, pick_index=pick)
    except Exception as e:
        print(f"失败: {e}")
        return 1

    print(f"\n成功 → {path.name}")
    print("已设为当前店铺。运行分析/订单时加: --shop", shop_key.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
