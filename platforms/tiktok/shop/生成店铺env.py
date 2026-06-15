# -*- coding: utf-8 -*-
"""
一键生成店铺 env：输入店键 + 授权回调 URL → 写出 config_<店键>.env

用法:
  python 生成店铺env.py TKKJ5PH "http://dingfengchuangyu.top/callback?...code=ROW_..."
  python 生成店铺env.py TKKJ5PH --url "http://..."
  python 生成店铺env.py                          # 交互输入

可选:
  --tag TIKTOK跨境5号PH
  --mode cross_border   或 local
  --start 2026-06-01
  --end 2026-06-01
  --pick 1              一个 code 对应多店时选序号
  --no-active           不切换为当前默认店
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from shop_hub import (
    HUB_DIR,
    authorize_shop,
    create_shop_config,
    find_shop,
    load_manifest,
    parse_auth_input,
    save_manifest,
    set_active_key,
    shop_config_path,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def guess_defaults(shop_key: str) -> tuple[str, str, str]:
    """返回 (export_tag, shop_mode, label)。"""
    key = shop_key.strip().upper()
    num = ""
    m = re.search(r"(\d+)", key)
    if m:
        num = m.group(1)
    is_cross = "KJ" in key
    if is_cross and num:
        tag = f"TIKTOK跨境{num}号PH"
    elif num:
        tag = f"TIKTOK{num}号店PH"
    else:
        tag = f"TIKTOK{key}"
    mode = "cross_border" if is_cross else "local"
    label = key
    return tag, mode, label


def ensure_shop_registered(
    shop_key: str,
    *,
    export_tag: str = "",
    shop_mode: str = "",
    label: str = "",
) -> None:
    key = shop_key.strip().upper()
    g_tag, g_mode, g_label = guess_defaults(key)
    tag = export_tag or g_tag
    mode = shop_mode or g_mode
    lab = label or g_label

    if find_shop(key):
        data = load_manifest()
        for s in data.get("shops", []):
            if s["key"] == key:
                s["export_tag"] = tag
                s["shop_mode"] = mode
                if lab:
                    s["label"] = lab
                break
        save_manifest(data)
        return

    cfg_path = HUB_DIR / f"config_{key}.env"
    if cfg_path.exists():
        data = load_manifest()
        if not find_shop(key):
            data.setdefault("shops", []).append(
                {
                    "key": key,
                    "aliases": [key.lower()],
                    "config": cfg_path.name,
                    "label": lab,
                    "export_tag": tag,
                    "shop_mode": mode,
                    "region": "PH",
                    "notes": "",
                }
            )
            save_manifest(data)
        return

    create_shop_config(key, label=lab, export_tag=tag, region="PH", shop_mode=mode)


def apply_env_fields(config_path: Path, fields: dict[str, str]) -> None:
    from tts_client import update_config_file

    update_config_file(config_path, fields)


def build_parser() -> argparse.ArgumentParser:
    today = date.today().isoformat()
    ap = argparse.ArgumentParser(description="店键 + 授权 URL → 生成 config_<店键>.env")
    ap.add_argument("shop_key", nargs="?", help="如 TKKJ5PH")
    ap.add_argument("callback_url", nargs="?", help="完整回调 URL 或 ROW_ 开头 code")
    ap.add_argument("--url", "-u", default="", help="授权回调 URL")
    ap.add_argument("--tag", default="", help="TTS_EXPORT_SHOP_TAG")
    ap.add_argument("--mode", choices=("local", "cross_border"), default="", help="店铺模式")
    ap.add_argument("--start", default=today, help="TTS_ANALYTICS_START")
    ap.add_argument("--end", default=today, help="TTS_ANALYTICS_END（end_date_lt 不含当天）")
    ap.add_argument("--days", default="7", help="TTS_ANALYTICS_DAYS")
    ap.add_argument("--pick", type=int, default=None, help="多店授权时选第几个")
    ap.add_argument("--no-active", action="store_true", help="生成后不设为当前店")
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    shop_key = (args.shop_key or "").strip().upper()
    auth_input = (args.url or args.callback_url or "").strip()

    if not shop_key:
        shop_key = input("店铺键 (如 TKKJ5PH): ").strip().upper()
    if not auth_input:
        print("请粘贴授权回调 URL（含 code=ROW_...）:")
        auth_input = input().strip()

    if not shop_key:
        print("错误: 缺少店铺键")
        return 1
    if not parse_auth_input(auth_input).get("code"):
        print("错误: URL 里未找到 code")
        return 1

    tag, default_mode, label = guess_defaults(shop_key)
    export_tag = args.tag or tag
    shop_mode = args.mode or default_mode

    try:
        ensure_shop_registered(
            shop_key,
            export_tag=export_tag,
            shop_mode=shop_mode,
            label=label,
        )
        config_path = authorize_shop(shop_key, auth_input, pick_index=args.pick)
        apply_env_fields(
            config_path,
            {
                "TTS_CONFIG_LABEL": shop_key,
                "TTS_EXPORT_SHOP_TAG": export_tag,
                "TTS_SHOP_MODE": shop_mode,
                "TTS_ANALYTICS_START": args.start,
                "TTS_ANALYTICS_END": args.end,
                "TTS_ANALYTICS_DAYS": str(args.days),
            },
        )

        data = load_manifest()
        for s in data.get("shops", []):
            if s["key"] == shop_key:
                s["export_tag"] = export_tag
                s["shop_mode"] = shop_mode
                s["label"] = label
                break
        save_manifest(data)

        if not args.no_active:
            set_active_key(shop_key)
    except Exception as e:
        print(f"失败: {e}")
        return 1

    text = config_path.read_text(encoding="utf-8")
    name = ""
    sid = ""
    for line in text.splitlines():
        if line.startswith("TTS_SHOP_NAME="):
            name = line.split("=", 1)[1]
        if line.startswith("TTS_SHOP_ID="):
            sid = line.split("=", 1)[1]

    print(f"\n已生成: {config_path}")
    print(f"店键     = {shop_key}")
    print(f"店名     = {name}")
    print(f"店铺ID   = {sid}")
    print(f"导出标签 = {export_tag}")
    print(f"模式     = {shop_mode}")
    print(f"分析日期 = {args.start} ~ {args.end}")
    print(f"\n使用: --shop {shop_key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
