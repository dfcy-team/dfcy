# -*- coding: utf-8 -*-
"""TikTok Marketing API OAuth（广告主授权，只读报表）。"""
from __future__ import annotations

import json
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
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
_active_shop_label: ContextVar[str] = ContextVar("marketing_shop_label", default="")

SHOP_TOKENS_DIR = TOKENS_FILE.parent / "shops"


def _safe_shop_key(shop_label: str) -> str:
    s = (shop_label or "").strip()
    if not s:
        raise ValueError("店铺名不能为空")
    for c in '<>:"/\\|?*':
        s = s.replace(c, "_")
    return s


def shop_token_path(shop_label: str) -> Path:
    return SHOP_TOKENS_DIR / f"{_safe_shop_key(shop_label)}.json"


def set_active_shop_label(shop_label: str) -> None:
    _active_shop_label.set((shop_label or "").strip())


def _resolve_shop_label(shop_label: str | None = None) -> str:
    label = (shop_label or _active_shop_label.get() or "").strip()
    if label:
        return label
    legacy = load_token_legacy()
    if legacy:
        return (legacy.get("shop_label") or "ADS").strip() or "ADS"
    raise RuntimeError("未指定店铺名，请先完成广告授权")


def _migrate_legacy_token() -> None:
    """将旧版单文件 marketing_token.json 迁入 shops/。"""
    if not TOKENS_FILE.is_file():
        return
    SHOP_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    if any(SHOP_TOKENS_DIR.glob("*.json")):
        return
    try:
        data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not data.get("access_token"):
        return
    label = (data.get("shop_label") or "ADS").strip() or "ADS"
    data["shop_label"] = label
    if ADVERTISERS_FILE.is_file() and not data.get("advertisers"):
        try:
            adv_data = json.loads(ADVERTISERS_FILE.read_text(encoding="utf-8"))
            data["advertisers"] = adv_data.get("advertisers") or []
        except (OSError, json.JSONDecodeError):
            pass
    shop_token_path(label).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_token_legacy() -> dict[str, Any] | None:
    if not TOKENS_FILE.is_file():
        return None
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_shop_token(shop_label: str) -> dict[str, Any] | None:
    _migrate_legacy_token()
    path = shop_token_path(shop_label)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_shop_bindings() -> list[dict[str, Any]]:
    _migrate_legacy_token()
    SHOP_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for path in sorted(SHOP_TOKENS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not data.get("access_token"):
            continue
        label = (data.get("shop_label") or path.stem).strip()
        advertisers = data.get("advertisers") or []
        adv_ids = data.get("advertiser_ids") or []
        default_adv = str(data.get("default_advertiser_id") or "").strip()
        out.append(
            {
                "shop_label": label,
                "advertiser_count": len(advertisers) or len(adv_ids),
                "advertisers": advertisers,
                "advertiser_ids": adv_ids,
                "default_advertiser_id": default_adv,
                "saved_at": data.get("saved_at", ""),
                "token_file": path.name,
            }
        )
    return out


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


def exchange_auth_code(auth_code: str, *, shop_label: str = "") -> dict[str, Any]:
    cfg = get_config()
    secret = (cfg.get("APP_SECRET") or "").strip()
    if not secret:
        raise RuntimeError(f"未配置 APP_SECRET，请编辑 {ENV_FILE}")
    if secret == cfg.get("APP_ID"):
        raise RuntimeError("APP_SECRET 误填为 App ID")

    label = (shop_label or "").strip()
    if not label:
        raise RuntimeError("请先填写绑定店铺名")

    code = auth_code.strip()
    if not code:
        raise RuntimeError("auth_code 为空")

    with _exchange_lock:
        code_key = code[-32:]
        if code_key in _exchanged_codes:
            raise RuntimeError("该授权码已处理过，请重新点击「连接广告账户」")
        _exchanged_codes.add(code_key)

    _log_oauth(
        f"EXCHANGE shop={label} app_id={cfg['APP_ID']} secret_fp={secret[:4]}...{secret[-4:]} "
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
        data["shop_label"] = label
        data = refresh_shop_advertisers(label, token_data=data)
        _log_oauth(
            f"OK shop={label} advertisers={len(data.get('advertisers') or [])} "
            f"default={data.get('default_advertiser_id', '')}"
        )
        return data
    except Exception as e:
        _log_oauth(f"FAIL shop={label} {e}")
        raise


def fetch_advertiser_list(access_token: str | None = None, *, shop_label: str | None = None) -> list[dict[str, Any]]:
    token = access_token or get_access_token(shop_label)
    url = f"{API_BASE}/oauth2/advertiser/get/"
    resp = _get_json(url, token, {"app_id": get_config()["APP_ID"], "secret": get_config()["APP_SECRET"]})
    items = (resp.get("data") or {}).get("list") or []
    return items if isinstance(items, list) else []


def _apply_advertiser_snapshot(
    data: dict[str, Any],
    advertisers: list[dict[str, Any]],
    *,
    access_token: str,
) -> dict[str, Any]:
    payload = dict(data)
    payload["advertisers"] = advertisers
    payload["advertiser_ids"] = [
        str(a.get("advertiser_id") or "").strip()
        for a in advertisers
        if str(a.get("advertiser_id") or "").strip()
    ]
    default_id = ""
    if access_token and advertisers:
        try:
            from report_client import find_shop_exclusive_advertiser_id

            default_id = find_shop_exclusive_advertiser_id(advertisers, access_token)
        except Exception:
            default_id = ""
    if not default_id and len(payload["advertiser_ids"]) == 1:
        default_id = payload["advertiser_ids"][0]
    if default_id:
        payload["default_advertiser_id"] = default_id
    return payload


def refresh_shop_advertisers(
    shop_label: str,
    *,
    token_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """用现有 token 刷新广告户列表，并解析店铺专属默认广告户（无需重新 OAuth）。"""
    label = (shop_label or "").strip()
    if not label:
        raise ValueError("店铺名不能为空")
    tok = dict(token_data) if token_data else load_shop_token(label)
    if not tok or not tok.get("access_token"):
        raise RuntimeError(f"店铺「{label}」尚未授权广告账户，请先在 /ads 完成授权")
    tok["shop_label"] = label
    advertisers = fetch_advertiser_list(tok["access_token"])
    tok = _apply_advertiser_snapshot(tok, advertisers, access_token=tok["access_token"])
    save_shop_token(tok)
    save_advertisers(advertisers)
    return tok


def resolve_default_advertiser_id(shop_label: str) -> str:
    """导出时默认广告户：token 中已保存的专属户，或列表中唯一户。"""
    label = (shop_label or "").strip()
    if not label:
        return ""
    tok = load_shop_token(label)
    if not tok:
        return ""
    default_id = str(tok.get("default_advertiser_id") or "").strip()
    if default_id:
        return default_id
    adv_ids = tok.get("advertiser_ids") or []
    if len(adv_ids) == 1:
        return str(adv_ids[0])
    advertisers = tok.get("advertisers") or []
    if len(advertisers) == 1:
        return str(advertisers[0].get("advertiser_id") or "")
    return ""


def refresh_all_shop_advertisers() -> list[dict[str, Any]]:
    """刷新所有已授权店铺的广告户列表（供定时任务 / API 调用）。"""
    _migrate_legacy_token()
    bindings = list_shop_bindings()
    if not bindings:
        legacy = load_token_legacy()
        if legacy and legacy.get("access_token"):
            label = (legacy.get("shop_label") or "ADS").strip() or "ADS"
            bindings = [{"shop_label": label}]
    results: list[dict[str, Any]] = []
    for b in bindings:
        label = (b.get("shop_label") or "").strip()
        if not label:
            continue
        try:
            refreshed = refresh_shop_advertisers(label)
            results.append(
                {
                    "shop_label": label,
                    "ok": True,
                    "advertiser_count": len(refreshed.get("advertisers") or []),
                    "default_advertiser_id": refreshed.get("default_advertiser_id", ""),
                }
            )
        except Exception as e:
            results.append({"shop_label": label, "ok": False, "error": str(e)})
    return results


def save_shop_token(data: dict[str, Any]) -> None:
    if not data.get("access_token"):
        raise RuntimeError("未获得 access_token，授权失败")
    label = (data.get("shop_label") or "").strip()
    if not label:
        raise ValueError("token 缺少 shop_label")
    payload = dict(data)
    payload["saved_at"] = datetime.now(timezone.utc).isoformat()
    SHOP_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    shop_token_path(label).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 兼容旧读取逻辑：最新一家也写一份 legacy（可选，便于排查）
    TOKENS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_token(data: dict[str, Any]) -> None:
    save_shop_token(data)


def load_token(shop_label: str | None = None) -> dict[str, Any] | None:
    if shop_label:
        return load_shop_token(shop_label)
    bindings = list_shop_bindings()
    if bindings:
        return load_shop_token(bindings[0]["shop_label"])
    return load_token_legacy()


def get_access_token(shop_label: str | None = None) -> str:
    label = _resolve_shop_label(shop_label)
    tok = load_shop_token(label)
    if not tok or not tok.get("access_token"):
        # 兼容仅存在 legacy marketing_token.json、尚未按店铺拆 token 的环境
        legacy = load_token_legacy()
        if legacy and legacy.get("access_token"):
            return legacy["access_token"]
        raise RuntimeError(f"店铺「{label}」尚未授权广告账户，请先在 /ads 完成授权")
    return tok["access_token"]


def binding_for_shop(shop_label: str) -> dict[str, Any] | None:
    label = (shop_label or "").strip()
    if not label:
        return None
    for b in list_shop_bindings():
        if b.get("shop_label") == label:
            return b
    return None


def save_advertisers(items: list[dict[str, Any]]) -> None:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "advertisers": items,
    }
    ADVERTISERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_advertisers(shop_label: str | None = None) -> list[dict[str, Any]]:
    label = (shop_label or _active_shop_label.get() or "").strip()
    if label:
        tok = load_shop_token(label)
        if tok and tok.get("advertisers"):
            return tok["advertisers"]
    if ADVERTISERS_FILE.is_file():
        try:
            data = json.loads(ADVERTISERS_FILE.read_text(encoding="utf-8"))
            items = data.get("advertisers") or []
            return items if isinstance(items, list) else []
        except (OSError, json.JSONDecodeError):
            pass
    return []


def save_shop_label(shop_label: str, *, new_label: str | None = None) -> None:
    old = (shop_label or "").strip()
    if not old:
        raise ValueError("店铺名不能为空")
    tok = load_shop_token(old)
    if not tok or not tok.get("access_token"):
        raise RuntimeError(f"店铺「{old}」尚未授权广告账户")
    target = (new_label or old).strip()
    if not target:
        raise ValueError("店铺名不能为空")
    tok["shop_label"] = target
    if target != old:
        old_path = shop_token_path(old)
        if old_path.is_file():
            old_path.unlink()
    save_shop_token(tok)


def token_status(shop_label: str | None = None) -> dict[str, Any]:
    bindings = list_shop_bindings()
    if shop_label:
        b = binding_for_shop(shop_label)
        if not b:
            return {"authorized": False, "shop_label": shop_label}
        return {"authorized": True, **b}
    if not bindings:
        return {"authorized": False, "bindings": [], "binding_count": 0}
    first = bindings[0]
    total_adv = sum(int(b.get("advertiser_count") or 0) for b in bindings)
    return {
        "authorized": True,
        "bindings": bindings,
        "binding_count": len(bindings),
        "shop_label": first.get("shop_label", ""),
        "advertiser_ids": first.get("advertiser_ids") or [],
        "advertiser_count": first.get("advertiser_count") or 0,
        "advertisers": first.get("advertisers") or [],
        "saved_at": first.get("saved_at", ""),
        "total_advertiser_slots": total_adv,
    }
