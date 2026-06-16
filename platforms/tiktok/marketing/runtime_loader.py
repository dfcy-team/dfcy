# -*- coding: utf-8 -*-
"""隔离加载 marketing 模块，避免与 content/config、content/oauth 冲突。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent


def _load_module(name: str, filename: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    path = ROOT / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def marketing_config() -> ModuleType:
    return _load_module("tiktok_marketing_config", "config.py")


def marketing_oauth() -> ModuleType:
    cfg = marketing_config()
    prev = sys.modules.get("config")
    sys.modules["config"] = cfg
    try:
        return _load_module("tiktok_marketing_oauth", "oauth.py")
    finally:
        if prev is not None:
            sys.modules["config"] = prev
        else:
            sys.modules.pop("config", None)


def marketing_report_client() -> ModuleType:
    oauth = marketing_oauth()
    prev_cfg = sys.modules.get("config")
    prev_oauth = sys.modules.get("oauth")
    sys.modules["config"] = marketing_config()
    sys.modules["oauth"] = oauth
    try:
        # 报表模块依赖顶层 config/oauth 名称
        sys.modules.pop("tiktok_marketing_report_client", None)
        return _load_module("tiktok_marketing_report_client", "report_client.py")
    finally:
        if prev_cfg is not None:
            sys.modules["config"] = prev_cfg
        else:
            sys.modules.pop("config", None)
        if prev_oauth is not None:
            sys.modules["oauth"] = prev_oauth
        else:
            sys.modules.pop("oauth", None)
