# -*- coding: utf-8 -*-
"""Shopee 授权入口 — 开发者 B 在 platforms/shopee/shop 实现后接入。"""
from __future__ import annotations

PLATFORM = "shopee"


def list_auth_links() -> list[dict]:
    """返回 Shopee 店铺授权链接列表（待实现）。"""
    return []


def build_authorize_url(shop_key: str) -> str:
    raise NotImplementedError("Shopee 授权尚未接入，请在 platforms/shopee/shop 实现")


def setup_and_authorize(
    shop_key: str,
    callback_url: str,
    *,
    pick_index: int | None = None,
    create_if_missing: bool = True,
) -> dict:
    raise NotImplementedError("Shopee 授权尚未接入，请在 platforms/shopee/shop 实现")
