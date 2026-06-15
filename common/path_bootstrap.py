# -*- coding: utf-8 -*-
"""确保 platforms/tiktok/test_env 存在，供各脚本 import shop_tz / tts_client。"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from common.paths import PROJECT_ROOT, TIKTOK_TEST_ENV

TEST_ENV = TIKTOK_TEST_ENV
LEGACY_TEST_ENV = Path(r"C:\Users\Administrator\Desktop\api测试\测试环境")
REQUIRED = ("shop_tz.py", "tts_client.py")


def ensure_test_env() -> Path:
    if all((TEST_ENV / name).exists() for name in REQUIRED):
        return TEST_ENV
    TEST_ENV.mkdir(parents=True, exist_ok=True)
    if LEGACY_TEST_ENV.exists():
        for name in REQUIRED:
            src = LEGACY_TEST_ENV / name
            if src.exists():
                shutil.copy2(src, TEST_ENV / name)
    if all((TEST_ENV / name).exists() for name in REQUIRED):
        return TEST_ENV
    missing = [n for n in REQUIRED if not (TEST_ENV / n).exists()]
    raise FileNotFoundError(
        f"缺少 test_env 模块: {', '.join(missing)}\n"
        f"目录: {TEST_ENV}"
    )


def prepend_test_env() -> Path:
    path = ensure_test_env()
    s = str(path)
    if s not in sys.path:
        sys.path.insert(0, s)
    return path
