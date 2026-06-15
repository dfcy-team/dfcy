# -*- coding: utf-8 -*-
"""English launcher for product search/detail (avoids CMD encoding issues)."""
from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "商品查询.py"), run_name="__main__")
