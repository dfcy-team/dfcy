# -*- coding: utf-8 -*-
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "SKU上架.py"), run_name="__main__")
