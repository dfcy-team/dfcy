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
HISTORICAL_MIGRATION_SHA = "f4837ab083886904019f352dc40a4fbb14f9fcbfd86352ecad0514c2b50cc649"
HISTORICAL_TARGETS = {
    "278b8f8759fc427510d57bbdd7bc23297a5b3e80": "2305aca1d6b50df256cf386dfe46b888ca5a8ac0",
    "96dd97a2bd3ea51ef57ae6e1e40741e078122753": "c1460c97e619ad4a35c36f9a8e523dc3ab239755",
}
V330_IDENTITY_PATH = (Path(__file__).resolve().parents[2] / "deploy/production-control/ci/v330-release-identity.json")
V330_IDENTITY = json.loads(V330_IDENTITY_PATH.read_text(encoding="utf-8"))
V330_SOURCE_SHA = V330_IDENTITY["source_sha"]
V330_SOURCE_TREE = V330_IDENTITY["source_tree"]
V330_SOURCE_MIGRATION_SHA = V330_IDENTITY["source_migration_sha256"]
V315_BASELINE_MIGRATION_SHA = V330_IDENTITY["baseline_migration_sha256"]
REDIS_IMAGE = "redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
REPOSITORY = "dfcy-team/dfcy"
GITHUB_ACTIONS_APP_ID = 15368


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
        # Checkout line endings must not change the approved source fingerprint.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def expected_testcases(path):
    """Convert pytest --collect-only node IDs to JUnit (classname, name) pairs."""
    nodeids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
               if "::" in line and not line.lstrip().startswith("=")]
    if not nodeids or len(nodeids) != len(set(nodeids)):
        raise ValueError("Missing or duplicate collected pytest node IDs")
    result = set()
    for nodeid in nodeids:
        module, *parts = nodeid.split("::")
        classname = module.removesuffix(".py").replace("/", ".").replace("\\", ".")
        result.add((classname + ("." + ".".join(parts[:-1]) if len(parts) > 1 else ""), parts[-1]))
    return result


def verify_junit(path, expected_path, label):
    try:
        tree = ET.parse(path)
        expected = expected_testcases(expected_path)
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"Missing or malformed {label} test evidence") from exc
    cases = tree.findall(".//testcase")
    actual = {(case.get("classname", ""), case.get("name", "")) for case in cases}
    if (not cases or actual != expected or len(actual) != len(cases)
            or any(case.find(tag) is not None for case in cases
                   for tag in ("failure", "error", "skipped"))):
        raise ValueError(f"Incomplete, skipped or unsuccessful {label} MySQL gate")
    return len(cases)


def validate_historical_source(release_sha, tree_sha, migration_sha):
    """Allow only the two reviewed historical business snapshots."""
    expected_tree = HISTORICAL_TARGETS.get(release_sha)
    if (expected_tree is None or tree_sha != expected_tree
            or migration_sha != HISTORICAL_MIGRATION_SHA):
        raise ValueError("Unapproved historical source, tree or migration fingerprint")
    return {"release_sha": release_sha, "tree_sha": tree_sha,
            "migration_sha256": migration_sha}


def validate_v330_controller(controller_sha, approved):
    if (not isinstance(approved, str) or not re.fullmatch(r"[0-9a-f]{40}", approved)
            or controller_sha != approved):
        raise ValueError("Unapproved V330 build controller")
    return approved


def validate_v330_source(release_sha, tree_sha, migration_sha):
    """Allow only the independently approved V330 cumulative source snapshot."""
    if (release_sha != V330_SOURCE_SHA or tree_sha != V330_SOURCE_TREE
            or migration_sha != V330_SOURCE_MIGRATION_SHA):
        raise ValueError("Unapproved V330 source, tree or migration fingerprint")
    return {"release_sha": release_sha, "tree_sha": tree_sha,
            "migration_sha256": migration_sha}


def verify_github_release_evidence(branch_response, checks_response, release_sha):
    """Fail closed unless protected main requires checks that passed on this exact SHA."""
    if not isinstance(branch_response, dict) or branch_response.get("protected") is not True:
        raise ValueError("main branch is not confirmed protected")
    protection = branch_response.get("protection")
    required = protection.get("required_status_checks") if isinstance(protection, dict) else None
    if not isinstance(required, dict):
        raise ValueError("main required checks are unavailable")
    constraints = required.get("checks") or []
    legacy_contexts = required.get("contexts") or []
    wanted = [(row.get("context"), row.get("app_id")) for row in constraints
              if isinstance(row, dict)]
    wanted.extend((context, GITHUB_ACTIONS_APP_ID) for context in legacy_contexts
                  if isinstance(context, str))
    if (not wanted or len(wanted) != len(constraints) + len(legacy_contexts)
            or any(not isinstance(name, str) or not name or app_id != GITHUB_ACTIONS_APP_ID
                   for name, app_id in wanted)):
        raise ValueError("main required checks are not the expected GitHub Actions checks")
    wanted = list(dict.fromkeys(wanted))

    if not isinstance(checks_response, dict) or not isinstance(checks_response.get("check_runs"), list):
        raise ValueError("release check-runs response is malformed")
    runs = checks_response["check_runs"]
    total_count = checks_response.get("total_count")
    if type(total_count) is not int or total_count != len(runs):
        raise ValueError("release check-runs response is incomplete")
    latest = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("name"), str) or type(run.get("id")) is not int:
            raise ValueError("release check-runs response is malformed")
        if run["name"] not in latest or run["id"] > latest[run["name"]]["id"]:
            latest[run["name"]] = run
    for context, app_id in wanted:
        run = latest.get(context)
        if (run is None or (run.get("app") or {}).get("id") != app_id
                or run.get("head_sha") != release_sha
                or run.get("status") != "completed" or run.get("conclusion") != "success"):
            raise ValueError(f"Required check did not pass for exact release: {context}")
    return {"protected": True, "required_checks": len(wanted), "release_sha": release_sha}


def verify_reports(directory, expected_directory=None):
    result = {}
    if expected_directory is not None:
        for name in ("lock-scope", "related-regression", "preflight-rejection"):
            count = verify_junit(directory / f"{name}.xml", expected_directory / f"{name}.nodeids", name)
            result[name] = {"passed": count, "failed": 0, "skipped": 0}
        return {"status": "PASS_REAL_MYSQL_CURRENT_MODEL_SCHEMA", "suites": result,
                "mysql": "8.4.11", "django": "5.2.17",
                "schema_mode": "synthetic current-model schema (--nomigrations)",
                "production_database_used": False, "fresh_mysql_migration_validation": False,
                "limitation": "Unchanged development.0002 view DDL conflicts with fresh MySQL atomic migration; this gate is not new-install certification."}
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


def verify_sync_workspace_report(directory, expected_directory=None):
    if expected_directory is not None:
        count = verify_junit(directory / "sync-workspace-regression.xml",
                             expected_directory / "sync-workspace-regression.nodeids", "sync workspace")
        return {"status": "PASS_REAL_MYSQL_SYNC_WORKSPACE_CURRENT_MODEL_SCHEMA",
                "testcases": count, "failed": 0, "skipped": 0,
                "mysql": "8.4.11", "django": "5.2.17",
                "schema_mode": "synthetic current-model schema (--nomigrations)",
                "production_database_used": False,
                "limitation": "Validates sync workspace regressions on the synthetic current-model schema; not fresh migration or formal acceptance."}
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


def verify_sales_reports(directory, expected_directory=None):
    tree = ET.parse(directory / "sales-regression.xml")
    cases = tree.findall(".//testcase")
    if expected_directory is not None:
        count = verify_junit(directory / "sales-regression.xml",
                             expected_directory / "sales-regression.nodeids", "sales")
    else:
        count = 85
        if len(cases) != count or any(case.find(tag) is not None for case in cases
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
        "status": "PASS_REAL_MYSQL_SALES_CURRENT_MODEL_SCHEMA", "testcases": count,
        "failed": 0, "skipped": 0, "index_migration": index,
        "mysql": "8.4.11", "django": "5.2.17",
        "schema_mode": "synthetic current-model schema (--nomigrations)",
        "production_database_used": False,
        "limitation": "Checks the exact new index operation forward and reverse on the disposable current-model schema; does not validate a fresh full migration chain.",
    }


def make_manifest(repository, release_sha, backend_digest, frontend_digest, redis_image, migration_sha):
    historical_migration = HISTORICAL_TARGETS.get(release_sha) and migration_sha == HISTORICAL_MIGRATION_SHA
    v330_source_migration = (release_sha == V330_SOURCE_SHA
                             and migration_sha == V330_SOURCE_MIGRATION_SHA)
    if (repository != REPOSITORY or redis_image != REDIS_IMAGE
            or (migration_sha != MIGRATION_SHA and not historical_migration
                and not v330_source_migration)):
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
    parser.add_argument("operation", choices=["reports", "sales-reports", "sync-workspace-reports", "manifest", "validate-history"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--release-sha")
    parser.add_argument("--tree-sha")
    parser.add_argument("--migration-sha")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--expected-directory", type=Path)
    args = parser.parse_args()
    if args.operation == "validate-history":
        result = validate_historical_source(args.release_sha, args.tree_sha, args.migration_sha)
        write_json(args.directory / "historical-source.json", result)
        print("Approved exact historical source and migration fingerprint.")
        return
    if args.operation == "reports":
        gate = verify_reports(args.directory, args.expected_directory)
        write_json(args.directory / "mysql-gate.json", gate)
        print("Real MySQL lock, related and preflight gates passed; test IDs matched the source collection.")
        return
    if args.operation == "sales-reports":
        gate = verify_sales_reports(args.directory, args.expected_directory)
        write_json(args.directory / "mysql-sales-gate.json", gate)
        print("Real MySQL sales gate passed: collected test IDs matched and forward/reverse index migration evidence verified.")
        return
    if args.operation == "sync-workspace-reports":
        gate = verify_sync_workspace_report(args.directory, args.expected_directory)
        write_json(args.directory / "mysql-sync-workspace-gate.json", gate)
        print("Real MySQL sync workspace gate passed: collected test IDs matched; zero failures or skips.")
        return
    gate = verify_reports(args.directory, args.expected_directory)
    sales_gate = verify_sales_reports(args.directory, args.expected_directory)
    sync_workspace_gate = verify_sync_workspace_report(args.directory, args.expected_directory)
    backend_root = args.source_root or Path(__file__).resolve().parents[1]
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
