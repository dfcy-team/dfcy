"""Fail-closed build evidence helpers. No deployment or business DB access."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

BASELINE_SHA = "8adf0a69a973146070c18c7450eefacc7f7f2829"
MIGRATION_SHA = "21eadb03414e1baa9fc71a9e5f56126e2a885bac790c476334deb9b36b1f9838"
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
    for name, count in (("lock-scope", 9), ("related-regression", 132), ("preflight-rejection", 6)):
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


def verify_sync_workspace_report(directory):
    try:
        tree = ET.parse(directory / "sync-workspace-regression.xml")
    except (OSError, ET.ParseError) as exc:
        raise ValueError("Missing or malformed sync workspace MySQL report") from exc
    cases = tree.findall(".//testcase")
    if len(cases) != 128 or any(case.find(tag) is not None for case in cases
                                 for tag in ("failure", "error", "skipped")):
        raise ValueError("Incomplete or unsuccessful sync workspace MySQL gate")
    return {
        "status": "PASS_REAL_MYSQL_SYNC_WORKSPACE_CURRENT_MODEL_SCHEMA",
        "testcases": 128, "failed": 0, "skipped": 0,
        "mysql": "8.4.11", "django": "5.2.17",
        "schema_mode": "synthetic current-model schema (--nomigrations)",
        "production_database_used": False,
        "limitation": "Validates sync workspace regressions on the synthetic current-model schema; not fresh migration or formal acceptance.",
    }


def verify_sales_reports(directory):
    tree = ET.parse(directory / "sales-regression.xml")
    cases = tree.findall(".//testcase")
    if len(cases) != 85 or any(case.find(tag) is not None for case in cases
                               for tag in ("failure", "error", "skipped")):
        raise ValueError("Incomplete or unsuccessful sales MySQL gate")
    try:
        index = json.loads((directory / "index-migration.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Missing or malformed sales index migration evidence") from exc
    expected = {
        "status": "pass", "migration": "commerce.0006_salesorder_currency_catalog_idx",
        "index": "idx_sales_order_currency", "columns": ["tenant_id", "currency"],
        "forward_and_reverse_checked": True, "rows_unchanged": True,
        "production_database_used": False, "fresh_migration_chain_validated": False,
        "schema_mode": "synthetic current-model schema",
    }
    boolean_keys = ("forward_and_reverse_checked", "rows_unchanged",
                    "production_database_used", "fresh_migration_chain_validated")
    if (any(type(index.get(key)) is not bool for key in boolean_keys)
            or any(index.get(key) != value for key, value in expected.items())):
        raise ValueError("Sales index migration evidence does not match approved migration")
    return {
        "status": "PASS_REAL_MYSQL_SALES_CURRENT_MODEL_SCHEMA", "testcases": 85,
        "failed": 0, "skipped": 0, "index_migration": index,
        "mysql": "8.4.11", "django": "5.2.17",
        "schema_mode": "synthetic current-model schema (--nomigrations)",
        "production_database_used": False,
        "limitation": "Checks the exact new index operation forward and reverse on the disposable current-model schema; does not validate a fresh full migration chain.",
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
    parser.add_argument("operation", choices=["reports", "sales-reports", "sync-workspace-reports", "manifest"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "reports":
        gate = verify_reports(args.directory)
        write_json(args.directory / "mysql-gate.json", gate)
        print("Real MySQL gate passed: 9 lock, 132 related and 6 preflight rejection tests; zero skips.")
        return
    if args.operation == "sales-reports":
        gate = verify_sales_reports(args.directory)
        write_json(args.directory / "mysql-sales-gate.json", gate)
        print("Real MySQL sales gate passed: 85 cases and forward/reverse index migration evidence.")
        return
    if args.operation == "sync-workspace-reports":
        gate = verify_sync_workspace_report(args.directory)
        write_json(args.directory / "mysql-sync-workspace-gate.json", gate)
        print("Real MySQL sync workspace gate passed: 128 cases; zero failures or skips.")
        return
    gate = verify_reports(args.directory)
    sales_gate = verify_sales_reports(args.directory)
    sync_workspace_gate = verify_sync_workspace_report(args.directory)
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
        "mysql_gate": gate, "mysql_sales_gate": sales_gate,
        "mysql_sync_workspace_gate": sync_workspace_gate,
        "vm_mutated": False, "cloud_mutated": False,
        "ledger_mutated": False, "deployment_authorized_by_this_receipt": False,
        "compose_runtime_verified": False,
    })
    print("Immutable production-format manifest created; no deployment performed.")


if __name__ == "__main__":
    main()
