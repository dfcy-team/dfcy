# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from services.settings import (
    ANALYTICS_LOGS,
    ANALYTICS_SCRIPT,
    FINANCE_SCRIPT,
    JOBS_DIR,
    ORDER_SCRIPT,
    PROJECT_ROOT,
)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def get_job(job_id: str) -> dict | None:
    with _lock:
        if job_id in _jobs:
            return dict(_jobs[job_id])
    p = _job_path(job_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save_job(job: dict) -> None:
    with _lock:
        _jobs[job["id"]] = dict(job)
    _job_path(job["id"]).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_log(job: dict, line: str) -> None:
    job["log"] = (job.get("log") or "") + line
    if len(job["log"]) > 120_000:
        job["log"] = job["log"][-120_000:]
    _save_job(job)


def _api_end_date(stat_day: str) -> str:
    """店铺分析 API：end 为次日（不含该日）。"""
    d = date.fromisoformat(stat_day)
    return (d + timedelta(days=1)).isoformat()


def _subprocess_env() -> dict:
    import os

    test_env = PROJECT_ROOT / "platforms" / "tiktok" / "test_env"
    parts = [str(PROJECT_ROOT), str(test_env)]
    old = os.environ.get("PYTHONPATH", "")
    if old:
        parts.append(old)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_subprocess(job: dict, script: Path, args: list[str], cwd: Path) -> None:
    import subprocess

    env = _subprocess_env()
    cmd = [sys.executable, str(script), *args]
    _append_log(job, f"\n>>> {' '.join(cmd)}\n\n")
    job["status"] = "running"
    _save_job(job)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_log(job, line)
        rc = proc.wait()
        job["returncode"] = rc
        job["status"] = "done" if rc == 0 else "failed"
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _save_job(job)
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _append_log(job, f"\n[ERROR] {e}\n")
        _save_job(job)


def start_analytics_export(
    *,
    shop_key: str,
    stat_day: str,
    export_types: str = "all",
    fast_mode: bool = True,
) -> str:
    end_api = _api_end_date(stat_day)
    args = [
        "--shop",
        shop_key.upper(),
        "--start",
        stat_day,
        "--end",
        end_api,
        "--type",
        export_types or "all",
        "--all-pages",
        "--export-excel",
    ]
    if fast_mode:
        args.append("--no-video-detail")
    return _start_job("analytics", shop_key, stat_day, ANALYTICS_SCRIPT, args, ANALYTICS_SCRIPT.parent)


def start_finance_export(*, shop_key: str, stat_day: str, finance_type: str = "all") -> str:
    end_api = _api_end_date(stat_day)
    args = [
        "--shop",
        shop_key.upper(),
        "--start",
        stat_day,
        "--end",
        end_api,
        "--type",
        finance_type or "all",
        "--all-pages",
        "--excel",
    ]
    return _start_job("finance", shop_key, stat_day, FINANCE_SCRIPT, args, FINANCE_SCRIPT.parent)


def start_order_export(*, shop_key: str, stat_day: str) -> str:
    end_api = _api_end_date(stat_day)
    args = [
        "--shop",
        shop_key.upper(),
        "--start",
        stat_day,
        "--end",
        end_api,
        "--all-pages",
        "--excel",
    ]
    return _start_job("orders", shop_key, stat_day, ORDER_SCRIPT, args, ORDER_SCRIPT.parent)


def _start_job(
    kind: str,
    shop_key: str,
    stat_day: str,
    script: Path,
    args: list[str],
    cwd: Path,
) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": kind,
        "shop_key": shop_key.upper(),
        "stat_day": stat_day,
        "status": "queued",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "script": str(script),
        "args": args,
        "log": "",
        "logs_dir": str(ANALYTICS_LOGS / shop_key.upper()),
    }
    _save_job(job)
    t = threading.Thread(target=_run_subprocess, args=(job, script, args, cwd), daemon=True)
    t.start()
    return job_id
