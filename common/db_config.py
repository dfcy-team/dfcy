# -*- coding: utf-8 -*-
from __future__ import annotations

import configparser
from pathlib import Path

from common.paths import CONFIG_DIR

DB_INI = CONFIG_DIR / "db.ini"


def load_db_config(ini_path: Path | None = None) -> dict:
    path = ini_path or DB_INI
    if not path.exists():
        raise FileNotFoundError(f"数据库配置不存在: {path}")

    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    sec = "数据库"
    tables = "表名"
    site_sec = "站点"

    site_map: dict[str, str] = {}
    if cp.has_section(site_sec):
        for code, name in cp.items(site_sec):
            if code.startswith("#"):
                continue
            site_map[code.strip().upper()] = name.strip()

    return {
        "host": cp.get(sec, "host"),
        "port": cp.getint(sec, "port"),
        "user": cp.get(sec, "user"),
        "password": cp.get(sec, "password"),
        "database": cp.get(sec, "database"),
        "charset": cp.get(sec, "charset", fallback="utf8mb4"),
        "product_table": cp.get(tables, "product_table", fallback="product_performance_report"),
        "sku_table": cp.get(tables, "sku_table", fallback="sku_performance_report"),
        "site_map": site_map or {"PH": "菲律宾", "MY": "马来", "TH": "泰国"},
    }
