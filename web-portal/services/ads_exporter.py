# -*- coding: utf-8 -*-
"""Web 层：TikTok 广告报表导出任务。"""
from __future__ import annotations

import importlib.util
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from services.exporter import _append_log, _save_job, get_job

MARKETING_ROOT = Path(__file__).resolve().parents[2] / "platforms" / "tiktok" / "marketing"


def _load_export_module():
    path = MARKETING_ROOT / "export_excel.py"
    spec = importlib.util.spec_from_file_location("tiktok_marketing_export", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["tiktok_marketing_export"] = mod
    prev = sys.path[:]
    if str(MARKETING_ROOT) not in sys.path:
        sys.path.insert(0, str(MARKETING_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = prev
    return mod


def _run_export_job(job: dict) -> None:
    job["status"] = "running"
    _save_job(job)
    try:
        mod = _load_export_module()
        _append_log(job, f"拉取 {job['report_kind']} 报表 {job['start_date']} ~ {job['end_date']}\n")
        prev = sys.path[:]
        if str(MARKETING_ROOT) not in sys.path:
            sys.path.insert(0, str(MARKETING_ROOT))
        try:
            out = mod.run_export(
                advertiser_id=job["advertiser_id"],
                start_date=job["start_date"],
                end_date=job["end_date"],
                report_kind=job["report_kind"],
                file_prefix=job["file_prefix"],
                shop_label=job.get("shop_label") or job["file_prefix"],
            )
        finally:
            sys.path[:] = prev
        job["output_file"] = str(out)
        job["status"] = "done"
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _append_log(job, f"\n[OK] {out}\n")
        _save_job(job)
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _append_log(job, f"\n[ERROR] {e}\n")
        _save_job(job)


def start_ads_export(
    *,
    advertiser_id: str,
    start_date: str,
    end_date: str,
    report_kind: str,
    file_prefix: str,
    shop_label: str = "",
) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": f"ads_{report_kind}",
        "shop_label": shop_label,
        "advertiser_id": advertiser_id,
        "start_date": start_date,
        "end_date": end_date,
        "report_kind": report_kind,
        "file_prefix": file_prefix,
        "status": "queued",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "log": "",
    }
    _save_job(job)
    t = threading.Thread(target=_run_export_job, args=(job,), daemon=True)
    t.start()
    return job_id
