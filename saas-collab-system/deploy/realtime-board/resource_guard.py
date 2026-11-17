#!/usr/bin/env python3
"""Reversible CPU affinity guard for explicitly approved production workers."""
from __future__ import annotations

import argparse
try:
    import fcntl
except ImportError:  # Allows mocked unit tests to run on the Windows workstation.
    fcntl = None
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ALLOWED = {
    "production-celery-1", "production-celery-history-1",
    "production-celery-background-1", "production-celery-video-v447-v3-1",
    "production-celery-finance-summary-1", "production-celery-flash-1",
    "production-celery-warehouse-orders-1",
}
LOCK = "/var/lock/dfcy-production-deploy.lock"
MANAGED_CPUSET = "1"
MANAGED_SHARES = 256


def in_work_window(now=None):
    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    return time(9) <= local.time().replace(tzinfo=None) < time(19)


def docker(*args):
    return subprocess.run(["docker", *args], check=False, capture_output=True, text=True, timeout=15)


def inspect(name):
    p = docker("inspect", name)
    if p.returncode:
        return None
    try:
        item = json.loads(p.stdout)[0]
        if not item.get("State", {}).get("Running"):
            return None
        host = item.get("HostConfig", {})
        return {"id": item["Id"], "cpuset": host.get("CpusetCpus") or "", "shares": int(host.get("CpuShares") or 0)}
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}


@contextmanager
def deploy_lock():
    if fcntl is None:
        raise RuntimeError("resource guard requires POSIX flock")
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def update(container_id, cpuset, shares):
    return docker("update", "--cpuset-cpus", str(cpuset), "--cpu-shares", str(shares), container_id).returncode == 0


def cpu_set(value):
    result = set()
    for part in value.split(","):
        if not part:
            continue
        bounds = part.split("-")
        result.update(range(int(bounds[0]), int(bounds[-1]) + 1))
    return result


def restore_target(original):
    # Docker update treats empty cpuset and zero shares as unchanged.
    # Materialize their defaults instead, so a successful command restores capacity.
    cpuset = original["cpuset"]
    if not cpuset:
        cpuset = ",".join(str(cpu) for cpu in sorted(os.sched_getaffinity(0)))
    return cpuset, original["shares"] or 1024


def run(config_path, state_path, restore=False, now=None):
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("ERROR config=1")
        return 2
    names = config.get("containers", [])
    if not isinstance(names, list) or any(n not in ALLOWED or not n.startswith("production-celery-") for n in names):
        print("ERROR config=1")
        return 2
    enabled = bool(config.get("enabled"))
    do_restore = restore or not enabled or not in_work_window(now)
    if not do_restore and (config.get("cpuset") != MANAGED_CPUSET or config.get("cpu_shares") != MANAGED_SHARES):
        print("ERROR config=1")
        return 2
    with deploy_lock() as locked:
        if not locked:
            print("SKIPPED_LOCKED")
            return 0
        state = load_state(state_path)
        counts = {"updated": 0, "restored": 0, "skipped": 0, "errors": 0}
        if do_restore:
            for name, original in list(state.items()):
                current = inspect(name)
                if not current or current["id"] != original.get("id"):
                    counts["skipped"] += 1
                    continue
                if current["cpuset"] != MANAGED_CPUSET or current["shares"] != MANAGED_SHARES:
                    counts["skipped"] += 1
                    continue
                target_cpuset, target_shares = restore_target(original)
                changed = update(current["id"], target_cpuset, target_shares)
                observed = inspect(name) if changed else None
                if (observed and observed["id"] == current["id"]
                        and cpu_set(observed["cpuset"]) == cpu_set(target_cpuset)
                        and observed["shares"] == target_shares):
                    counts["restored"] += 1
                    del state[name]
                else:
                    counts["errors"] += 1
            save_state(state_path, state)
        else:
            if (os.cpu_count() or 0) < 2:
                print("ERROR cpus=1")
                return 2
            for name in names:
                current = inspect(name)
                if not current:
                    counts["skipped"] += 1
                    continue
                previous = state.get(name)
                if previous and previous.get("id") != current["id"]:
                    # Container replacement: do not transfer another ID's snapshot.
                    del state[name]
                    previous = None
                if previous:
                    if current["cpuset"] == MANAGED_CPUSET and current["shares"] == MANAGED_SHARES:
                        counts["skipped"] += 1
                        continue
                    if current["cpuset"] == previous["cpuset"] and current["shares"] == previous["shares"]:
                        check = inspect(name)
                        if check and check["id"] == current["id"] and update(current["id"], MANAGED_CPUSET, MANAGED_SHARES):
                            counts["updated"] += 1
                        else:
                            counts["errors"] += 1
                    else:
                        counts["skipped"] += 1
                    continue
                state[name] = {"id": current["id"], "cpuset": current["cpuset"], "shares": current["shares"]}
                save_state(state_path, state)  # durable snapshot before mutation
                # Recheck identity immediately before updating by immutable ID.
                check = inspect(name)
                if not check or check["id"] != current["id"]:
                    counts["skipped"] += 1
                    continue
                if update(current["id"], MANAGED_CPUSET, MANAGED_SHARES):
                    counts["updated"] += 1
                else:
                    counts["errors"] += 1
            save_state(state_path, state)
        print(" ".join(f"{k}={v}" for k, v in counts.items()))
        return 1 if counts["errors"] else 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args(argv)
    return run(args.config, args.state, args.restore)


if __name__ == "__main__":
    sys.exit(main())
