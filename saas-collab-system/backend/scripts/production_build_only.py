"""Fail-closed build evidence helpers. No deployment or business DB access."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

BASELINE_SHA = "87ef1377164a525750a870cb863b28cd03d6d759"
MIGRATION_SHA = "994211c610a58bf7033491e2ae655464adec7a4d492674d5188ed228c3f9974e"
REDIS_IMAGE = "redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
REPOSITORY = "dfcy-team/dfcy"


def require(pattern, value, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"Invalid {label}")
    return value


def migration_digest(root):
    digest = sha256()
    paths = sorted(root.glob("apps/*/migrations/*.py"))
    if not paths:
        raise ValueError("Missing migration source")
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def verify_reports(directory):
    result = {}
    for name, count in (("lock-scope", 9), ("related-regression", 131), ("preflight-rejection", 6)):
        tree = ET.parse(directory / f"{name}.xml")
        cases = tree.findall(".//testcase")
        if len(cases) != count or any(case.find(tag) is not None for case in cases
                                      for tag in ("failure", "error", "skipped")):
            raise ValueError(f"Incomplete or unsuccessful {name} MySQL gate")
        result[name] = {"passed": count, "failed": 0, "skipped": 0}
    return {
        "status": "PASS_REAL_MYSQL_CURRENT_MODEL_SCHEMA", "suites": result,
        "mysql": "8.4.11", "django": "5.2.17", "isolation": "READ-COMMITTED",
        "schema_mode": "synthetic current-model schema (--nomigrations)",
        "production_database_used": False, "fresh_mysql_migration_validation": False,
        "limitation": "Unchanged development.0002 view DDL conflicts with fresh MySQL atomic migration; this gate is not new-install certification.",
    }


def make_manifest(repository, release_sha, backend_digest, frontend_digest, redis_image, migration_sha):
    if repository != REPOSITORY or redis_image != REDIS_IMAGE or migration_sha != MIGRATION_SHA:
        raise ValueError("Unapproved repository, Redis or migration baseline")
    require(r"[0-9a-f]{40}", release_sha, "release SHA")
    require(r"sha256:[0-9a-f]{64}", backend_digest, "backend digest")
    require(r"sha256:[0-9a-f]{64}", frontend_digest, "frontend digest")
    return {
        "schema_version": 1, "environment": "production", "repository": repository,
        "git_sha": release_sha, "release_sha": release_sha,
        "backend_image": f"ghcr.io/{repository}/saas-collab-backend@{backend_digest}",
        "frontend_image": f"ghcr.io/{repository}/saas-collab-frontend@{frontend_digest}",
        "redis_image": redis_image, "migration_sha256": migration_sha,
        "compose_sha256": "owner-controlled-on-target",
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["reports", "manifest"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    gate = verify_reports(args.directory)
    if args.operation == "reports":
        write_json(args.directory / "mysql-gate.json", gate)
        print("Real MySQL gate passed: 9 lock, 131 related and 6 preflight rejection tests; zero skips.")
        return
    backend_root = Path(__file__).resolve().parents[1]
    migration_sha = migration_digest(backend_root)
    manifest = make_manifest(os.environ["GITHUB_REPOSITORY"], os.environ["RELEASE_SHA"],
                             os.environ["BACKEND_DIGEST"], os.environ["FRONTEND_DIGEST"],
                             os.environ["REDIS_IMAGE"], migration_sha)
    run_id = require(r"[1-9][0-9]*", os.environ["GITHUB_RUN_ID"], "run ID")
    attempt = require(r"[1-9][0-9]*", os.environ["GITHUB_RUN_ATTEMPT"], "run attempt")
    manifest_path = args.directory / "release-manifest.json"
    write_json(manifest_path, manifest)
    write_json(args.directory / "build-only-receipt.json", {
        "schema_version": 1, "status": "BUILT_NOT_DEPLOYED",
        "baseline_git_sha": BASELINE_SHA, "git_sha": manifest["git_sha"],
        "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "workflow_run_id": run_id, "workflow_run_attempt": attempt,
        "mysql_gate": gate, "vm_mutated": False, "cloud_mutated": False,
        "ledger_mutated": False, "deployment_authorized_by_this_receipt": False,
        "compose_runtime_verified": False,
    })
    print("Immutable production-format manifest created; no deployment performed.")


if __name__ == "__main__":
    main()
