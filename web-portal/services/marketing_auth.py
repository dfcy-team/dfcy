# -*- coding: utf-8
"""Web 层封装：TikTok Marketing API（广告授权）。"""
from __future__ import annotations

import sys
from pathlib import Path

MARKETING_ROOT = Path(__file__).resolve().parents[2] / "platforms" / "tiktok" / "marketing"
if str(MARKETING_ROOT) not in sys.path:
    sys.path.insert(0, str(MARKETING_ROOT))

import oauth as marketing_oauth  # noqa: E402
from config import APP_ID, REDIRECT_URI, save_app_secret  # noqa: E402

build_authorize_url = marketing_oauth.build_authorize_url
exchange_auth_code = marketing_oauth.exchange_auth_code
extract_auth_code_from_query = marketing_oauth.extract_auth_code_from_query
verify_credentials = marketing_oauth.verify_credentials
is_marketing_callback = marketing_oauth.is_marketing_callback
token_status = marketing_oauth.token_status
fetch_advertiser_list = marketing_oauth.fetch_advertiser_list
load_advertisers = marketing_oauth.load_advertisers
save_app_secret = save_app_secret
