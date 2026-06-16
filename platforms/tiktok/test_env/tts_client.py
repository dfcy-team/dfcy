# -*- coding: utf-8 -*-
"""TikTok Shop API 公共客户端（测试/正式共用）"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from requests import Response
from requests.exceptions import ChunkedEncodingError, ConnectionError, SSLError, Timeout

API_VERSION = "202309"
AUTH_HOST = "https://auth.tiktok-shops.com"
API_HOST = "https://open-api.tiktokglobalshop.com"

# 连 TikTok 国际站时偶发 SSL 断连，自动重试（视频/商品逐条拉取时仍会再包一层重试）
_HTTP_RETRIES = 6
_HTTP_RETRY_WAIT = (1.5, 3.0, 5.0, 8.0, 12.0)


def _request_with_retry(method: str, url: str, **kwargs) -> Response:
    last_err: Exception | None = None
    for attempt in range(_HTTP_RETRIES):
        try:
            return requests.request(method, url, **kwargs)
        except (SSLError, ConnectionError, Timeout, ChunkedEncodingError) as e:
            last_err = e
            if attempt < _HTTP_RETRIES - 1:
                time.sleep(_HTTP_RETRY_WAIT[min(attempt, len(_HTTP_RETRY_WAIT) - 1)])
    assert last_err is not None
    raise last_err


def load_env(env_file: Path, override: bool = False) -> None:
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if override:
                os.environ[k] = v
            else:
                os.environ.setdefault(k, v)


def strip_config_argv(argv: list[str]) -> list[str]:
    """去掉 --config / --shop，避免和业务参数解析冲突。"""
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] in ("--config", "-c", "--shop", "-s") and i + 1 < len(argv):
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def find_shops_hub_dir(start: Path) -> Path | None:
    """platforms/tiktok/shop 或 legacy 正式环境/店铺配置。"""
    for base in (start, start.parent, start.parent.parent):
        for name in ("shop", "店铺配置"):
            hub = base / name
            if (hub / "shops.json").exists():
                return hub
    return None


def _hub_config_for_key(hub: Path, key: str) -> Path | None:
    try:
        data = json.loads((hub / "shops.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    k = key.strip().lower()
    for s in data.get("shops") or []:
        names = {s.get("key", "").lower(), Path(s.get("config", "")).stem.lower()}
        names.update(a.lower() for a in s.get("aliases") or [])
        if k in names:
            return hub / s["config"]
    return hub / f"config_{key.upper()}.env"


def _current_shop_path(hub: Path) -> Path:
    try:
        proj = hub.parents[2]
        if str(proj) not in sys.path:
            sys.path.insert(0, str(proj))
        from common.paths import resolve_current_shop_file

        return resolve_current_shop_file()
    except Exception:
        return hub / "CURRENT_SHOP.txt"


def resolve_config_path(base_dir: Path, argv: list[str] | None = None) -> Path:
    argv = argv if argv is not None else sys.argv[1:]
    hub = find_shops_hub_dir(base_dir)

    for i, a in enumerate(argv):
        if a in ("--config", "-c") and i + 1 < len(argv):
            name = argv[i + 1]
            p = Path(name)
            return p if p.is_absolute() else base_dir / name

    if hub:
        for i, a in enumerate(argv):
            if a in ("--shop", "-s") and i + 1 < len(argv):
                p = _hub_config_for_key(hub, argv[i + 1])
                if p and p.exists():
                    return p
                raise FileNotFoundError(f"店铺配置不存在: {argv[i + 1]} -> {p}")

        shop_env = os.getenv("TTS_SHOP", "").strip()
        if shop_env:
            p = _hub_config_for_key(hub, shop_env)
            if p and p.exists():
                return p

        cur_file = _current_shop_path(hub)
        if cur_file.exists():
            key = cur_file.read_text(encoding="utf-8").strip()
            if key:
                p = _hub_config_for_key(hub, key)
                if p and p.exists():
                    return p

    custom = os.getenv("TTS_CONFIG", "").strip()
    if custom:
        p = Path(custom)
        if p.is_absolute():
            return p
        if p.exists():
            return p
        if hub and (hub / p.name).exists():
            return hub / p.name
        return base_dir / custom

    if hub:
        active = (hub / "shops.json").read_text(encoding="utf-8")
        try:
            key = json.loads(active).get("active", "")
            if key:
                p = _hub_config_for_key(hub, key)
                if p and p.exists():
                    return p
        except (OSError, json.JSONDecodeError):
            pass

    return base_dir / "config.env"


def init_shop_config(base_dir: Path, argv: list[str] | None = None) -> Path:
    """加载店铺 config；支持 --config、--shop TK2PH（店铺配置目录）、TTS_CONFIG。"""
    path = resolve_config_path(base_dir, argv)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    hub = find_shops_hub_dir(base_dir)
    if hub and (hub / "app.env").exists():
        load_env(hub / "app.env", override=False)
    load_env(path, override=True)
    os.environ["TTS_CONFIG_FILE"] = str(path)
    if hub:
        os.environ["TTS_SHOPS_HUB"] = str(hub)
    return path


def update_config_file(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    done = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else ""
        if key in updates:
            out.append(f"{key}={updates[key]}")
            done.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in done:
            out.append(f"{key}={val}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def cfg(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


TOKEN_EXPIRED_CODES = {105002, "105002"}
_TOKEN_REFRESH_BUFFER = timedelta(minutes=10)


def is_token_expired_error(resp: dict | None) -> bool:
    if not resp:
        return False
    if resp.get("code") in TOKEN_EXPIRED_CODES:
        return True
    msg = str(resp.get("message") or resp.get("msg") or "").lower()
    return "expired credentials" in msg or ("access_token" in msg and "expired" in msg)


def _shop_config_path(config_path: Path | None = None) -> Path | None:
    if config_path and config_path.exists():
        return config_path
    raw = cfg("TTS_CONFIG_FILE")
    if raw:
        p = Path(raw)
        if p.exists():
            return p
    return None


def _token_expires_at(key: str = "TTS_ACCESS_TOKEN_EXPIRES_AT") -> datetime | None:
    raw = cfg(key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _access_token_still_valid() -> bool:
    access = cfg("TTS_ACCESS_TOKEN")
    if not access:
        return False
    exp = _token_expires_at()
    if exp is None:
        return True
    if exp > datetime.now() + timedelta(days=30):
        return False
    return datetime.now() + _TOKEN_REFRESH_BUFFER < exp


def _expiry_iso_from_field(d: dict[str, Any], keys: tuple[str, ...], default_seconds: int) -> str:
    now = datetime.now()
    for k in keys:
        v = d.get(k)
        if v is None or str(v).strip() == "":
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 10_000_000_000:
            n = n // 1000
        if n > 1_000_000_000:
            return datetime.fromtimestamp(n).isoformat(timespec="seconds")
        return (now + timedelta(seconds=n)).isoformat(timespec="seconds")
    return (now + timedelta(seconds=default_seconds)).isoformat(timespec="seconds")


def token_updates_from_data(d: dict[str, Any]) -> dict[str, str]:
    access = str(d.get("access_token") or "")
    refresh = str(d.get("refresh_token") or cfg("TTS_REFRESH_TOKEN") or "")
    return {
        "TTS_ACCESS_TOKEN": access,
        "TTS_REFRESH_TOKEN": refresh,
        "TTS_ACCESS_TOKEN_EXPIRES_AT": _expiry_iso_from_field(
            d, ("access_token_expire_in", "expires_in"), 86400
        ),
        "TTS_REFRESH_TOKEN_EXPIRES_AT": _expiry_iso_from_field(
            d, ("refresh_token_expire_in", "refresh_expires_in"), 31536000
        ),
    }


def refresh_shop_token(
    client: TikTokShopClient,
    config_path: Path | None = None,
    *,
    quiet: bool = False,
) -> str | None:
    refresh = cfg("TTS_REFRESH_TOKEN")
    if not refresh:
        if not quiet:
            print("错误: 缺少 TTS_REFRESH_TOKEN，请重新授权店铺")
        return None
    path = _shop_config_path(config_path)
    r = client.token_refresh(refresh)
    if not is_ok(r):
        if not quiet:
            print(f"续期失败: code={r.get('code')} {r.get('message')}")
        return None
    updates = token_updates_from_data(r.get("data") or {})
    if not updates.get("TTS_ACCESS_TOKEN"):
        if not quiet:
            print("续期失败: 响应中无 access_token")
        return None
    if path:
        update_config_file(path, updates)
        load_env(path, override=True)
    else:
        for k, v in updates.items():
            os.environ[k] = v
    if not quiet:
        print(f"[token] 已自动续期，有效至 {updates['TTS_ACCESS_TOKEN_EXPIRES_AT']}")
    return updates["TTS_ACCESS_TOKEN"]


def get_shop_token(client: TikTokShopClient, config_path: Path | None = None) -> str | None:
    path = _shop_config_path(config_path)
    if path:
        client.config_path = path
    exp = _token_expires_at()
    if _access_token_still_valid():
        if exp is not None:
            token = cfg("TTS_ACCESS_TOKEN")
            if token:
                client.access_token = token
                return token
        elif cfg("TTS_REFRESH_TOKEN"):
            token = refresh_shop_token(client, path)
            if token:
                client.access_token = token
                return token
        token = cfg("TTS_ACCESS_TOKEN")
        if token:
            client.access_token = token
            return token
    if cfg("TTS_REFRESH_TOKEN"):
        token = refresh_shop_token(client, path)
        if token:
            client.access_token = token
            return token
    token = cfg("TTS_ACCESS_TOKEN")
    if token:
        client.access_token = token
        return token
    print("错误: 缺少 TTS_ACCESS_TOKEN / TTS_REFRESH_TOKEN，请运行授权或 授权换token.py")
    return None


class TikTokShopClient:
    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.config_path: Path | None = None
        self.access_token: str = ""

    def _active_token(self, token: str) -> str:
        return self.access_token or token

    def _retry_after_refresh(self, resp: dict, token: str) -> str | None:
        if not is_token_expired_error(resp):
            if is_ok(resp):
                self.access_token = self._active_token(token)
            return None
        if not self.config_path:
            return None
        new = refresh_shop_token(self, self.config_path)
        if new:
            self.access_token = new
            return new
        return None

    def sign(self, path: str, query: dict[str, Any], body: str = "") -> str:
        params = {k: v for k, v in query.items() if k not in ("sign", "access_token", "x-tts-access-token")}
        pieces = "".join(f"{k}{params[k]}" for k in sorted(params))
        wrapped = f"{self.app_secret}{path}{pieces}{body}{self.app_secret}"
        return hmac.new(self.app_secret.encode(), wrapped.encode(), hashlib.sha256).hexdigest()

    def get(self, path: str, token: str, extra: dict | None = None) -> dict:
        tok = self._active_token(token)
        query: dict[str, Any] = {"app_key": self.app_key, "timestamp": int(time.time())}
        if extra:
            query.update(extra)
        query["sign"] = self.sign(path, query)
        r = _request_with_retry(
            "GET",
            f"{API_HOST}{path}",
            params=query,
            headers={"content-type": "application/json", "x-tts-access-token": tok},
            timeout=60,
        )
        data = r.json()
        new = self._retry_after_refresh(data, tok)
        if new:
            query["timestamp"] = int(time.time())
            query["sign"] = self.sign(path, query)
            r = _request_with_retry(
                "GET",
                f"{API_HOST}{path}",
                params=query,
                headers={"content-type": "application/json", "x-tts-access-token": new},
                timeout=60,
            )
            return r.json()
        return data

    def post(self, path: str, token: str, body: dict, extra: dict | None = None) -> dict:
        tok = self._active_token(token)
        query: dict[str, Any] = {"app_key": self.app_key, "timestamp": int(time.time())}
        if extra:
            query.update(extra)
        raw = json.dumps(body, separators=(",", ":"))
        query["sign"] = self.sign(path, query, raw)
        r = _request_with_retry(
            "POST",
            f"{API_HOST}{path}",
            params=query,
            data=raw,
            headers={"content-type": "application/json", "x-tts-access-token": tok},
            timeout=60,
        )
        data = r.json()
        new = self._retry_after_refresh(data, tok)
        if new:
            query["timestamp"] = int(time.time())
            query["sign"] = self.sign(path, query, raw)
            r = _request_with_retry(
                "POST",
                f"{API_HOST}{path}",
                params=query,
                data=raw,
                headers={"content-type": "application/json", "x-tts-access-token": new},
                timeout=60,
            )
            return r.json()
        return data

    def put(self, path: str, token: str, body: dict | None = None, extra: dict | None = None) -> dict:
        query: dict[str, Any] = {"app_key": self.app_key, "timestamp": int(time.time())}
        if extra:
            query.update(extra)
        raw = json.dumps(body if body is not None else {}, separators=(",", ":"))
        query["sign"] = self.sign(path, query, raw)
        r = _request_with_retry(
            "PUT",
            f"{API_HOST}{path}",
            params=query,
            data=raw,
            headers={"content-type": "application/json", "x-tts-access-token": token},
            timeout=60,
        )
        return r.json()

    def delete(self, path: str, token: str, body: dict | None = None, extra: dict | None = None) -> dict:
        query: dict[str, Any] = {"app_key": self.app_key, "timestamp": int(time.time())}
        if extra:
            query.update(extra)
        raw = json.dumps(body if body is not None else {}, separators=(",", ":"))
        query["sign"] = self.sign(path, query, raw)
        r = _request_with_retry(
            "DELETE",
            f"{API_HOST}{path}",
            params=query,
            data=raw,
            headers={"content-type": "application/json", "x-tts-access-token": token},
            timeout=60,
        )
        return r.json()

    def post_multipart(
        self,
        path: str,
        token: str,
        files: dict,
        form: dict | None = None,
        extra: dict | None = None,
    ) -> dict:
        """Multipart POST（如上传图片）；签名时 body 为空字符串。"""
        query: dict[str, Any] = {"app_key": self.app_key, "timestamp": int(time.time())}
        if extra:
            query.update(extra)
        query["sign"] = self.sign(path, query, "")
        r = _request_with_retry(
            "POST",
            f"{API_HOST}{path}",
            params=query,
            data=form or {},
            files=files,
            headers={"x-tts-access-token": token},
            timeout=120,
        )
        return r.json()

    def token_by_code(self, code: str) -> dict:
        return requests.get(
            f"{AUTH_HOST}/api/v2/token/get",
            params={
                "app_key": self.app_key,
                "app_secret": self.app_secret,
                "auth_code": code,
                "grant_type": "authorized_code",
            },
            timeout=30,
        ).json()

    def token_refresh(self, refresh: str) -> dict:
        return requests.get(
            f"{AUTH_HOST}/api/v2/token/refresh",
            params={
                "app_key": self.app_key,
                "app_secret": self.app_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=30,
        ).json()


def is_ok(resp: dict) -> bool:
    return resp.get("code") == 0


def get_shops(resp: dict) -> list[dict]:
    return (resp.get("data") or {}).get("shops") or resp.get("shops") or []


def pick_shop(shops: list[dict], region: str, manual_cipher: str, shop_code: str = "") -> tuple[str, dict | None]:
    if manual_cipher:
        for s in shops:
            if s.get("cipher") == manual_cipher:
                return manual_cipher, s
        return manual_cipher, None
    if shop_code:
        for s in shops:
            if s.get("code") == shop_code:
                return s.get("cipher", ""), s
    for s in shops:
        if (s.get("region") or "").upper() == region:
            return s.get("cipher", ""), s
    return (shops[0].get("cipher", ""), shops[0]) if shops else ("", None)
