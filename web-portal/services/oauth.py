# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from services.settings import APP_KEY, APP_SECRET, AUTH_BASE, WEB_ROOT


def exchange_code(auth_code: str) -> tuple[bool, str, dict[str, Any] | None]:
    if not APP_KEY or not APP_SECRET:
        return False, "未配置 APP_KEY / APP_SECRET（检查 local.env 或 TikTok_API app.env）", None
    qs = urllib.parse.urlencode(
        {
            "app_key": APP_KEY,
            "app_secret": APP_SECRET,
            "auth_code": auth_code,
            "grant_type": "authorized_code",
        }
    )
    url = f"{AUTH_BASE}/api/v2/token/get?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        return False, f"HTTP {e.code}: {body[:500]}", None
    except Exception as e:
        return False, str(e), None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False, body[:500], None
    if data.get("code") != 0:
        return False, f"code={data.get('code')} {data.get('message')}", data
    log_path = WEB_ROOT / "data" / "last_token.json"
    log_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, "success", data
