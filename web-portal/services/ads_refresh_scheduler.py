# -*- coding: utf-8 -*-
"""网站内置：按 config/广告定时刷新.ini 定时刷新各店广告户列表。"""
from __future__ import annotations

import configparser
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from services.settings import PROJECT_ROOT

INI_PATH = PROJECT_ROOT / "config" / "广告定时刷新.ini"
_started = False
_lock = threading.Lock()


def _read_ini() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    if INI_PATH.is_file():
        cp.read(INI_PATH, encoding="utf-8")
    return cp


def _enabled() -> bool:
    cp = _read_ini()
    val = cp.get("Web服务", "启用内置调度", fallback="1").strip().lower()
    return val in ("1", "true", "yes", "是", "on")


def _timezone_name() -> str:
    cp = _read_ini()
    return cp.get("定时", "时区", fallback="Asia/Manila").strip() or "Asia/Manila"


def _schedule_times() -> list[str]:
    cp = _read_ini()
    times: list[str] = []
    morning = cp.get("定时", "凌晨执行时间", fallback="00:05").strip()
    evening = cp.get("定时", "晚间执行时间", fallback="22:05").strip()
    if morning:
        times.append(morning)
    if evening:
        times.append(evening)
    return times


def _now_in_schedule_tz() -> datetime:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from common.timezone_util import get_timezone

    return datetime.now(get_timezone(_timezone_name()))


def _run_refresh() -> None:
    import importlib.util

    marketing_root = PROJECT_ROOT / "platforms" / "tiktok" / "marketing"
    path = marketing_root / "refresh_advertisers_scheduled.py"
    spec = importlib.util.spec_from_file_location("ads_refresh_scheduled", path)
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    prev = sys.path[:]
    for p in (str(PROJECT_ROOT), str(marketing_root)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        spec.loader.exec_module(mod)
        mod.run_refresh(ini_path=INI_PATH)
    finally:
        sys.path[:] = prev


def _loop() -> None:
    fired: set[str] = set()
    last_day = ""
    while True:
        try:
            now = _now_in_schedule_tz()
            day_key = now.strftime("%Y-%m-%d")
            if day_key != last_day:
                fired.clear()
                last_day = day_key
            hhmm = now.strftime("%H:%M")
            slot = f"{day_key} {hhmm}"
            if hhmm in _schedule_times() and slot not in fired:
                fired.add(slot)
                print(f"[ads_refresh_scheduler] 触发刷新 {slot} ({_timezone_name()})")
                _run_refresh()
        except Exception as e:
            print(f"[ads_refresh_scheduler] {e}")
        time.sleep(30)


def start_if_enabled() -> None:
    """网站启动时调用；已启动或配置关闭时自动跳过。"""
    global _started
    with _lock:
        if _started or not _enabled():
            return
        t = threading.Thread(target=_loop, name="ads_refresh_scheduler", daemon=True)
        t.start()
        _started = True
        times = ", ".join(_schedule_times()) or "—"
        print(f"[ads_refresh_scheduler] 内置调度已启动: {times} ({_timezone_name()})")
