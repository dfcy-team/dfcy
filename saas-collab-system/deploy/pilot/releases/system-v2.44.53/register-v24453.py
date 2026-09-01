#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess

VERSION = "2.44.53"
PARENT = "2.44.52"
PARENT_COMMIT = "e3dc85b948ffa7ddee9bf5ffc7e3ae16d95d4644"
COMMIT = "37eaa4a3344be9d3a3c6897e6e4936972a429c40"
TAG = "v2.44.53-deployed"
SCOPE = "influencers"
CANONICAL_REF = "refs/baselines/canonical-deployed"
UNIFIED = pathlib.Path("/opt/saas-collab/release-control/unified")
LEGACY = pathlib.Path("/opt/saas-collab/release-control/shared-version-ledger")
RELEASE_DIR = pathlib.Path(__file__).resolve().parent
DEV_B_ROOT = pathlib.Path("/home/dfcy01/releases/developer-b-influencer-releases")


def fail(message):
    raise SystemExit(f"V2.44.53 registration blocked: {message}")


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


def append_jsonl(path, payload):
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def image_id(image):
    return output("docker", "image", "inspect", image, "--format", "{{.Id}}")


def running_image(container):
    return output("docker", "inspect", container, "--format", "{{.Config.Image}}")


def image_revision(image):
    return output(
        "docker",
        "image",
        "inspect",
        image,
        "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
    )


def mirror_commit(mirror, ref):
    return output("git", f"--git-dir={mirror}", "rev-parse", f"{ref}^{{commit}}")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if "DEPLOYMENT_VALIDATION=PASS" not in (RELEASE_DIR / "deployment-status.txt").read_text(encoding="utf-8"):
        fail("deployment evidence is not PASS")
    if "VERIFY=PASS" not in (RELEASE_DIR / "verification-status.txt").read_text(encoding="utf-8"):
        fail("verification evidence is not PASS")

    unified_current_path = UNIFIED / "ledger/current-version.json"
    legacy_current_path = LEGACY / "current-version.json"
    unified_history_path = UNIFIED / "ledger/release-history.jsonl"
    legacy_history_path = LEGACY / "release-ledger.jsonl"
    unified_current = read_json(unified_current_path)
    legacy_current = read_json(legacy_current_path)
    for current, label in ((unified_current, "unified"), (legacy_current, "legacy")):
        if current.get("current_release_version") != PARENT or current.get("git_commit") != PARENT_COMMIT:
            fail(f"{label} ledger no longer matches the V2.44.52 parent")

    expected = {
        "application-backend-1": "saas-collab-backend:v2.44.53",
        "application-celery-1": "saas-collab-backend:v2.44.53",
        "application-celery-beat-1": "saas-collab-backend:v2.44.53",
        "application-frontend-1": "saas-collab-frontend:v2.44.53",
        "application-custody-sidecar-1": "saas-collab-custody:v2.44.50",
    }
    for container, image in expected.items():
        if running_image(container) != image:
            fail(f"{container} is not running {image}")
    for image in ("saas-collab-backend:v2.44.53", "saas-collab-frontend:v2.44.53"):
        if image_revision(image) != COMMIT:
            fail(f"{image} revision label does not match the merged commit")

    mirrors = (
        "/home/dfcy01/releases/developer-a-authorized-releases/git-mirror.git",
        "/home/dfcy01/releases/developer-b-influencer-releases/git-mirror.git",
    )
    for mirror in mirrors:
        if mirror_commit(mirror, f"refs/tags/{TAG}") != COMMIT:
            fail(f"{TAG} is missing or incorrect in {mirror}")
        if mirror_commit(mirror, CANONICAL_REF) != COMMIT:
            fail(f"canonical ref is not V2.44.53 in {mirror}")

    backend_digest = image_id("saas-collab-backend:v2.44.53")
    frontend_digest = image_id("saas-collab-frontend:v2.44.53")
    custody_digest = image_id("saas-collab-custody:v2.44.50")
    now_utc = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    local_zone = dt.timezone(dt.timedelta(hours=8))
    now_local = now_utc.astimezone(local_zone)
    now_utc_text = now_utc.isoformat().replace("+00:00", "Z")
    now_local_text = now_local.strftime("%Y-%m-%dT%H:%M:%S%z")

    backup_dir = RELEASE_DIR / f"pre-register-ledger-{now_utc.strftime('%Y%m%dT%H%M%SZ')}"
    backup_dir.mkdir(mode=0o700)
    for source in (
        unified_current_path,
        unified_history_path,
        legacy_current_path,
        legacy_history_path,
        UNIFIED / "release-policy.json",
        UNIFIED / f"releases/{PARENT}/release-record.json",
    ):
        if source.exists():
            shutil.copy2(source, backup_dir / source.name)

    record_path = UNIFIED / f"releases/{VERSION}/release-record.json"
    marker_path = UNIFIED / f"releases/{VERSION}/OWNER_VERIFICATION_REQUIRED.json"
    legacy_marker_path = LEGACY / f"releases/{VERSION}/OWNER_VERIFICATION_REQUIRED.json"
    dev_b_marker_path = DEV_B_ROOT / f"releases/{VERSION}/OWNER_VERIFICATION_REQUIRED.json"
    release_record = {
        "schema_version": 3,
        "version": VERSION,
        "parent_version": PARENT,
        "git_commit": COMMIT,
        "git_tag": TAG,
        "actor": "architect",
        "source_actor": "developer_b",
        "current": True,
        "status_in_unified_ledger": "deployed_pending_owner_verification",
        "scope": SCOPE,
        "canonical_ref": CANONICAL_REF,
        "source_manifest": str(RELEASE_DIR),
        "frontend_image": "saas-collab-frontend:v2.44.53",
        "frontend_digest": frontend_digest,
        "backend_image": "saas-collab-backend:v2.44.53",
        "backend_digest": backend_digest,
        "celery_image": "saas-collab-backend:v2.44.53",
        "celery_beat_image": "saas-collab-backend:v2.44.53",
        "custody_image": "saas-collab-custody:v2.44.50",
        "custody_digest": custody_digest,
        "database_migration_required": False,
        "database_migrations": [],
        "database_backup": None,
        "database_backup_sha256": None,
        "menu_changed": False,
        "router_changed": False,
        "permission_catalog_changed": False,
        "owner_verification": "pending",
        "owner_verification_required": True,
        "deployment_evidence_directory": str(RELEASE_DIR),
        "registered_at_utc": now_utc_text,
        "registered_at_local": now_local_text,
        "rollback": {
            "application_release": PARENT,
            "backend_image": "saas-collab-backend:v2.44.52",
            "frontend_image": "saas-collab-frontend:v2.44.52",
            "custody_sidecar": "saas-collab-custody:v2.44.50",
            "database_restore_required": False,
        },
    }
    marker = {
        "schema_version": 1,
        "status": "deployed_pending_owner_verification",
        "version": VERSION,
        "parent_version": PARENT,
        "git_commit": COMMIT,
        "git_tag": TAG,
        "canonical_ref": CANONICAL_REF,
        "actor": "architect",
        "source_actor": "developer_b",
        "scope": SCOPE,
        "frontend_image": "saas-collab-frontend:v2.44.53",
        "frontend_digest": frontend_digest,
        "backend_image": "saas-collab-backend:v2.44.53",
        "backend_digest": backend_digest,
        "custody_image": "saas-collab-custody:v2.44.50",
        "custody_digest": custody_digest,
        "database_migrations": [],
        "owner_verification": "pending",
        "owner_verification_required": True,
        "verification_evidence": str(RELEASE_DIR),
        "created_at_utc": now_utc_text,
    }
    atomic_json(record_path, release_record)
    for path in (marker_path, legacy_marker_path, dev_b_marker_path, RELEASE_DIR / "OWNER_VERIFICATION_REQUIRED.json"):
        atomic_json(path, marker)

    current_payload = {
        "schema_version": 3,
        "captured_date": now_utc.date().isoformat(),
        "current_release_version": VERSION,
        "parent_release_version": PARENT,
        "git_commit": COMMIT,
        "git_tag": TAG,
        "canonical_ref": CANONICAL_REF,
        "source_manifest": str(RELEASE_DIR),
        "runtime_frontend_image": "saas-collab-frontend:v2.44.53",
        "runtime_frontend_digest": frontend_digest,
        "runtime_backend_image": "saas-collab-backend:v2.44.53",
        "runtime_backend_digest": backend_digest,
        "runtime_custody_image": "saas-collab-custody:v2.44.50",
        "runtime_custody_digest": custody_digest,
        "runtime_celery_image": "saas-collab-backend:v2.44.53",
        "runtime_celery_beat_image": "saas-collab-backend:v2.44.53",
        "status": "deployed_pending_owner_verification",
        "release_actor": "architect",
        "source_actor": "developer_b",
        "release_scope": SCOPE,
        "release_record": str(record_path),
        "database_migration_required": False,
        "database_migrations": [],
        "database_backup": None,
        "database_backup_sha256": None,
        "menu_changed": False,
        "router_changed": False,
        "permission_catalog_changed": False,
        "owner_verification": "pending",
        "owner_verification_required": True,
        "deployed_at_utc": now_utc_text,
        "deployed_at_local": now_local_text,
    }
    legacy_payload = dict(current_payload)
    legacy_payload["schema_version"] = 2
    legacy_payload["runtime_frontend_image_id"] = frontend_digest
    legacy_payload["runtime_backend_image_id"] = backend_digest
    legacy_payload["runtime_custody_image_id"] = custody_digest
    atomic_json(unified_current_path, current_payload)
    atomic_json(legacy_current_path, legacy_payload)

    parent_record_path = UNIFIED / f"releases/{PARENT}/release-record.json"
    if parent_record_path.exists():
        parent_record = read_json(parent_record_path)
        parent_record["current"] = False
        atomic_json(parent_record_path, parent_record)
    policy_path = UNIFIED / "release-policy.json"
    if policy_path.exists():
        policy = read_json(policy_path)
        policy["current_baseline"] = {
            "version": VERSION,
            "git_tag": TAG,
            "git_commit": COMMIT,
            "status": "deployed_pending_owner_verification",
            "database_migrations": [],
        }
        atomic_json(policy_path, policy)

    event = {
        "schema_version": 3,
        "event": "architect_controlled_release_registered",
        "version": VERSION,
        "parent_version": PARENT,
        "git_commit": COMMIT,
        "git_tag": TAG,
        "canonical_ref": CANONICAL_REF,
        "actor": "architect",
        "source_actor": "developer_b",
        "scope": SCOPE,
        "frontend_image": "saas-collab-frontend:v2.44.53",
        "frontend_digest": frontend_digest,
        "backend_image": "saas-collab-backend:v2.44.53",
        "backend_digest": backend_digest,
        "custody_image": "saas-collab-custody:v2.44.50",
        "custody_digest": custody_digest,
        "database_migration_required": False,
        "database_migrations": [],
        "menu_changed": False,
        "router_changed": False,
        "permission_catalog_changed": False,
        "status": "deployed_pending_owner_verification",
        "owner_verification": "pending",
        "time_utc": now_utc_text,
        "time_local": now_local_text,
    }
    append_jsonl(unified_history_path, event)
    append_jsonl(legacy_history_path, event)

    current_link = UNIFIED / "current"
    temporary_link = UNIFIED / f"current.tmp.{os.getpid()}"
    temporary_link.symlink_to(UNIFIED / f"releases/{VERSION}", target_is_directory=True)
    os.replace(temporary_link, current_link)
    (UNIFIED / "ledger/LATEST.sha256").write_text(f"{sha256(unified_current_path)}  {unified_current_path}\n", encoding="utf-8")
    (LEGACY / "LATEST.sha256").write_text(f"{sha256(legacy_current_path)}  {legacy_current_path}\n", encoding="utf-8")

    print(f"V2.44.53 REGISTRATION=PASS status=deployed_pending_owner_verification tag={TAG} scope={SCOPE}")


if __name__ == "__main__":
    main()
