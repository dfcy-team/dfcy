#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess

COMMIT = "37eaa4a3344be9d3a3c6897e6e4936972a429c40"
ROOT = pathlib.Path("/opt/saas-collab/release-control/unified")
CURRENT = ROOT / "ci-control/current.json"
AUDIT = ROOT / "ci-control/ledger/audit.jsonl"
RELEASE_DIR = pathlib.Path(__file__).resolve().parent


def output(*command):
    return subprocess.check_output(command, text=True).strip()


def atomic_json(path, value):
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main():
    ledger = json.loads((ROOT / "ledger/current-version.json").read_text(encoding="utf-8"))
    if ledger.get("current_release_version") != "2.44.53" or ledger.get("git_commit") != COMMIT:
        raise SystemExit("CI alignment blocked: unified ledger is not V2.44.53")
    expected = {
        "application-backend-1": "saas-collab-backend:v2.44.53",
        "application-celery-1": "saas-collab-backend:v2.44.53",
        "application-celery-beat-1": "saas-collab-backend:v2.44.53",
        "application-frontend-1": "saas-collab-frontend:v2.44.53",
    }
    for container, image in expected.items():
        actual = output("docker", "inspect", container, "--format", "{{.Config.Image}}")
        if actual != image:
            raise SystemExit(f"CI alignment blocked: {container} runs {actual}")

    backup = RELEASE_DIR / "pre-align-ci-control-current.json"
    if not backup.exists():
        shutil.copy2(CURRENT, backup)
        os.chmod(backup, 0o600)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    backend_digest = output("docker", "image", "inspect", "saas-collab-backend:v2.44.53", "--format", "{{.Id}}")
    frontend_digest = output("docker", "image", "inspect", "saas-collab-frontend:v2.44.53", "--format", "{{.Id}}")
    redis_digest = output("docker", "image", "inspect", "redis:7-alpine", "--format", "{{.Id}}")
    migration_sha = hashlib.sha256(b"V2.44.53 database migrations: NONE\n").hexdigest()
    payload = {
        "schema_version": 1,
        "environment": "production",
        "release_sha": COMMIT,
        "backend_image": f"saas-collab-backend:v2.44.53@{backend_digest}",
        "frontend_image": f"saas-collab-frontend:v2.44.53@{frontend_digest}",
        "redis_image": f"redis:7-alpine@{redis_digest}",
        "migration_sha256": migration_sha,
        "manifest_sha256": hashlib.sha256((RELEASE_DIR / "manifest.json").read_bytes()).hexdigest(),
        "actor": "architect",
        "action": "controlled_release_registration",
        "completed_at": now.isoformat().replace("+00:00", "Z"),
        "completed_at_epoch": int(now.timestamp()),
        "production_cutover": False,
        "source_manifest": str(RELEASE_DIR),
    }
    atomic_json(CURRENT, payload)
    event = {
        "time": payload["completed_at"],
        "action": "align-current-after-controlled-release",
        "result": "success",
        "release_sha": COMMIT,
        "actor": "architect",
        "detail": "CI control current aligned to unified V2.44.53 runtime; production_cutover remains false",
    }
    with AUDIT.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(AUDIT, 0o600)
    print("V2.44.53 CI_CONTROL_ALIGNMENT=PASS production_cutover=false")


if __name__ == "__main__":
    main()
