# -*- coding: utf-8 -*-
"""多店铺配置中心 — 解析授权 URL、换 token、切换当前店。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HUB_DIR = Path(__file__).resolve().parent
FORMAL_ROOT = HUB_DIR.parent
_PROJECT = HUB_DIR.parents[2]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))
from common.paths import CURRENT_SHOP_FILE, ensure_export_dirs, migrate_current_shop_file

ensure_export_dirs()
migrate_current_shop_file()
MANIFEST_PATH = HUB_DIR / "shops.json"
CURRENT_PATH = CURRENT_SHOP_FILE
APP_ENV = HUB_DIR / "app.env"
TEMPLATE_ENV = HUB_DIR / "_template.env"

TEST_ENV = FORMAL_ROOT / "test_env"
if str(TEST_ENV) not in sys.path:
    sys.path.insert(0, str(TEST_ENV))


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_manifest(data: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_shops() -> list[dict]:
    return load_manifest().get("shops") or []


def find_shop(arg: str) -> dict | None:
    if not arg:
        return None
    a = arg.strip().lower()
    for s in list_shops():
        keys = {s["key"].lower(), Path(s["config"]).stem.lower()}
        keys.add(s.get("label", "").lower())
        keys.update(x.lower() for x in s.get("aliases", []))
        if a in keys or a == s["config"].lower():
            return s
    return None


def shop_config_path(shop: dict) -> Path:
    return HUB_DIR / shop["config"]


def read_active_key() -> str:
    data = load_manifest()
    if CURRENT_PATH.exists():
        k = CURRENT_PATH.read_text(encoding="utf-8").strip()
        if k:
            return k
    return data.get("active") or "TK1PH"


def set_active_key(key: str) -> Path:
    shop = find_shop(key)
    if not shop:
        raise KeyError(f"未知店铺键: {key}")
    CURRENT_PATH.write_text(shop["key"] + "\n", encoding="utf-8")
    data = load_manifest()
    data["active"] = shop["key"]
    save_manifest(data)
    return shop_config_path(shop)


def resolve_config_by_key(key: str) -> Path | None:
    shop = find_shop(key)
    if not shop:
        return None
    p = shop_config_path(shop)
    return p if p.exists() else None


def resolve_config_from_argv(argv: list[str]) -> Path | None:
    for i, a in enumerate(argv):
        if a in ("--shop", "-s") and i + 1 < len(argv):
            return resolve_config_by_key(argv[i + 1])
    return None


def load_merged_config(config_path: Path) -> None:
    from tts_client import load_env

    if APP_ENV.exists():
        load_env(APP_ENV, override=False)
    load_env(config_path, override=True)
    import os

    os.environ["TTS_CONFIG_FILE"] = str(config_path)
    os.environ["TTS_SHOPS_HUB"] = str(HUB_DIR)


def apply_shop(key: str | None = None) -> Path:
    k = key or read_active_key()
    p = resolve_config_by_key(k)
    if not p:
        raise FileNotFoundError(f"店铺配置不存在: {k} -> config_{k}.env")
    load_merged_config(p)
    return p


def parse_auth_input(text: str) -> dict:
    """从完整回调 URL、或纯 code=ROW_... 提取 code / app_key / region。"""
    text = (text or "").strip().strip('"').strip("'")
    if not text:
        return {}
    if "code=" in text or text.startswith("http"):
        if not text.startswith("http"):
            text = "http://dummy?" + text.lstrip("?")
        q = parse_qs(urlparse(text).query)
        code = (q.get("code") or [""])[0]
        app_key = (q.get("app_key") or [""])[0]
        region = (q.get("shop_region") or [""])[0]
        return {"code": code, "app_key": app_key, "region": region.upper()}
    if text.startswith("ROW_"):
        return {"code": text}
    m = re.search(r"code=(ROW_[^&\s]+)", text)
    if m:
        return {"code": m.group(1)}
    return {}


def ensure_all_registered_configs() -> list[str]:
    """为 shops.json 中已登记但缺少 env 文件的店铺补建配置。"""
    created: list[str] = []
    for shop in list_shops():
        path = shop_config_path(shop)
        if not path.exists():
            ensure_config_file(shop)
            created.append(shop["key"])
    return created


def ensure_config_file(shop: dict) -> Path:
    """店铺已在 shops.json 中，但 config_*.env 缺失时从模板补建。"""
    path = shop_config_path(shop)
    if path.exists():
        return path

    key = shop["key"]
    tag = shop.get("export_tag") or f"TIKTOK{key}"
    region = (shop.get("region") or "PH").upper()
    mode = shop.get("shop_mode") or "local"
    body = TEMPLATE_ENV.read_text(encoding="utf-8") if TEMPLATE_ENV.exists() else (
        "# 新店\nTTS_CONFIG_LABEL={key}\nTTS_EXPORT_SHOP_TAG={tag}\n"
        "TTS_TARGET_REGION=PH\nTTS_SHOP_MODE=local\n"
        "TTS_ACCESS_TOKEN=\nTTS_REFRESH_TOKEN=\nTTS_SHOP_CIPHER=\n"
    )
    text = body.replace("{key}", key).replace("{tag}", tag)
    text = re.sub(r"^TTS_TARGET_REGION=.*$", f"TTS_TARGET_REGION={region}", text, flags=re.M)
    text = re.sub(r"^TTS_SHOP_MODE=.*$", f"TTS_SHOP_MODE={mode}", text, flags=re.M)
    path.write_text(text, encoding="utf-8")
    return path


def create_shop_config(
    key: str,
    label: str = "",
    export_tag: str = "",
    region: str = "PH",
    shop_mode: str = "local",
    aliases: list[str] | None = None,
) -> Path:
    key = key.strip().upper()
    if not re.match(r"^[A-Z0-9_]+$", key):
        raise ValueError("店键仅允许字母数字下划线，如 TK3PH")
    cfg_name = f"config_{key}.env"
    path = HUB_DIR / cfg_name
    if path.exists():
        raise FileExistsError(f"已存在: {path.name}")

    tag = export_tag or f"TIKTOK{key}"
    body = TEMPLATE_ENV.read_text(encoding="utf-8") if TEMPLATE_ENV.exists() else (
        "# 新店\nTTS_CONFIG_LABEL={key}\nTTS_EXPORT_SHOP_TAG={tag}\n"
        "TTS_TARGET_REGION=PH\nTTS_SHOP_MODE=local\n"
        "TTS_ACCESS_TOKEN=\nTTS_REFRESH_TOKEN=\nTTS_SHOP_CIPHER=\n"
    )
    text = body.replace("{key}", key).replace("{tag}", tag)
    text = re.sub(r"^TTS_TARGET_REGION=.*$", f"TTS_TARGET_REGION={region.upper()}", text, flags=re.M)
    text = re.sub(r"^TTS_SHOP_MODE=.*$", f"TTS_SHOP_MODE={shop_mode}", text, flags=re.M)
    path.write_text(text, encoding="utf-8")

    data = load_manifest()
    entry = {
        "key": key,
        "aliases": aliases or [key.lower()],
        "config": cfg_name,
        "label": label or key,
        "export_tag": tag,
        "shop_mode": shop_mode,
        "region": region,
        "notes": "",
    }
    data.setdefault("shops", []).append(entry)
    save_manifest(data)
    return path


def authorize_shop(shop_key: str, auth_input: str, pick_index: int | None = None) -> Path:
    from tts_client import (
        API_VERSION,
        TikTokShopClient,
        cfg,
        get_shops,
        is_ok,
        pick_shop,
        token_updates_from_data,
        update_config_file,
    )

    shop = find_shop(shop_key)
    if not shop:
        raise KeyError(f"未知店铺: {shop_key}，先用 新建店铺.py 创建")

    parsed = parse_auth_input(auth_input)
    code = parsed.get("code", "")
    if not code:
        raise ValueError("未解析到 code，请粘贴完整回调 URL")

    config_path = ensure_config_file(shop)
    load_merged_config(config_path)

    expected_key = cfg("TTS_APP_KEY", "")
    url_key = parsed.get("app_key", "")
    if url_key and expected_key and url_key != expected_key:
        raise ValueError(f"URL 里 app_key={url_key} 与 app.env 中 {expected_key} 不一致")

    region = parsed.get("region") or shop.get("region") or cfg("TTS_TARGET_REGION", "PH")

    client = TikTokShopClient(cfg("TTS_APP_KEY"), cfg("TTS_APP_SECRET"))
    client.config_path = config_path
    tr = client.token_by_code(code)
    if not is_ok(tr):
        raise RuntimeError(f"换 token 失败: {tr}")

    d = tr["data"]
    access = d["access_token"]

    r = client.get(f"/authorization/{API_VERSION}/shops", access)
    cipher = shop_id = shop_name = ""
    if is_ok(r):
        shops = get_shops(r)
        if len(shops) == 1:
            picked = shops[0]
        elif pick_index is not None and 1 <= pick_index <= len(shops):
            picked = shops[pick_index - 1]
        else:
            print("\n本 code 对应多个店铺，请指定 --pick 序号:")
            for i, s in enumerate(shops, 1):
                print(f"  [{i}] {s.get('name')} region={s.get('region')} id={s.get('id')}")
            cipher, picked = pick_shop(shops, region.upper(), cfg("TTS_SHOP_CIPHER", ""))
        if picked:
            cipher = str(picked.get("cipher") or "")
            shop_id = str(picked.get("id") or "")
            shop_name = str(picked.get("name") or "")

    updates = token_updates_from_data(d)
    updates["TTS_AUTH_CODE"] = ""
    if cipher:
        updates["TTS_SHOP_CIPHER"] = cipher
    if shop_id:
        updates["TTS_SHOP_ID"] = shop_id
    if shop_name:
        updates["TTS_SHOP_NAME"] = shop_name
    if region:
        updates["TTS_TARGET_REGION"] = region.upper()

    update_config_file(config_path, updates)

    # 同步 shops.json 备注
    data = load_manifest()
    for s in data.get("shops", []):
        if s["key"] == shop["key"]:
            if shop_name:
                s["notes"] = shop_name
            break
    save_manifest(data)

    set_active_key(shop["key"])
    return config_path


def print_status() -> None:
    active = read_active_key()
    print("=" * 60)
    print(f"配置中心: {HUB_DIR}")
    print(f"应用凭据: {APP_ENV.name}  app_key=6k2of5545ns13")
    print(f"当前店铺: {active}")
    print("-" * 60)
    for s in list_shops():
        p = shop_config_path(s)
        mark = " <-- 当前" if s["key"] == active else ""
        txt = p.read_text(encoding="utf-8") if p.exists() else ""
        ok = "有token" if "TTS_ACCESS_TOKEN=ROW_" in txt or "TTS_ACCESS_TOKEN=GCP_" in txt else "待授权"
        print(f"  [{s['key']}] {s.get('label')}  {ok}{mark}")
        print(f"       文件: {s['config']}  导出标签: {s.get('export_tag')}")
        if s.get("notes"):
            print(f"       店名: {s['notes']}")
    print("=" * 60)
