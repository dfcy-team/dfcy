# -*- coding: utf-8 -*-
"""跨境店 shop_id 分组与主配置店识别（同一 shop_id 只应有一个主配置入库）。"""
from __future__ import annotations

import configparser
import re
from pathlib import Path

from common.paths import DEFAULT_SHOP_HUB, RUN_SHOPS_INI


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def load_shop_profiles(shop_hub: Path | None = None) -> dict[str, dict[str, str]]:
    """{shop_key: {shop_id, shop_cipher, target_region, shop_mode, env_path}}"""
    hub = Path(shop_hub or DEFAULT_SHOP_HUB)
    profiles: dict[str, dict[str, str]] = {}
    for path in sorted(hub.glob("config_*.env")):
        raw = _parse_env_file(path)
        key = (raw.get("TTS_CONFIG_LABEL") or path.stem.replace("config_", "")).upper()
        shop_id = raw.get("TTS_SHOP_ID", "")
        if not shop_id:
            continue
        profiles[key] = {
            "shop_key": key,
            "shop_id": shop_id,
            "shop_cipher": raw.get("TTS_SHOP_CIPHER", ""),
            "target_region": raw.get("TTS_TARGET_REGION", "").upper(),
            "shop_mode": raw.get("TTS_SHOP_MODE", ""),
            "env_path": str(path),
        }
    return profiles


def load_run_shop_keys(ini_path: Path | None = None) -> set[str]:
    path = ini_path or RUN_SHOPS_INI
    if not path.exists():
        return set()
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    raw = cp.get("本次运行", "店铺", fallback="").strip()
    if not raw:
        return set()
    return {s.strip().upper() for s in raw.replace("，", ",").split(",") if s.strip()}


def group_by_shop_id(profiles: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for key, prof in profiles.items():
        sid = prof.get("shop_id", "")
        if not sid:
            continue
        groups.setdefault(sid, []).append(key)
    for sid in groups:
        groups[sid] = sorted(set(groups[sid]))
    return groups


def _region_rank(shop_key: str) -> int:
    m = re.search(r"(PH|TH|MY|SG|VN|ID)$", shop_key.upper())
    order = {"PH": 0, "TH": 1, "MY": 2, "SG": 3, "VN": 4, "ID": 5}
    return order.get(m.group(1) if m else "", 99)


def pick_primary_shop_key(
    shop_keys: list[str],
    *,
    run_keys: set[str] | None = None,
) -> str:
    """同一 shop_id 多国配置中，选唯一主配置店（应用来跑数/入库）。"""
    keys = sorted({k.upper() for k in shop_keys})
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]

    run_keys = run_keys or load_run_shop_keys()
    in_run = [k for k in keys if k in run_keys]
    if len(in_run) == 1:
        return in_run[0]
    if len(in_run) > 1:
        return sorted(in_run, key=_region_rank)[0]

    return sorted(keys, key=_region_rank)[0]


def cross_border_duplicate_groups(
    shop_hub: Path | None = None,
) -> list[dict[str, object]]:
    """返回需要按主配置去重的跨境组（len(shop_keys)>1）。"""
    profiles = load_shop_profiles(shop_hub)
    run_keys = load_run_shop_keys()
    out: list[dict[str, object]] = []
    for shop_id, keys in group_by_shop_id(profiles).items():
        if len(keys) < 2:
            continue
        primary = pick_primary_shop_key(keys, run_keys=run_keys)
        secondary = [k for k in keys if k != primary]
        out.append(
            {
                "shop_id": shop_id,
                "shop_keys": keys,
                "primary": primary,
                "secondary": secondary,
                "profiles": {k: profiles[k] for k in keys if k in profiles},
            }
        )
    return out


def is_primary_shop_for_import(shop_key: str, shop_hub: Path | None = None) -> tuple[bool, str]:
    """导入前检查：非主配置店应跳过商品/SKU/联盟入库，避免同一 shop_id 重复写入。"""
    key = shop_key.upper()
    profiles = load_shop_profiles(shop_hub)
    prof = profiles.get(key)
    if not prof:
        return True, ""

    shop_id = prof["shop_id"]
    group = [k for k, p in profiles.items() if p.get("shop_id") == shop_id]
    if len(group) < 2:
        return True, ""

    primary = pick_primary_shop_key(group)
    if key == primary:
        return True, ""

    others = ", ".join(k for k in group if k != key)
    return False, (
        f"{key} 与 {others} 共用 shop_id={shop_id}；"
        f"请仅用主配置 {primary} 拉数入库（广告可按国家配置单独跑）"
    )


def filter_analytics_shop_keys(
    shop_keys: list[str],
    shop_hub: Path | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """商品/SKU/联盟入库用：去掉同 shop_id 的非主配置店。返回 (保留, [(跳过店, 原因)])."""
    kept: list[str] = []
    skipped: list[tuple[str, str]] = []
    for key in shop_keys:
        ok, msg = is_primary_shop_for_import(key, shop_hub)
        if ok:
            kept.append(key)
        else:
            skipped.append((key, msg))
    return kept, skipped
