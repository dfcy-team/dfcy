# -*- coding: utf-8 -*-
"""从 TikTok API 同步 PH 类目到 categories_ph.json，并更新桌面 Excel 下拉。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook

from category_helper import (
    DEFAULT_EXCEL,
    apply_category_sheet,
    build_category_catalog,
    default_category_label,
    save_category_catalog,
)
from product_api import get_categories, ini_get, load_ini, setup_client

SCRIPT_DIR = Path(__file__).resolve().parent


def ensure_excel_exists() -> None:
    if DEFAULT_EXCEL.exists():
        return
    from 生成Excel模板 import main as gen_main

    gen_main()


def main() -> int:
    cp = load_ini()
    ap = argparse.ArgumentParser(description="同步 TikTok 类目到 Excel 下拉")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--excel", default=str(DEFAULT_EXCEL))
    ap.add_argument("--locale", default="zh-CN", help="类目语言，默认 zh-CN 中文")
    args = ap.parse_args()

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    print(f"店铺: {cfg_path.name}")

    print("正在拉取类目（中文）...")
    categories = get_categories(client, token, cipher, locale=args.locale)
    rows = build_category_catalog(categories)
    save_category_catalog(rows, shop=args.shop, region="PH", locale=args.locale)
    print(f"已保存 {len(rows)} 个叶子类目 -> {SCRIPT_DIR / 'categories_ph.json'}")

    ensure_excel_exists()
    excel_path = Path(args.excel)
    wb = load_workbook(excel_path)
    apply_category_sheet(wb, rows)
    try:
        wb.save(excel_path)
        print(f"已更新 Excel 下拉: {excel_path}")
    except PermissionError:
        alt = excel_path.with_name(excel_path.stem + "_含类目下拉" + excel_path.suffix)
        wb.save(alt)
        print(f"原 Excel 可能正打开，已另存为: {alt}")
        print("请关闭原文件后，用新文件或再运行一次同步。")
    print(f"示例: {default_category_label('810376')}")
    print("\n在「商品」表的「类目」列点下拉选择即可，无需手填 ID。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
