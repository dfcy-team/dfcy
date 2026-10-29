"""Offline verifier for the V330 production build-only artifact pair."""
import hashlib
import argparse
import json
import re
import sys

from pathlib import Path

IDENTITY = json.loads((Path(__file__).with_name("v330-release-identity.json")).read_text(encoding="utf-8"))
RELEASE = IDENTITY["source_sha"]
MIGRATION = IDENTITY["source_migration_sha256"]
BASELINE_MIGRATION = IDENTITY["baseline_migration_sha256"]
BASELINE = "8adf0a69a973146070c18c7450eefacc7f7f2829"
REDIS = "redis@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
RECEIPT_FALSE = ("vm_mutated", "cloud_mutated", "ledger_mutated",
                 "deployment_authorized_by_this_receipt", "compose_runtime_verified")


def valid_gate_evidence(receipt):
    mysql = receipt.get("mysql_gate")
    sales = receipt.get("mysql_sales_gate")
    sync = receipt.get("mysql_sync_workspace_gate")
    if (not isinstance(mysql, dict) or mysql.get("status") != "PASS_REAL_MYSQL_CURRENT_MODEL_SCHEMA"
            or mysql.get("mysql") != "8.4.11" or mysql.get("django") != "5.2.17"
            or mysql.get("production_database_used") is not False
            or mysql.get("fresh_mysql_migration_validation") is not False):
        return False
    suites = mysql.get("suites")
    expected = {"lock-scope": 9, "related-regression": 160, "preflight-rejection": 6}
    if not isinstance(suites, dict) or set(suites) != set(expected):
        return False
    if any(not isinstance(suites[name], dict) or suites[name].get("passed") != count
           or suites[name].get("failed") != 0 or suites[name].get("skipped") != 0
           for name, count in expected.items()):
        return False
    if (not isinstance(sales, dict) or sales.get("status") != "PASS_REAL_MYSQL_SALES_CURRENT_MODEL_SCHEMA"
            or sales.get("testcases") != 91 or sales.get("failed") != 0 or sales.get("skipped") != 0
            or sales.get("mysql") != "8.4.11" or sales.get("django") != "5.2.17"
            or sales.get("production_database_used") is not False):
        return False
    index = sales.get("index_migration")
    if (not isinstance(index, dict) or index.get("status") != "pass"
            or index.get("migration") != "commerce.0006_salesorder_currency_catalog_idx"
            or index.get("index") != "idx_sales_order_currency"
            or index.get("columns") != ["tenant_id", "currency"]
            or index.get("forward_and_reverse_checked") is not True
            or index.get("rows_unchanged") is not True
            or index.get("production_database_used") is not False
            or index.get("fresh_migration_chain_validated") is not False):
        return False
    return (isinstance(sync, dict)
            and sync.get("status") == "PASS_REAL_MYSQL_SYNC_WORKSPACE_CURRENT_MODEL_SCHEMA"
            and sync.get("testcases") == 195 and sync.get("failed") == 0
            and sync.get("skipped") == 0 and sync.get("production_database_used") is False
            and sync.get("mysql") == "8.4.11" and sync.get("django") == "5.2.17")


def verify(manifest_bytes, receipt_bytes, run_id, attempt="1"):
    """Validate raw artifact bytes and return their hashes; fail closed on drift."""
    m, r = json.loads(manifest_bytes), json.loads(receipt_bytes)
    if set(m) != {"schema_version", "environment", "repository", "git_sha", "release_sha",
                  "backend_image", "frontend_image", "redis_image", "migration_sha256", "compose_sha256"}:
        raise ValueError("manifest schema mismatch")
    if (MIGRATION == BASELINE_MIGRATION or m["schema_version"] != 1 or m["environment"] != "production"
            or m["repository"] != "dfcy-team/dfcy" or m["git_sha"] != RELEASE
            or m["release_sha"] != RELEASE or m["migration_sha256"] != MIGRATION
            or m["compose_sha256"] != "owner-controlled-on-target" or m["redis_image"] != REDIS):
        raise ValueError("manifest V330 provenance mismatch")
    for key in ("backend", "frontend"):
        if not re.fullmatch(r"ghcr\.io/dfcy-team/dfcy/saas-collab-" + key + r"@sha256:[0-9a-f]{64}", m[key + "_image"]):
            raise ValueError("manifest image invalid")
    mh, rh = hashlib.sha256(manifest_bytes).hexdigest(), hashlib.sha256(receipt_bytes).hexdigest()
    required = {"schema_version", "status", "baseline_git_sha", "git_sha", "manifest_sha256",
                "workflow_run_id", "workflow_run_attempt", "mysql_gate", "mysql_sales_gate",
                "mysql_sync_workspace_gate", *RECEIPT_FALSE}
    if set(r) != required or r["schema_version"] != 1 or r["status"] != "BUILT_NOT_DEPLOYED":
        raise ValueError("receipt schema/status mismatch")
    if not valid_gate_evidence(r):
        raise ValueError("receipt MySQL gate evidence mismatch")
    if (r["baseline_git_sha"] != BASELINE or str(r["workflow_run_id"]) != str(run_id) or str(r["workflow_run_attempt"]) != str(attempt)
            or r["git_sha"] != RELEASE or r["manifest_sha256"] != mh
            or any(r[k] is not False for k in RECEIPT_FALSE)):
        raise ValueError("receipt provenance mismatch")
    return {"manifest_sha256": mh, "receipt_sha256": rh}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", default="1")
    args = parser.parse_args()
    try:
        result = verify(open(args.manifest, "rb").read(), open(args.receipt, "rb").read(), args.run_id, args.attempt)
        print(json.dumps(result, separators=(",", ":")))
    except (ValueError, OSError, json.JSONDecodeError, KeyError, TypeError):
        print("Fixed batch artifact validation failed.", file=sys.stderr)
        raise SystemExit(1)
