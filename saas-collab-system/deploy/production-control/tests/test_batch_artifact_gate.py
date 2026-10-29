import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("batch_artifact_gate", ROOT / "ci/batch_artifact_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
WORKFLOW = (ROOT.parents[2] / ".github/workflows/developer-a-production-release.yml").read_text(encoding="utf-8")


def artifacts():
    m = {"schema_version": 1, "environment": "production", "repository": "dfcy-team/dfcy",
         "git_sha": gate.RELEASE, "release_sha": gate.RELEASE,
         "backend_image": "ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:" + "1" * 64,
         "frontend_image": "ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:" + "2" * 64,
         "redis_image": gate.REDIS, "migration_sha256": gate.MIGRATION,
         "compose_sha256": "owner-controlled-on-target"}
    mb = (json.dumps(m, indent=2) + "\n").encode()
    r = {"schema_version": 1, "status": "BUILT_NOT_DEPLOYED", "baseline_git_sha": gate.BASELINE,
         "git_sha": gate.RELEASE, "manifest_sha256": __import__("hashlib").sha256(mb).hexdigest(),
         "workflow_run_id": "317", "workflow_run_attempt": "1",
         "mysql_gate": {"status": "PASS_REAL_MYSQL_CURRENT_MODEL_SCHEMA", "suites": {
             "lock-scope": {"passed": 9, "failed": 0, "skipped": 0},
             "related-regression": {"passed": 160, "failed": 0, "skipped": 0},
             "preflight-rejection": {"passed": 6, "failed": 0, "skipped": 0}},
             "mysql": "8.4.11", "django": "5.2.17", "production_database_used": False,
             "fresh_mysql_migration_validation": False},
         "mysql_sales_gate": {"status": "PASS_REAL_MYSQL_SALES_CURRENT_MODEL_SCHEMA", "testcases": 91,
             "failed": 0, "skipped": 0, "index_migration": {"status": "pass",
             "migration": "commerce.0006_salesorder_currency_catalog_idx", "index": "idx_sales_order_currency",
             "columns": ["tenant_id", "currency"], "forward_and_reverse_checked": True,
             "rows_unchanged": True, "production_database_used": False,
             "fresh_migration_chain_validated": False}, "mysql": "8.4.11", "django": "5.2.17",
             "production_database_used": False},
         "mysql_sync_workspace_gate": {"status": "PASS_REAL_MYSQL_SYNC_WORKSPACE_CURRENT_MODEL_SCHEMA",
             "testcases": 195, "failed": 0, "skipped": 0, "production_database_used": False,
             "mysql": "8.4.11", "django": "5.2.17"},
         **{k: False for k in gate.RECEIPT_FALSE}}
    return mb, (json.dumps(r, indent=2) + "\n").encode()


def test_build_only_production_artifact_pair_passes_raw_byte_verification():
    m, r = artifacts()
    assert gate.verify(m, r, "317") == {
        "manifest_sha256": __import__("hashlib").sha256(m).hexdigest(),
        "receipt_sha256": __import__("hashlib").sha256(r).hexdigest()}


def test_wrong_run_or_mutated_receipt_is_rejected():
    m, r = artifacts()
    for run, body in [("318", r), ("317", r.replace(b'"vm_mutated": false', b'"vm_mutated": true'))]:
        try:
            gate.verify(m, body, run)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid artifact accepted")


def test_missing_or_failed_mysql_gates_are_rejected():
    m, raw = artifacts()
    receipt = json.loads(raw)
    receipt["mysql_gate"] = {}
    broken = json.dumps(receipt).encode()
    try:
        gate.verify(m, broken, "317")
    except ValueError:
        pass
    else:
        raise AssertionError("receipt with missing test evidence accepted")


def test_v330_workflow_has_disjoint_nobuild_stages_and_exact_evidence_binding():
    assert "name: Preflight exact V330 build-only artifacts (no deployment)" in WORKFLOW
    assert "name: Deploy same verified V330 manifest without rebuilding" in WORKFLOW
    assert "production-artifacts-build-only.yml" in WORKFLOW
    assert "production-v330-preflight-proof-${{ github.run_id }}" in WORKFLOW
    assert "--receipt-sha256=" in WORKFLOW and "--manifest-sha256=" in WORKFLOW
    assert "--registry-token-stdin" in WORKFLOW
    assert "steps.bind.outputs.backend_image" in WORKFLOW
    assert "preflight_run_id" in WORKFLOW
    assert "v330-release-identity.json" in WORKFLOW
    assert "vars.V330_APPROVED_BUILD_CONTROLLER_SHA" in WORKFLOW
    assert not re.search(r"continue-on-error:\s*true", WORKFLOW)


def test_v330_source_digest_is_distinct_from_v315_baseline_digest():
    assert gate.MIGRATION == "696734a0a1ade1064cc9519018e51223c658d8db13f71154e97498fadb55a740"
    assert gate.BASELINE_MIGRATION == "7628bb3e116b30baa7e61d2b1df75367d77fe452773778b4dde3f6476586deb3"
    assert gate.MIGRATION != gate.BASELINE_MIGRATION
