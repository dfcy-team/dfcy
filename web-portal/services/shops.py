# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

from services.settings import AUTHORIZE_URL, HUB_DIR, PROJECT_ROOT, SHOPS_JSON, SERVICE_ID

_TEST_ENV = PROJECT_ROOT / "platforms" / "tiktok" / "test_env"
if str(_TEST_ENV) not in sys.path:
    sys.path.insert(0, str(_TEST_ENV))
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))


def guess_defaults(shop_key: str) -> tuple[str, str, str, str]:
    """返回 (export_tag, shop_mode, label, region)。"""
    key = shop_key.strip().upper()
    num = ""
    m = re.search(r"(\d+)", key)
    if m:
        num = m.group(1)
    is_cross = "KJ" in key
    if key.endswith("TH"):
        region = "TH"
    elif key.endswith("MY"):
        region = "MY"
    else:
        region = "PH"
    if is_cross and num:
        tag = f"TIKTOK跨境{num}号PH" if region == "PH" else f"TIKTOK跨境{num}号{region}"
    elif num:
        tag = f"TIKTOK{num}号店{region}"
    else:
        tag = f"TIKTOK{key}"
    mode = "cross_border" if is_cross else "local"
    return tag, mode, key, region


def load_shops() -> list[dict]:
    if not SHOPS_JSON.exists():
        return []
    data = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))
    out: list[dict] = []
    for s in data.get("shops") or []:
        key = s.get("key", "")
        cfg_path = HUB_DIR / s.get("config", f"config_{key}.env")
        has_token = False
        shop_name = s.get("notes") or s.get("label") or key
        if cfg_path.exists():
            text = cfg_path.read_text(encoding="utf-8")
            has_token = bool(re.search(r"^TTS_ACCESS_TOKEN=\S+", text, re.M)) or bool(
                re.search(r"^TTS_REFRESH_TOKEN=\S+", text, re.M)
            )
            m = re.search(r"^TTS_SHOP_NAME=(.+)$", text, re.M)
            if m and m.group(1).strip():
                shop_name = m.group(1).strip()
        out.append(
            {
                "key": key,
                "label": s.get("label", key),
                "export_tag": s.get("export_tag", ""),
                "region": s.get("region", "PH"),
                "shop_mode": s.get("shop_mode", "local"),
                "enabled": s.get("enabled", True),
                "has_token": has_token,
                "shop_name": shop_name,
            }
        )
    return out


def list_tiktok_auth_links() -> list[dict]:
    """全部 TikTok 店铺的一键授权链接（含 state，回调可自动绑定）。"""
    if not SHOPS_JSON.exists():
        return []
    data = json.loads(SHOPS_JSON.read_text(encoding="utf-8"))
    by_key = {s["key"]: s for s in (data.get("shops") or [])}
    out: list[dict] = []
    for s in load_shops():
        meta = by_key.get(s["key"]) or {}
        if meta.get("platform") not in (None, "", "tiktok"):
            continue
        out.append(
            {
                "key": s["key"],
                "label": s.get("shop_name") or s.get("label") or s["key"],
                "region": s.get("region", ""),
                "has_token": s.get("has_token", False),
                "enabled": meta.get("enabled", True),
                "url": build_authorize_url(s["key"]),
            }
        )
    return out


def build_authorize_url(shop_key: str) -> str:
    """TikTok 授权链接，state=店键便于回调自动绑定。"""
    key = shop_key.strip().upper()
    base = AUTHORIZE_URL
    if not base:
        base = f"https://services.tiktokshop.com/open/authorize?service_id={SERVICE_ID}"
    parsed = urlparse(base)
    qs = parse_qs(parsed.query)
    flat = {k: v[0] if v else "" for k, v in qs.items()}
    flat["service_id"] = flat.get("service_id") or SERVICE_ID
    flat["state"] = key
    query = urlencode(flat)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def ensure_shop_registered(
    shop_key: str,
    *,
    export_tag: str = "",
    shop_mode: str = "",
    label: str = "",
    region: str = "",
) -> Path:
    from shop_hub import create_shop_config, find_shop, load_manifest, save_manifest

    key = shop_key.strip().upper()
    if not re.match(r"^[A-Z0-9_]+$", key):
        raise ValueError("店键格式错误，例如 TK6PH、TKKJ3PH")

    g_tag, g_mode, g_label, g_region = guess_defaults(key)
    tag = export_tag or g_tag
    mode = shop_mode or g_mode
    lab = label or g_label
    reg = (region or g_region).upper()
    cfg_path = HUB_DIR / f"config_{key}.env"

    if find_shop(key):
        from shop_hub import ensure_config_file

        data = load_manifest()
        shop_entry = None
        for s in data.get("shops", []):
            if s["key"] == key:
                shop_entry = s
                s["export_tag"] = tag
                s["shop_mode"] = mode
                s["region"] = reg
                if lab:
                    s["label"] = lab
                s["enabled"] = True
                break
        save_manifest(data)
        if shop_entry:
            return ensure_config_file(shop_entry)
        return cfg_path

    if cfg_path.exists():
        data = load_manifest()
        if not find_shop(key):
            data.setdefault("shops", []).append(
                {
                    "key": key,
                    "aliases": [key.lower()],
                    "config": cfg_path.name,
                    "label": lab,
                    "export_tag": tag,
                    "shop_mode": mode,
                    "region": reg,
                    "platform": "tiktok",
                    "enabled": True,
                    "notes": "",
                }
            )
            save_manifest(data)
        return cfg_path

    return create_shop_config(
        key,
        label=lab,
        export_tag=tag,
        region=reg,
        shop_mode=mode,
        aliases=[key.lower()],
    )


def authorize_shop_from_callback(
    shop_key: str,
    callback_url: str,
    pick_index: int | None = None,
) -> dict:
    from shop_hub import authorize_shop

    path = authorize_shop(shop_key, callback_url, pick_index=pick_index)
    return {
        "ok": True,
        "config": path.name,
        "shop_key": shop_key.upper(),
        "config_path": str(path),
    }


def setup_and_authorize(
    shop_key: str,
    callback_url: str,
    *,
    pick_index: int | None = None,
    export_tag: str = "",
    shop_mode: str = "",
    label: str = "",
    region: str = "",
    create_if_missing: bool = True,
) -> dict:
    key = shop_key.strip().upper()
    if create_if_missing:
        cfg = ensure_shop_registered(
            key,
            export_tag=export_tag,
            shop_mode=shop_mode,
            label=label,
            region=region,
        )
    else:
        from shop_hub import find_shop

        if not find_shop(key):
            raise KeyError(f"店铺 {key} 未登记，请勾选「自动创建店铺配置」")
        cfg = HUB_DIR / f"config_{key}.env"

    result = authorize_shop_from_callback(key, callback_url, pick_index=pick_index)
    result["created_config"] = cfg.name
    g_tag, g_mode, _, g_region = guess_defaults(key)
    result["export_tag"] = export_tag or g_tag
    result["shop_mode"] = shop_mode or g_mode
    result["region"] = region or g_region
    return result
