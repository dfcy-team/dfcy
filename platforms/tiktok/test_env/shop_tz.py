# -*- coding: utf-8 -*-
"""店铺国家/时区 — 订单、流水、分析共用。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import tzdata  # noqa: F401
except ImportError:
    pass

KNOWN_REGIONS = ("PH", "TH", "MY", "VN", "SG", "ID", "US", "GB", "MX", "BR")

REGION_IANA: dict[str, str] = {
    "PH": "Asia/Manila",
    "TH": "Asia/Bangkok",
    "MY": "Asia/Kuala_Lumpur",
    "VN": "Asia/Ho_Chi_Minh",
    "SG": "Asia/Singapore",
    "ID": "Asia/Jakarta",
    "US": "America/Los_Angeles",
    "GB": "Europe/London",
    "MX": "America/Mexico_City",
    "BR": "America/Sao_Paulo",
}

REGION_UTC_OFFSET: dict[str, int] = {
    "PH": 8,
    "TH": 7,
    "MY": 8,
    "VN": 7,
    "SG": 8,
    "ID": 7,
}


def get_shop_tz(region: str) -> timezone | ZoneInfo:
    region = (region or "PH").upper()
    name = REGION_IANA.get(region)
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    hours = REGION_UTC_OFFSET.get(region, 8)
    return timezone(timedelta(hours=hours))


def infer_shop_region(
    target_region: str = "",
    config_label: str = "",
    config_stem: str = "",
    export_tag: str = "",
) -> str:
    """优先 TTS_TARGET_REGION，否则从 TK2PH / TIKTOK1号店PH 等后缀推断。"""
    r = (target_region or os.getenv("TTS_TARGET_REGION", "")).strip().upper()
    if r in KNOWN_REGIONS:
        return r
    for src in (config_label, config_stem, export_tag, os.getenv("TTS_CONFIG_LABEL", "")):
        u = str(src).upper().replace("-", "_")
        if u in KNOWN_REGIONS:
            return u
        for code in KNOWN_REGIONS:
            if u.endswith(code) or u.endswith(f"_{code}"):
                return code
    return "PH"


def infer_shop_region_from_cfg(config_file: Path | None = None) -> str:
    from tts_client import cfg

    stem = config_file.stem if config_file else ""
    return infer_shop_region(
        cfg("TTS_TARGET_REGION", ""),
        cfg("TTS_CONFIG_LABEL", stem),
        stem,
        cfg("TTS_EXPORT_SHOP_TAG", ""),
    )


def tz_label(region: str) -> str:
    r = (region or "PH").upper()
    name = REGION_IANA.get(r, "")
    if name:
        return f"{r} ({name})"
    off = REGION_UTC_OFFSET.get(r, 8)
    return f"{r} (UTC+{off})"


def today_local(tz: timezone | ZoneInfo) -> date:
    return datetime.now(tz).date()


def parse_local_date(s: str, tz: timezone | ZoneInfo) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=tz)


def date_range_to_unix(
    start: str, end: str, tz: timezone | ZoneInfo
) -> tuple[int | None, int | None]:
    """当地自然日 → unix；结束日含全天（lt=次日 0 点）。"""
    ge = lt = None
    ds = parse_local_date(start, tz)
    de = parse_local_date(end, tz)
    if ds:
        ge = int(ds.timestamp())
    if de:
        lt = int((de + timedelta(days=1)).timestamp())
    return ge, lt


def fmt_ts(
    ts,
    tz: timezone | ZoneInfo,
    region: str = "PH",
) -> str:
    if ts in (None, "", 0, "0"):
        return ""
    try:
        t = int(ts)
        r = (region or "PH").upper()
        return datetime.fromtimestamp(t, tz=tz).strftime("%Y-%m-%d %H:%M:%S") + f" {r}"
    except (TypeError, ValueError):
        return str(ts)


def pick_config_before_init(env_root: Path, default_config: str = "") -> None:
    """命令行 --config/--shop 优先；否则 店铺配置/CURRENT_SHOP；否则 default。"""
    import sys

    argv = sys.argv[1:]
    if any(a in ("--config", "-c", "--shop", "-s") for a in argv):
        return
    hub = env_root / "shop"
    if hub.exists():
        try:
            proj = env_root.parent
            if str(proj) not in sys.path:
                sys.path.insert(0, str(proj))
            from common.paths import resolve_current_shop_file

            if resolve_current_shop_file().exists():
                return
        except Exception:
            if (hub / "CURRENT_SHOP.txt").exists():
                return
    if default_config.strip():
        os.environ["TTS_CONFIG"] = default_config.strip()
