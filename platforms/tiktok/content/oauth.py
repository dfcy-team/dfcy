# -*- coding: utf-8 -*-
"""TikTok Login Kit OAuth（Content Posting API）。"""
from __future__ import annotations

import json
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from config import AUTH_URL, ENV_FILE, TOKEN_URL, TOKENS_FILE, get_config

_exchange_lock = threading.Lock()
_exchanged_codes: set[str] = set()


def build_authorize_url(state: str | None = None) -> tuple[str, str]:
    cfg = get_config()
    csrf = state or f"{cfg['OAUTH_STATE_PREFIX']}_{secrets.token_urlsafe(16)}"
    params = {
        "client_key": cfg["CLIENT_KEY"],
        "scope": cfg["SCOPES"],
        "response_type": "code",
        "redirect_uri": cfg["REDIRECT_URI"],
        "state": csrf,
        "disable_auto_auth": "1",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", csrf


def is_content_callback(state: str = "", scopes: str = "", app_key: str = "") -> bool:
    if app_key:
        return False
    if scopes:
        return True
    st = (state or "").lower()
    return st.startswith(get_config()["OAUTH_STATE_PREFIX"].lower())


def _log_oauth(msg: str) -> None:
    log_dir = TOKENS_FILE.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "oauth.log"
    ts = datetime.now(timezone.utc).isoformat()
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    # 完全按 TikTok 文档 curl --data-urlencode 编码（* ! 等也编码）
    body = urllib.parse.urlencode(data, quote_via=lambda s, *_a, **_k: urllib.parse.quote(str(s), safe="")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Token API 返回非 JSON: {raw[:300]}") from e
    if parsed.get("error"):
        desc = parsed.get("error_description") or parsed.get("error")
        log_id = parsed.get("log_id", "")
        raise RuntimeError(f"{desc} (log_id={log_id})")
    return parsed


def extract_code_from_query(query_string: bytes | str) -> str:
    """从原始 query string 提取 code（避免 Flask/Werkzeug 二次解码破坏 code）。"""
    qs = query_string.decode("utf-8", errors="replace") if isinstance(query_string, bytes) else query_string
    for part in qs.split("&"):
        if part.startswith("code="):
            return urllib.parse.unquote(part[5:])
    return ""


def extract_code_from_url(url: str) -> str:
    """从 TikTok 回调完整 URL 中提取 code（只解码一次）。"""
    raw = url.strip()
    if not raw:
        raise ValueError("URL 为空")
    if "://" in raw:
        raw = urllib.parse.urlparse(raw).query
    elif raw.startswith("?"):
        raw = raw[1:]
    elif "code=" in raw and not raw.startswith("code="):
        raw = raw.split("?", 1)[-1]
    for part in raw.split("&"):
        if part.startswith("code="):
            return urllib.parse.unquote(part[5:])
    raise ValueError("URL 中未找到 code 参数")


def verify_credentials() -> dict[str, Any]:
    """用假 code 探测 Key/Secret 是否被 TikTok 接受。"""
    cfg = get_config()
    secret = (cfg.get("CLIENT_SECRET") or "").strip()
    if not secret:
        return {"ok": False, "error": "未配置 CLIENT_SECRET"}
    try:
        data = _post_form(
            TOKEN_URL,
            {
                "client_key": cfg["CLIENT_KEY"],
                "client_secret": secret,
                "code": "credential_probe",
                "grant_type": "authorization_code",
                "redirect_uri": cfg["REDIRECT_URI"],
            },
        )
        return {"ok": True, "data": data}
    except RuntimeError as e:
        msg = str(e)
        if "invalid_client" in msg:
            return {"ok": False, "error": "invalid_client", "detail": msg}
        if "invalid_grant" in msg or "expired" in msg.lower():
            return {"ok": True, "detail": "凭据格式已被 TikTok 接受"}
        return {"ok": False, "error": msg}


def exchange_code(
    code: str,
    *,
    redirect_uri: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    cfg = get_config()
    secret = (cfg.get("CLIENT_SECRET") or "").strip()
    if not secret:
        raise RuntimeError(f"未配置 CLIENT_SECRET，请编辑 {ENV_FILE}")
    if secret == cfg.get("CLIENT_KEY"):
        raise RuntimeError("CLIENT_SECRET 误填为 Client Key，请填写「客户机密」")

    auth_code = code.strip()
    if not auth_code:
        raise RuntimeError("授权 code 为空")

    with _exchange_lock:
        code_key = auth_code[-32:]
        if code_key in _exchanged_codes:
            raise RuntimeError("该授权码已处理过，请重新点击「连接 TikTok」")
        _exchanged_codes.add(code_key)

    redirect = redirect_uri or cfg["REDIRECT_URI"]

    _log_oauth(
        f"EXCHANGE key={cfg['CLIENT_KEY']} secret_fp={secret[:4]}...{secret[-4:]} "
        f"secret_len={len(secret)} redirect={redirect} code_len={len(auth_code)} "
        f"code_tail={auth_code[-12:]!r}"
    )

    payload = {
        "client_key": cfg["CLIENT_KEY"],
        "client_secret": secret,
        "code": auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
    }

    redirects = [redirect]
    alt = redirect.rstrip("/") + "/" if not redirect.endswith("/") else redirect.rstrip("/")
    if alt not in redirects:
        redirects.append(alt)

    last_err: Exception | None = None
    try:
        for idx, redir in enumerate(redirects):
            payload["redirect_uri"] = redir
            if idx:
                _log_oauth(f"RETRY redirect={redir}")
            try:
                data = _post_form(TOKEN_URL, payload)
                if persist:
                    save_token(data)
                _log_oauth(f"OK open_id={data.get('open_id')} scope={data.get('scope')}")
                return data
            except RuntimeError as e:
                last_err = e
                if "invalid_client" not in str(e):
                    raise
        if last_err:
            raise last_err
        raise RuntimeError("换 token 失败")
    except Exception as e:
        _log_oauth(f"FAIL {e}")
        raise


def exchange_callback_url(url: str) -> dict[str, Any]:
    return exchange_code(extract_code_from_url(url))


def refresh_token(refresh: str, *, persist: bool = True) -> dict[str, Any]:
    cfg = get_config()
    secret = (cfg.get("CLIENT_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("未配置 CLIENT_SECRET")
    data = _post_form(
        TOKEN_URL,
        {
            "client_key": cfg["CLIENT_KEY"],
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
    )
    if persist:
        save_token(data)
    return data


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
        raise RuntimeError("尚未授权，请先打开 /content 完成 TikTok 登录授权")
    return tok["access_token"]


def token_status() -> dict[str, Any]:
    tok = load_token()
    if not tok or not tok.get("access_token"):
        return {"authorized": False}
    return {
        "authorized": True,
        "open_id": tok.get("open_id", ""),
        "scope": tok.get("scope", ""),
        "expires_in": tok.get("expires_in"),
        "saved_at": tok.get("saved_at", ""),
    }
