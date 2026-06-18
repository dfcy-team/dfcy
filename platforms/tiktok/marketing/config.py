# -*- coding: utf-8 -*-
"""TikTok Marketing API 配置（广告数据分析）。"""
from __future__ import annotations

from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
TOKENS_DIR = MODULE_ROOT / "tokens"
TOKENS_FILE = TOKENS_DIR / "marketing_token.json"
ADVERTISERS_FILE = MODULE_ROOT / "advertisers.json"
ENV_FILE = MODULE_ROOT / "app.env"

AUTH_URL = "https://business-api.tiktok.com/portal/auth"
TOKEN_URL = "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/"
API_BASE = "https://business-api.tiktok.com/open_api/v1.3"


def read_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return vals
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def get_config() -> dict[str, str]:
    vals = read_env()
    return {
        "APP_ID": vals.get("APP_ID", "7651554890895851537"),
        "APP_SECRET": vals.get("APP_SECRET", ""),
        "REDIRECT_URI": vals.get("REDIRECT_URI", "https://dingfengchuangyu.com/callback"),
        "OAUTH_STATE_PREFIX": vals.get("OAUTH_STATE_PREFIX", "ads"),
    }


def save_app_secret(secret: str) -> None:
    secret = secret.strip()
    if not secret:
        raise ValueError("Secret 不能为空")
    cfg = get_config()
    if secret == cfg.get("APP_ID"):
        raise ValueError("Secret 不能与 App ID 相同")
    lines: list[str] = []
    found = False
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.strip().startswith("APP_SECRET="):
                lines.append(f"APP_SECRET={secret}")
                found = True
            else:
                lines.append(raw)
    if not found:
        lines.append(f"APP_SECRET={secret}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


_cfg = get_config()
APP_ID = _cfg["APP_ID"]
APP_SECRET = _cfg["APP_SECRET"]
REDIRECT_URI = _cfg["REDIRECT_URI"]
OAUTH_STATE_PREFIX = _cfg["OAUTH_STATE_PREFIX"]

TOKENS_DIR.mkdir(parents=True, exist_ok=True)
