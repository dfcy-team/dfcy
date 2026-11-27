"""Collect allowlisted host automation state without executing business tasks."""
import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

UNITS = {
    "replenishment": "saas-replenishment-daily",
    "backup": "saas-collab-backup-maintenance",
    "paired_backup": "saas-paired-daily",
    "board": "dfcy-board-workhours",
    "inbound_feishu": "saas-inbound-feishu",
    "video_cutoff": "saas-tk-video-cutoff",
}
CRONS = {"abc": "saas-inventory-abc", "inventory_warnings": "saas-inventory-warnings",
         "first_sale": "saas-first-sale-date-maintenance"}


def command(args):
    return subprocess.check_output(args, text=True, timeout=10)


def properties(unit):
    text = command(["systemctl", "show", unit, "--no-pager",
        "-p", "LoadState", "-p", "ActiveState", "-p", "UnitFileState",
        "-p", "NextElapseUSecRealtime", "-p", "Result", "-p", "ExecMainStatus",
        "-p", "ExecMainStartTimestamp", "-p", "ExecMainExitTimestamp"])
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def timestamp(value):
    if not value or value == "n/a":
        return None
    # systemctl uses the host timezone. TZ=UTC is set by the entry point.
    try:
        return datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S %Z").replace(
            tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def collect_backend(now):
    """Fixed read-only Django probe; business payloads never leave the process."""
    probe = """import os,json
os.environ.setdefault('DJANGO_SETTINGS_MODULE','cloud_prod_settings')
import django;django.setup()
from config.celery import app
from django.apps import apps
d={'business':{}}
for key,label,name in [('abc','masterdata','InventoryABCRun'),('replenishment','supply_chain','ReplenishmentCalculationJob')]:
 try:
  m=apps.get_model(label,name); fs={f.name for f in m._meta.fields}
  wanted=[f for f in ['id','tenant_id','status','created_at','completed_at','updated_at'] if f in fs]
  d['business'][key]=list(m.objects.order_by('-pk').values(*wanted)[:20])
 except LookupError:pass
print(json.dumps(d,default=str))
"""
    try:
        data = json.loads(command(["docker", "exec", "production-backend-1", "python", "-c", probe]))
    except (OSError, subprocess.SubprocessError, ValueError):
        data = {"business": {}}
    beat_probe = """import os,json
os.environ.setdefault('DJANGO_SETTINGS_MODULE','cloud_prod_settings')
from config.celery import app
print(json.dumps({k:{'schedule':str(v['schedule']),'task':v['task']} for k,v in app.conf.beat_schedule.items()}))
"""
    try:
        data["beat"] = json.loads(command(["docker", "exec", "production-celery-beat-1", "python", "-c", beat_probe]))
    except (OSError, subprocess.SubprocessError, ValueError):
        data["beat"] = {}
    rows = [dict(id="beat:"+key, observed_at=now, enabled=True, state="unknown",
                 schedule=value["schedule"][:200], next_run_at=None, last_result=None)
            for key, value in data.get("beat", {}).items()]
    pattern = re.compile(r"Task ([A-Za-z0-9_.]+)\[([a-fA-F0-9-]+)\] (succeeded|failed)")
    events = {}
    # Docker logs can contain arguments. Keep only regex allowlisted metadata.
    for container in ("production-celery-background-1", "production-celery-control-1"):
        try:
            process = subprocess.run(["docker", "logs", "--since", "15m", "--tail", "1000", container],
                                     capture_output=True, text=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (process.stdout + process.stderr).splitlines():
            match = pattern.search(line)
            stamp = re.search(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),", line)
            if not match or not stamp:
                continue
            name, identity, state = match.groups()
            ended = datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
            events.setdefault(name, []).append(dict(id=identity, status="success" if state == "succeeded" else "failed",
                started_at=None, finished_at=ended, result="Celery 执行成功" if state == "succeeded" else "Celery 执行失败"))
    for row in rows:
        task = data["beat"][row["id"][5:]]["task"]
        runs = events.get(task, [])[-100:]
        row["runs"] = runs
        if runs:
            row["last_result"] = runs[-1]["result"]
    return rows, data.get("business", {})


def collect():
    now = datetime.now(timezone.utc).isoformat()
    tasks = []
    for key, unit in UNITS.items():
        row = dict(id=key, observed_at=now, enabled=None, state="unknown",
                   schedule=None, next_run_at=None, last_result=None)
        try:
            timer = properties(unit + ".timer")
            service = properties(unit + ".service")
            if timer.get("LoadState") != "loaded":
                tasks.append(row)
                continue
            unit_state = timer.get("UnitFileState")
            if unit_state in ("enabled", "enabled-runtime"):
                row["enabled"] = True
            elif unit_state in ("disabled", "masked", "masked-runtime"):
                row["enabled"] = False
            row["state"] = "idle" if timer.get("ActiveState") == "active" else "paused"
            row["next_run_at"] = timestamp(timer.get("NextElapseUSecRealtime"))
            lines = command(["systemctl", "cat", unit + ".timer"]).splitlines()
            row["schedule"] = " ".join(line for line in lines if line.startswith(
                ("OnCalendar=", "OnUnitActiveSec=", "OnBootSec=")))[:200]
            if service.get("ExecMainStartTimestamp"):
                row["last_result"] = ("进程结果 " + service.get("Result", "unknown") +
                    "，退出码 " + service.get("ExecMainStatus", "unknown"))[:200]
            started = timestamp(service.get("ExecMainStartTimestamp"))
            finished = timestamp(service.get("ExecMainExitTimestamp"))
            if started:
                status = "unknown"
                if service.get("ActiveState") in ("active", "activating"):
                    status = "running"
                elif finished:
                    status = "success" if service.get("Result") == "success" and service.get("ExecMainStatus") == "0" else "failed"
                row["runs"] = [dict(id=unit + ":" + started, status=status,
                    started_at=started, finished_at=finished, result=row["last_result"] or "进程结果待确认")]
            if service.get("ActiveState") in ("active", "activating"):
                row["state"] = "running"
            elif service.get("ActiveState") == "failed":
                row["state"] = "failed"
        except (OSError, subprocess.SubprocessError):
            pass
        tasks.append(row)
    for key, name in CRONS.items():
        row = dict(id=key, observed_at=now, enabled=None, state="unknown",
                   schedule=None, next_run_at=None, last_result=None)
        try:
            lines = [line.split() for line in Path("/etc/cron.d", name).read_text().splitlines()
                     if line.strip() and not line.lstrip().startswith("#")]
            schedules = [" ".join(parts[:5]) for parts in lines
                         if len(parts) >= 7 and parts[0][0] in "*0123456789"]
            row["enabled"] = bool(schedules)
            row["schedule"] = " | ".join(schedules)[:200] or None
        except OSError:
            pass
        tasks.append(row)
    beat, business = collect_backend(now)
    for row in tasks:
        records = business.get(row["id"], [])
        if records:
            row["runs"] = [dict(id=str(record["id"]), tenant_id=record["tenant_id"], status={
                "ready":"success", "completed":"success", "failed":"failed", "partial":"partial",
                "running":"running", "building":"running", "queued":"queued"
            }.get(record["status"], "unknown"), started_at=record.get("created_at"),
                finished_at=record.get("completed_at") or (record.get("updated_at") if record["status"] in ("completed","failed") else None),
                result="业务计算状态 " + record["status"]) for record in records]

    return {"tasks": tasks + beat}


def serialize_bounded(snapshot):
    """Keep current task state, discarding oldest run evidence to fit importer cap."""
    while True:
        payload = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
        if len(payload) <= 131072:
            return payload
        candidates = [(run.get("finished_at") or run.get("started_at") or "", row, index)
                      for row in snapshot["tasks"] for index, run in enumerate(row.get("runs", []))]
        if not candidates:
            raise ValueError("Task observations exceed 128 KiB without run history")
        _, row, index = min(candidates, key=lambda item: item[0])
        row["runs"].pop(index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    os.environ["TZ"] = "UTC"
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".observations-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(serialize_bounded(collect()))
        os.chmod(name, 0o600)
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)


if __name__ == "__main__":
    main()
