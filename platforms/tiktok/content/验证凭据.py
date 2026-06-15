# -*- coding: utf-8 -*-
"""验证 TikTok 沙盒凭据（注意：假 code 无法验证 Secret 是否正确）。"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import ENV_FILE, get_config  # noqa: E402

cfg = get_config()
print("env file   :", ENV_FILE)
print("Client Key :", cfg["CLIENT_KEY"])
print("Secret len :", len(cfg["CLIENT_SECRET"]))
print("Redirect   :", cfg["REDIRECT_URI"])
print()

def _token_request(payload: dict) -> dict:
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        "https://open.tiktokapis.com/v2/oauth/token/",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    return json.loads(raw)


auth_test = _token_request(
    {
        "client_key": cfg["CLIENT_KEY"],
        "client_secret": cfg["CLIENT_SECRET"],
        "code": "test",
        "grant_type": "authorization_code",
        "redirect_uri": cfg["REDIRECT_URI"],
    }
)
print("授权码接口探测 (假 code):", auth_test)
print()
if auth_test.get("error") == "invalid_client":
    print("结论: Client Key 或 Client Secret 错误")
    print("请到 Portal 沙盒页重新复制 Secret 到 app.env")
    sys.exit(1)
if auth_test.get("error") == "invalid_grant":
    print("结论: 凭据正确（TikTok 已接受 Key/Secret）。")
    print("请打开 https://dingfengchuangyu.top/content 点「连接 TikTok」完成授权。")
else:
    print("结论: 见上方响应")
