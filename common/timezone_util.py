# -*- coding: utf-8 -*-
"""IANA 时区解析；Windows 未装 tzdata 时回退到固定 UTC 偏移。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    import tzdata  # noqa: F401
except ImportError:
    pass

REGION_IANA: dict[str, str] = {
    "PH": "Asia/Manila",
    "TH": "Asia/Bangkok",
    "MY": "Asia/Kuala_Lumpur",
    "VN": "Asia/Ho_Chi_Minh",
    "SG": "Asia/Singapore",
    "ID": "Asia/Jakarta",
}

REGION_UTC_OFFSET: dict[str, int] = {
    "PH": 8,
    "TH": 7,
    "MY": 8,
    "VN": 7,
    "SG": 8,
    "ID": 7,
}

IANA_UTC_OFFSET: dict[str, int] = {
    name: REGION_UTC_OFFSET[region]
    for region, name in REGION_IANA.items()
}


def get_timezone(tz_name: str = "Asia/Manila") -> timezone | ZoneInfo:
    name = (tz_name or "Asia/Manila").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        pass
    hours = IANA_UTC_OFFSET.get(name, 8)
    return timezone(timedelta(hours=hours))


def today_in_tz(tz_name: str = "Asia/Manila") -> datetime:
    return datetime.now(get_timezone(tz_name))
