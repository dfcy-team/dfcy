# -*- coding: utf-8 -*-
"""加载 视频上传/app.env 配置（每次直接从文件读取，避免环境变量缓存）。"""
from __future__ import annotations

from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
TOKENS_DIR = MODULE_ROOT / "tokens"
TOKENS_FILE = TOKENS_DIR / "user_token.json"
ENV_FILE = MODULE_ROOT / "app.env"

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API_BASE = "https://open.tiktokapis.com"


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
        "CLIENT_KEY": vals.get("CLIENT_KEY", "sbaw5qeahefu7vcr2t"),
        "CLIENT_SECRET": vals.get("CLIENT_SECRET", ""),
        "REDIRECT_URI": vals.get("REDIRECT_URI", "https://dingfengchuangyu.top/content/callback"),
        "SCOPES": vals.get("SCOPES", "user.info.basic,video.upload,video.publish"),
        "OAUTH_STATE_PREFIX": vals.get("OAUTH_STATE_PREFIX", "content"),
    }


def save_client_secret(secret: str) -> None:
    secret = secret.strip()
    if not secret:
        raise ValueError("Secret 不能为空")
    cfg = get_config()
    if secret == cfg.get("CLIENT_KEY"):
        raise ValueError("Secret 不能与 Client Key 相同，请粘贴「客户机密」而非「客户端密钥」")
    if len(secret) < 20:
        raise ValueError("Secret 长度异常，请确认复制的是完整客户机密")
    lines: list[str] = []
    found = False
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.strip().startswith("CLIENT_SECRET="):
                lines.append(f"CLIENT_SECRET={secret}")
                found = True
            else:
                lines.append(raw)
    if not found:
        lines.append(f"CLIENT_SECRET={secret}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


_cfg = get_config()
CLIENT_KEY = _cfg["CLIENT_KEY"]
CLIENT_SECRET = _cfg["CLIENT_SECRET"]
REDIRECT_URI = _cfg["REDIRECT_URI"]
SCOPES = _cfg["SCOPES"]
OAUTH_STATE_PREFIX = _cfg["OAUTH_STATE_PREFIX"]

TOKENS_DIR.mkdir(parents=True, exist_ok=True)
