# -*- coding: utf-8 -*-
"""POST /product/202309/images/upload — 上传主图，返回 uri 供创建商品使用。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from product_api import (
    ini_get,
    load_ini,
    print_api_result,
    save_json,
    setup_client,
    upload_product_image,
)


def main() -> int:
    cp = load_ini()
    ap = argparse.ArgumentParser(description="TikTok 上传商品图片")
    ap.add_argument("--shop", "-s", default=ini_get(cp, "common", "shop", "TK6PH"))
    ap.add_argument("--file", "-f", default=ini_get(cp, "create", "image_path", ""))
    ap.add_argument("--use-case", default=ini_get(cp, "create", "image_use_case", "MAIN_IMAGE"))
    args = ap.parse_args()

    if not args.file:
        print("请在 测试设置.ini [create] image_path= 填写图片路径，或 --file xxx.jpg")
        return 1

    argv = ["--shop", args.shop] if args.shop else []
    client, token, cipher, cfg_path = setup_client(argv)
    image_path = Path(args.file)
    if not image_path.is_absolute():
        image_path = Path(__file__).resolve().parent / image_path

    print(f"店铺: {cfg_path.name}")
    print(f"上传: {image_path}  use_case={args.use_case}")

    uri = upload_product_image(client, token, cipher, image_path, args.use_case)
    print(f"\n主图 uri（填到 ini 的 main_image_uri）:\n{uri}")
    save_json("image_upload_last.json", {"uri": uri, "file": str(image_path)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
