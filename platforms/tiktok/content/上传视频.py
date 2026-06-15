# -*- coding: utf-8 -*-
"""命令行上传 TikTok 视频。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parent
if str(MODULE) not in sys.path:
    sys.path.insert(0, str(MODULE))

from oauth import build_authorize_url, token_status  # noqa: E402
from upload_client import fetch_publish_status, upload_direct, upload_draft  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="鼎峰TK内容管家 — 上传视频到 TikTok")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status", help="查看授权状态")
    p_auth = sub.add_parser("auth-url", help="打印授权链接")
    p_draft = sub.add_parser("draft", help="上传到收件箱草稿")
    p_draft.add_argument("video", help="本地 mp4 路径")
    p_direct = sub.add_parser("direct", help="直接发布（沙盒建议 SELF_ONLY）")
    p_direct.add_argument("video", help="本地 mp4 路径")
    p_direct.add_argument("--title", default="", help="标题")
    p_direct.add_argument("--privacy", default="SELF_ONLY", help="隐私级别")
    p_poll = sub.add_parser("poll", help="查询发布状态")
    p_poll.add_argument("publish_id")

    args = ap.parse_args()
    if args.cmd == "status":
        print(json.dumps(token_status(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "auth-url":
        url, state = build_authorize_url()
        print(url)
        print(f"state={state}")
        return 0
    if args.cmd == "draft":
        result = upload_draft(Path(args.video))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "direct":
        result = upload_direct(
            Path(args.video),
            title=args.title,
            privacy_level=args.privacy,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "poll":
        result = fetch_publish_status(args.publish_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
