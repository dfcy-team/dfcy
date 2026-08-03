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
PROJECT_ROOT = MARKETING_ROOT.parents[2]


def _load_export_module(report_kind: str = "creative"):
    mod_name = "tiktok_marketing_export_cost" if report_kind == "cost" else "tiktok_marketing_export"
    path = MARKETING_ROOT / ("export_cost_excel.py" if report_kind == "cost" else "export_excel.py")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[mod_name] = mod
    prev = sys.path[:]
    # The web app also loads TikTok Content's modules under generic names such
    # as ``oauth``. Marketing exporters use a different OAuth/config pair;
    # isolate those modules while importing the exporter.
    module_names = ("config", "oauth", "report_client")
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    marketing_cfg_spec = importlib.util.spec_from_file_location(
        "tiktok_marketing_export_config", MARKETING_ROOT / "config.py"
    )
    marketing_cfg = importlib.util.module_from_spec(marketing_cfg_spec)
    assert marketing_cfg_spec.loader is not None
    marketing_cfg_spec.loader.exec_module(marketing_cfg)
    marketing_oauth_spec = importlib.util.spec_from_file_location(
        "tiktok_marketing_export_oauth", MARKETING_ROOT / "oauth.py"
    )
    marketing_oauth = importlib.util.module_from_spec(marketing_oauth_spec)
    assert marketing_oauth_spec.loader is not None
    sys.modules["config"] = marketing_cfg
    marketing_oauth_spec.loader.exec_module(marketing_oauth)
    sys.modules["oauth"] = marketing_oauth
    sys.modules.pop("report_client", None)
    for p in (str(PROJECT_ROOT), str(MARKETING_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = prev
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return mod


def _run_export_job(job: dict) -> None:
    job["status"] = "running"
    _save_job(job)
    try:
        kind = job["report_kind"]
        mod = _load_export_module(kind)
        label = "总花费" if kind == "cost" else kind
        _append_log(job, f"拉取 {label} 报表 {job['start_date']} ~ {job['end_date']}\n")
        prev = sys.path[:]
        if str(MARKETING_ROOT) not in sys.path:
            sys.path.insert(0, str(MARKETING_ROOT))
        try:
            export_kwargs = {
                "advertiser_id": job["advertiser_id"],
                "start_date": job["start_date"],
                "end_date": job["end_date"],
                "shop_label": job.get("shop_label") or job["file_prefix"],
            }
            if kind == "cost":
                out = mod.run_export(**export_kwargs)
            else:
                out = mod.run_export(
                    **export_kwargs,
                    report_kind=kind,
                    file_prefix=job["file_prefix"],
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
