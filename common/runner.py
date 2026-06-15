# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common.path_bootstrap import ensure_test_env


def run_script(script: Path, args: list[str], *, cwd: Path | None = None) -> int:
    test_env = ensure_test_env()
    env = os.environ.copy()
    extra = str(test_env)
    env["PYTHONPATH"] = extra + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, str(script), *args]
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd or script.parent), env=env)
    return result.returncode


def save_run_log(log_dir: Path, name: str, payload: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"{name}_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
