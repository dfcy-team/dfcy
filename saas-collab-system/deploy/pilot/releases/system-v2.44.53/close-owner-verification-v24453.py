#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess

VERSION = "2.44.53"
COMMIT = "37eaa4a3344be9d3a3c6897e6e4936972a429c40"
TAG = "v2.44.53-deployed"
UNIFIED = pathlib.Path("/opt/saas-collab/release-control/unified")
LEGACY = pathlib.Path("/opt/saas-collab/release-control/shared-version-ledger")
DEV_B = pathlib.Path("/home/dfcy01/releases/developer-b-influencer-releases")
RELEASE_DIR = pathlib.Path(__file__).resolve().parent


def read_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)


def append_once(path, event, identity):
    if path.exists() and identity in path.read_text(encoding="utf-8"):
        return
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output(*command):
    return subprocess.check_output(command, text=True).strip()


def main():
    unified_current_path = UNIFIED / "ledger/current-version.json"
    legacy_current_path = LEGACY / "current-version.json"
    record_path = UNIFIED / f"releases/{VERSION}/release-record.json"
    policy_path = UNIFIED / "release-policy.json"
    unified = read_json(unified_current_path)
    legacy = read_json(legacy_current_path)
    record = read_json(record_path)
    for payload, label in ((unified, "unified ledger"), (legacy, "legacy ledger")):
        if payload.get("current_release_version") != VERSION or payload.get("git_commit") != COMMIT or payload.get("git_tag") != TAG:
            raise SystemExit(f"V2.44.53 verification close blocked: {label} mismatch")
    if unified.get("status") != "deployed_pending_owner_verification":
        raise SystemExit("V2.44.53 verification close blocked: release is not pending owner verification")
    expected = {
        "application-backend-1": "saas-collab-backend:v2.44.53",
        "application-celery-1": "saas-collab-backend:v2.44.53",
        "application-celery-beat-1": "saas-collab-backend:v2.44.53",
        "application-frontend-1": "saas-collab-frontend:v2.44.53",
    }
    for container, image in expected.items():
        if output("docker", "inspect", container, "--format", "{{.Config.Image}}") != image:
            raise SystemExit(f"V2.44.53 verification close blocked: {container} image mismatch")
    if output("docker", "inspect", "application-custody-sidecar-1", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}") != "healthy":
        raise SystemExit("V2.44.53 verification close blocked: custody sidecar is not healthy")

    now_utc = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    now_local = now_utc.astimezone(dt.timezone(dt.timedelta(hours=8)))
    utc_text = now_utc.isoformat().replace("+00:00", "Z")
    local_text = now_local.strftime("%Y-%m-%dT%H:%M:%S%z")
    backup = RELEASE_DIR / f"owner-verification-backup-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
    backup.mkdir(mode=0o700)
    for source in (unified_current_path, legacy_current_path, record_path, policy_path):
        shutil.copy2(source, backup / source.name)

    for payload in (unified, legacy):
        payload.update({
            "status": "owner_verified",
            "owner_verification": "accepted",
            "owner_verification_required": False,
            "owner_verified_at_utc": utc_text,
            "owner_verified_at_local": local_text,
        })
    record.update({
        "status_in_unified_ledger": "owner_verified",
        "owner_verification": "accepted",
        "owner_verification_required": False,
        "owner_verified_at_utc": utc_text,
        "owner_verified_at_local": local_text,
    })
    atomic_json(unified_current_path, unified)
    atomic_json(legacy_current_path, legacy)
    atomic_json(record_path, record)
    policy = read_json(policy_path)
    policy.setdefault("current_baseline", {})["status"] = "owner_verified"
    atomic_json(policy_path, policy)

    accepted = {
        "schema_version": 1,
        "verification_required": False,
        "status": "owner_verified",
        "release_version": VERSION,
        "git_commit": COMMIT,
        "git_tag": TAG,
        "scope": "influencers",
        "release_actor_role": "architect",
        "source_actor_role": "developer_b",
        "verification_actor_role": "system_owner",
        "verification_result": "accepted",
        "message": "系统负责人验收通过，V2.44.53 达人模块增量发布闭环完成",
        "time_utc": utc_text,
        "time_local": local_text,
    }
    accepted_paths = (
        UNIFIED / f"releases/{VERSION}/OWNER_VERIFICATION_ACCEPTED.json",
        LEGACY / f"releases/{VERSION}/OWNER_VERIFICATION_ACCEPTED.json",
        DEV_B / f"releases/{VERSION}/OWNER_VERIFICATION_ACCEPTED.json",
        RELEASE_DIR / "OWNER_VERIFICATION_ACCEPTED.json",
    )
    for path in accepted_paths:
        atomic_json(path, accepted)

    unified_event = {
        "schema_version": 2,
        "event": "owner_verification_completed",
        "version": VERSION,
        "git_commit": COMMIT,
        "git_tag": TAG,
        "actor": "system_owner",
        "release_actor": "architect",
        "source_actor": "developer_b",
        "scope": "influencers",
        "status": "owner_verified",
        "verification_result": "accepted",
        "time_utc": utc_text,
        "time_local": local_text,
    }
    legacy_event = {
        "schema_version": 1,
        "event": "owner_verification_completed",
        "phase": "owner_acceptance",
        "result": "PASS",
        "actor_role": "system_owner",
        "release_actor_role": "architect",
        "source_actor_role": "developer_b",
        "release_version": VERSION,
        "git_commit": COMMIT,
        "git_tag": TAG,
        "scope": "influencers",
        "status": "owner_verified",
        "verification_result": "accepted",
        "time_utc": utc_text,
        "time_local": local_text,
    }
    append_once(UNIFIED / "ledger/release-history.jsonl", unified_event, '"event":"owner_verification_completed","version":"2.44.53"')
    append_once(LEGACY / "release-ledger.jsonl", legacy_event, '"event":"owner_verification_completed","phase":"owner_acceptance","result":"PASS","actor_role":"system_owner","release_version":"2.44.53"')
    append_once(DEV_B / "release-events.jsonl", legacy_event, '"event":"owner_verification_completed","phase":"owner_acceptance","result":"PASS","actor_role":"system_owner","release_version":"2.44.53"')

    (UNIFIED / "ledger/LATEST.sha256").write_text(f"{sha256(unified_current_path)}  {unified_current_path}\n", encoding="utf-8")
    (LEGACY / "LATEST.sha256").write_text(f"{sha256(legacy_current_path)}  {legacy_current_path}\n", encoding="utf-8")
    print("V2.44.53 OWNER_VERIFICATION_CLOSE=PASS status=owner_verified")


if __name__ == "__main__":
    main()
