# -*- coding: utf-8 -*-
"""Web 层封装：视频上传模块。"""
from __future__ import annotations

import sys
from pathlib import Path

CONTENT_ROOT = Path(__file__).resolve().parents[2] / "platforms" / "tiktok" / "content"
if str(CONTENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTENT_ROOT))

import oauth as content_oauth  # noqa: E402
import upload_client as content_upload  # noqa: E402
from config import CLIENT_KEY, REDIRECT_URI, save_client_secret  # noqa: E402

UPLOAD_DIR = CONTENT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

build_authorize_url = content_oauth.build_authorize_url
exchange_code = content_oauth.exchange_code
exchange_callback_url = content_oauth.exchange_callback_url
extract_code_from_query = content_oauth.extract_code_from_query
verify_credentials = content_oauth.verify_credentials
is_content_callback = content_oauth.is_content_callback
token_status = content_oauth.token_status
upload_draft = content_upload.upload_draft
upload_direct = content_upload.upload_direct
fetch_publish_status = content_upload.fetch_publish_status
