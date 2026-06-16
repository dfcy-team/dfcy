# -*- coding: utf-8 -*-
"""TikTok Marketing API OAuth（广告主授权，只读报表）。"""
from __future__ import annotations

import json
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from config import (
    ADVERTISERS_FILE,
    API_BASE,
    APP_ID,
    AUTH_URL,
    ENV_FILE,
    OAUTH_STATE_PREFIX,
    REDIRECT_URI,
    TOKEN_URL,
    TOKENS_FILE,
    get_config,
    save_app_secret,
)

_exchange_lock = threading.Lock()
_exchanged_codes: set[str] = set()


def build_authorize_url(state: str | None = None) -> tuple[str, str]:
    cfg = get_config()
    csrf = state or f"{cfg['OAUTH_STATE_PREFIX']}_{secrets.token_urlsafe(16)}"
    params = {
        "app_id": cfg["APP_ID"],
        "state": csrf,
        "redirect_uri": cfg["REDIRECT_URI"],
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", csrf


def is_marketing_callback(
    state: str = "",
    auth_code: str = "",
    *,
    code: str = "",
    app_key: str = "",
    scopes: str = "",
) -> bool:
    if app_key or scopes:
        return False
    if auth_code:
        return True
    st = (state or "").lower()
    if st.startswith(get_config()["OAUTH_STATE_PREFIX"].lower()):
        return True
    # Marketing 回调用 auth_code；Shop 用 code。仅有 code 且无 shop state 时不视为 marketing。
    if code and not auth_code:
        return False
    return False


def _log_oauth(msg: str) -> None:
    log_dir = TOKENS_FILE.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "oauth.log"
    ts = datetime.now(timezone.utc).isoformat()
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] [marketing] {msg}\n")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Cache-Control": "no-cache"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"API 返回非 JSON: {raw[:300]}") from e
    if parsed.get("code") not in (0, None):
        msg = parsed.get("message") or parsed.get("msg") or str(parsed.get("code"))
        raise RuntimeError(f"{msg} (code={parsed.get('code')})")
    return parsed


def _get_json(url: str, access_token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    qs = urllib.parse.urlencode(params or {})
    full = f"{url}?{qs}" if qs else url
    req = urllib.request.Request(
        full,
        headers={"Access-Token": access_token, "Cache-Control": "no-cache"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"API 返回非 JSON: {raw[:300]}") from e
    if parsed.get("code") not in (0, None):
        msg = parsed.get("message") or parsed.get("msg") or str(parsed.get("code"))
        raise RuntimeError(f"{msg} (code={parsed.get('code')})")
    return parsed


def extract_auth_code_from_query(query_string: bytes | str) -> str:
    qs = query_string.decode("utf-8", errors="replace") if isinstance(query_string, bytes) else query_string
    for part in qs.split("&"):
        if part.startswith("auth_code="):
            return urllib.parse.unquote(part[10:])
    return ""


def verify_credentials() -> dict[str, Any]:
    cfg = get_config()
    secret = (cfg.get("APP_SECRET") or "").strip()
    if not secret:
        return {"ok": False, "error": "未配置 APP_SECRET"}
    try:
        data = _post_json(
            TOKEN_URL,
            {"app_id": cfg["APP_ID"], "secret": secret, "auth_code": "credential_probe"},
        )
        return {"ok": True, "data": data}
    except RuntimeError as e:
        msg = str(e)
        if "auth_code" in msg.lower() or "invalid" in msg.lower() or "expired" in msg.lower():
            return {"ok": True, "detail": "凭据格式已被 TikTok 接受（auth_code 探测预期失败）"}
        return {"ok": False, "error": msg}


def exchange_auth_code(auth_code: str) -> dict[str, Any]:
    cfg = get_config()
    secret = (cfg.get("APP_SECRET") or "").strip()
    if not secret:
        raise RuntimeError(f"未配置 APP_SECRET，请编辑 {ENV_FILE}")
    if secret == cfg.get("APP_ID"):
        raise RuntimeError("APP_SECRET 误填为 App ID")

    code = auth_code.strip()
    if not code:
        raise RuntimeError("auth_code 为空")

    with _exchange_lock:
        code_key = code[-32:]
        if code_key in _exchanged_codes:
            raise RuntimeError("该授权码已处理过，请重新点击「连接广告账户」")
        _exchanged_codes.add(code_key)

    _log_oauth(
        f"EXCHANGE app_id={cfg['APP_ID']} secret_fp={secret[:4]}...{secret[-4:]} "
        f"code_len={len(code)} code_tail={code[-12:]!r}"
    )

    try:
        resp = _post_json(
            TOKEN_URL,
            {"app_id": cfg["APP_ID"], "secret": secret, "auth_code": code},
        )
        data = resp.get("data") or {}
        if not data.get("access_token"):
            raise RuntimeError("未获得 access_token")
        save_token(data)
        advertisers = fetch_advertiser_list(data["access_token"])
        save_advertisers(advertisers)
        _log_oauth(f"OK advertisers={len(advertisers)} ids={data.get('advertiser_ids', [])}")
        return data
    except Exception as e:
        _log_oauth(f"FAIL {e}")
        raise


def fetch_advertiser_list(access_token: str | None = None) -> list[dict[str, Any]]:
    token = access_token or get_access_token()
    url = f"{API_BASE}/oauth2/advertiser/get/"
    resp = _get_json(url, token, {"app_id": get_config()["APP_ID"], "secret": get_config()["APP_SECRET"]})
    items = (resp.get("data") or {}).get("list") or []
    return items if isinstance(items, list) else []


def save_token(data: dict[str, Any]) -> None:
    if not data.get("access_token"):
        raise RuntimeError("未获得 access_token，授权失败")
    payload = dict(data)
    payload["saved_at"] = datetime.now(timezone.utc).isoformat()
    TOKENS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_token() -> dict[str, Any] | None:
    if not TOKENS_FILE.is_file():
        return None
    return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))


def get_access_token() -> str:
    tok = load_token()
    if not tok or not tok.get("access_token"):
        raise RuntimeError("尚未授权广告账户，请先打开 /ads 完成授权")
    return tok["access_token"]


def save_advertisers(items: list[dict[str, Any]]) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "advertisers": items,
    }
    ADVERTISERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_advertisers() -> list[dict[str, Any]]:
    if not ADVERTISERS_FILE.is_file():
        return []
    data = json.loads(ADVERTISERS_FILE.read_text(encoding="utf-8"))
    items = data.get("advertisers") or []
    return items if isinstance(items, list) else []


def token_status() -> dict[str, Any]:
    tok = load_token()
    if not tok or not tok.get("access_token"):
        return {"authorized": False}
    adv_ids = tok.get("advertiser_ids") or []
    advertisers = load_advertisers()
    return {
        "authorized": True,
        "advertiser_ids": adv_ids,
        "advertiser_count": len(adv_ids) if adv_ids else len(advertisers),
        "advertisers": advertisers,
        "scope": tok.get("scope"),
        "saved_at": tok.get("saved_at", ""),
    }
