# -*- coding: utf-8
"""Web 层封装：TikTok Marketing API（广告授权）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MARKETING_ROOT = Path(__file__).resolve().parents[2] / "platforms" / "tiktok" / "marketing"


def _load_marketing_modules():
    """隔离加载 marketing/config + oauth，避免与 content/config 模块名冲突。"""
    cfg_spec = importlib.util.spec_from_file_location(
        "tiktok_marketing_config", MARKETING_ROOT / "config.py"
    )
    cfg = importlib.util.module_from_spec(cfg_spec)
    assert cfg_spec.loader is not None
    cfg_spec.loader.exec_module(cfg)

    oauth_spec = importlib.util.spec_from_file_location(
        "tiktok_marketing_oauth", MARKETING_ROOT / "oauth.py"
    )
    oauth_mod = importlib.util.module_from_spec(oauth_spec)
    assert oauth_spec.loader is not None
    prev_config = sys.modules.get("config")
    sys.modules["config"] = cfg
    try:
        oauth_spec.loader.exec_module(oauth_mod)
    finally:
        if prev_config is not None:
            sys.modules["config"] = prev_config
        else:
            sys.modules.pop("config", None)
    return cfg, oauth_mod


_cfg, marketing_oauth = _load_marketing_modules()

APP_ID = _cfg.APP_ID
REDIRECT_URI = _cfg.REDIRECT_URI
save_app_secret = _cfg.save_app_secret

build_authorize_url = marketing_oauth.build_authorize_url
exchange_auth_code = marketing_oauth.exchange_auth_code
extract_auth_code_from_query = marketing_oauth.extract_auth_code_from_query
verify_credentials = marketing_oauth.verify_credentials
is_marketing_callback = marketing_oauth.is_marketing_callback
token_status = marketing_oauth.token_status
fetch_advertiser_list = marketing_oauth.fetch_advertiser_list
load_advertisers = marketing_oauth.load_advertisers
save_shop_label = marketing_oauth.save_shop_label
list_shop_bindings = marketing_oauth.list_shop_bindings
binding_for_shop = marketing_oauth.binding_for_shop
set_active_shop_label = marketing_oauth.set_active_shop_label
refresh_shop_advertisers = marketing_oauth.refresh_shop_advertisers
resolve_default_advertiser_id = marketing_oauth.resolve_default_advertiser_id
resolve_advertiser_name = marketing_oauth.resolve_advertiser_name
refresh_all_shop_advertisers = marketing_oauth.refresh_all_shop_advertisers
delete_shop_authorization = marketing_oauth.delete_shop_authorization
load_custom_ad_shops = marketing_oauth.load_custom_ad_shops
add_custom_ad_shop = marketing_oauth.add_custom_ad_shop
remove_custom_ad_shop = marketing_oauth.remove_custom_ad_shop
