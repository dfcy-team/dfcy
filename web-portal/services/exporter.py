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


def _validate_date_range(start_date: str, end_date: str, *, max_days: int = 93) -> tuple[str, str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    span = (end - start).days + 1
    if span > max_days:
        raise ValueError(f"日期范围不能超过 {max_days} 天")
    return start_date, end_date


def _analytics_api_end(end_inclusive: str) -> str:
    return (date.fromisoformat(end_inclusive) + timedelta(days=1)).isoformat()


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
    start_date: str,
    end_date: str,
    export_types: str = "all",
    fast_mode: bool = True,
) -> str:
    start_date, end_date = _validate_date_range(start_date, end_date)
    end_api = _analytics_api_end(end_date)
    args = [
        "--shop",
        shop_key.upper(),
        "--start",
        start_date,
        "--end",
        end_api,
        "--type",
        export_types or "all",
        "--all-pages",
        "--export-excel",
    ]
    if fast_mode:
        args.append("--no-video-detail")
    return _start_job("analytics", shop_key, start_date, end_date, ANALYTICS_SCRIPT, args, ANALYTICS_SCRIPT.parent)


def start_finance_export(
    *, shop_key: str, start_date: str, end_date: str, finance_type: str = "all"
) -> str:
    start_date, end_date = _validate_date_range(start_date, end_date)
    args = [
        "--shop",
        shop_key.upper(),
        "--start",
        start_date,
        "--end",
        end_date,
        "--type",
        finance_type or "all",
        "--all-pages",
        "--excel",
    ]
    return _start_job("finance", shop_key, start_date, end_date, FINANCE_SCRIPT, args, FINANCE_SCRIPT.parent)


def start_order_export(*, shop_key: str, start_date: str, end_date: str) -> str:
    start_date, end_date = _validate_date_range(start_date, end_date)
    args = [
        "--shop",
        shop_key.upper(),
        "--start",
        start_date,
        "--end",
        end_date,
        "--all-pages",
        "--excel",
    ]
    return _start_job("orders", shop_key, start_date, end_date, ORDER_SCRIPT, args, ORDER_SCRIPT.parent)


def _start_job(
    kind: str,
    shop_key: str,
    start_date: str,
    end_date: str,
    script: Path,
    args: list[str],
    cwd: Path,
) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": kind,
        "shop_key": shop_key.upper(),
        "start_date": start_date,
        "end_date": end_date,
        "stat_day": start_date if start_date == end_date else f"{start_date}~{end_date}",
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
