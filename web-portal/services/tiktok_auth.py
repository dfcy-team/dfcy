# -*- coding: utf-8 -*-
"""TikTok 授权入口 — 调用 platforms/tiktok（当前薄包装 正式环境/shop_hub）。"""
from __future__ import annotations

import sys
from pathlib import Path

ERP_ROOT = Path(__file__).resolve().parents[2]
if str(ERP_ROOT / "web-portal") not in sys.path:
    sys.path.insert(0, str(ERP_ROOT / "web-portal"))

from services import shops  # noqa: E402

PLATFORM = "tiktok"


def list_auth_links() -> list[dict]:
    return [x for x in shops.list_tiktok_auth_links() if x.get("key")]


def build_authorize_url(shop_key: str) -> str:
    return shops.build_authorize_url(shop_key)


def setup_and_authorize(
    shop_key: str,
    callback_url: str,
    *,
    pick_index: int | None = None,
    create_if_missing: bool = True,
) -> dict:
    return shops.setup_and_authorize(
        shop_key,
        callback_url,
        pick_index=pick_index,
        create_if_missing=create_if_missing,
    )
