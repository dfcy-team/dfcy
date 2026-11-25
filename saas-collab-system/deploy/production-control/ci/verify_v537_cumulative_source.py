"""Read-only verification of the exact cumulative V537 source control."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

if not __debug__:
    raise RuntimeError("Optimized Python disables release gates")

EXPECTED_SOURCE = "4006bf530bfde783f54c4110773e8397aca3ec97"
EXPECTED_TREE = "4517d7df34e820ba0c96b9fb4e397c08e0cd56cd"
EXPECTED_PARENT = "081b87a0a6c2e153ae889b855e3aecbfd2e3ba20"
EXPECTED_MIGRATIONS = "855f9c19b9b0c89ec047facc3af4d99619a38f3f075ef141010c14a0dd18a88d"
IDENTITY_NAME = "v537-cumulative-source-identity.json"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuntimeError(reason)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE).decode().strip()


def blob(revision: str, path: str) -> bytes:
    oid = git("rev-parse", f"{revision}:{path}")
    return subprocess.check_output(["git", "cat-file", "blob", oid], stderr=subprocess.PIPE)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def decode_capture(capture: dict, label: str) -> bytes:
    encoded = capture["raw_base64"]
    require(isinstance(encoded, str) and encoded, f"{label} raw capture missing")
    raw = base64.b64decode(encoded, validate=True)
    require(digest(raw) == capture["artifact_sha256"], f"{label} capture SHA mismatch")
    return raw


identity_path = Path(__file__).with_name(IDENTITY_NAME)
require(identity_path.is_file(), "V537 source identity missing")
identity = json.loads(identity_path.read_text(encoding="utf-8"))

# Exact candidate, parent, and three-commit first-parent chain.
source = identity["source"]
require(source["sha"] == EXPECTED_SOURCE, "source SHA is not current V537 candidate")
require(source["tree_sha"] == EXPECTED_TREE, "source tree SHA mismatch")
require(source["parent_sha"] == EXPECTED_PARENT, "source parent SHA mismatch")
require(source["commit_count"] == 3 and len(source["commits"]) == 3, "expected three cumulative source commits")
require(source["pull_request"] == 642, "unexpected source pull request")
require(git("rev-parse", "HEAD") == source["sha"], "Git HEAD does not match source")
require(git("rev-parse", "HEAD^{tree}") == source["tree_sha"], "Git tree does not match source tree")
require(git("rev-parse", f"HEAD~{source['commit_count']}") == source["parent_sha"], "Git parent mismatch")
require(git("rev-list", "--count", source["parent_sha"] + "..HEAD") == "3", "Git source commit count mismatch")
commits = git("rev-list", "--reverse", "--first-parent", source["parent_sha"] + "..HEAD").splitlines()
require(commits == source["commits"], "Git source commit sequence mismatch")

# The control is bound to an explicitly selected deploy action on main.
for key in ("GITHUB_REPOSITORY", "GITHUB_REF", "GITHUB_SHA", "EXPECTED_CONTROL_SHA", "REQUESTED_ACTION", "REQUESTED_TRANSPORT"):
    require(bool(os.environ.get(key)), f"required control environment variable missing: {key}")
require(os.environ["GITHUB_REPOSITORY"] == "dfcy-team/dfcy", "unexpected control repository")
require(os.environ["GITHUB_REF"] == "refs/heads/main", "control must run on main")
require(re.fullmatch(r"[0-9a-f]{40}", os.environ["GITHUB_SHA"]) is not None, "invalid control SHA")
require(os.environ["EXPECTED_CONTROL_SHA"] == os.environ["GITHUB_SHA"], "control SHA binding mismatch")
require(os.environ["REQUESTED_ACTION"] == "deploy", "control action must be deploy")
require(os.environ["REQUESTED_TRANSPORT"] == "ssh", "control transport must be ssh")

# Exact file inventory and content hashes, including byte-identical menu files.
files = identity["files"]
require(isinstance(files, dict) and bool(files), "source file hash map missing")
changed = set(git("diff", "--name-only", source["parent_sha"], "HEAD").splitlines())
require(changed == set(files), "source changed-path inventory differs from identity")
for path, expected in files.items():
    require(digest(blob("HEAD", path)) == expected, f"source file SHA mismatch: {path}")

baseline = identity["baseline"]
require(baseline["sha256"] == "e682408c65d45700123a210f95cfbfe7b6bbb75ee1ea203d787f962f85b5175f", "independently approved V533 baseline mismatch")
require(re.fullmatch(r"[0-9a-f]{64}", baseline["sha256"]) is not None, "invalid approved baseline digest")
require(bool(os.environ.get("EXPECTED_BASELINE_SHA")) and baseline["sha256"] == os.environ["EXPECTED_BASELINE_SHA"], "baseline SHA environment binding mismatch")
require(baseline["source_sha"] == source["parent_sha"] and baseline["version"] == "2.44.533", "approved baseline source/version mismatch")
require((baseline["tables"], baseline["migration_nodes"]) == (423,541), "approved baseline counts mismatch")

protected_menu = identity["protected_menu_files"]
require(isinstance(protected_menu, dict) and bool(protected_menu), "protected menu hash map missing")
for path, expected in protected_menu.items():
    parent_bytes = blob(source["parent_sha"], path)
    head_bytes = blob("HEAD", path)
    require(parent_bytes == head_bytes, f"protected menu file changed: {path}")
    require(digest(parent_bytes) == expected, f"protected menu baseline SHA mismatch: {path}")

# Explicit registered warehouse label change; other navigation bytes remain fixed.
for path in identity["title_only_files"]:
    require(blob(source["parent_sha"], path).replace("仓库库存明细查询".encode(), "仓库库存明细".encode()) == blob("HEAD", path), "unapproved navigation/title change: " + path)

# Recompute the full canonical migration fingerprint and preserve every old migration.
migration = identity["migration"]
require(migration["canonical_sha256"] == EXPECTED_MIGRATIONS, "unexpected V537 canonical migration SHA")
migration_paths = sorted(p for p in git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    if "/backend/apps/" in p and "/migrations/" in p and p.endswith(".py"))
h = hashlib.sha256()
for path in migration_paths:
    h.update(path.split("/backend/", 1)[1].encode())
    h.update(blob("HEAD", path))
require(h.hexdigest() == migration["canonical_sha256"], "full migration fingerprint mismatch")
changed_migrations = {p for p in changed if "/migrations/" in p and p.endswith(".py")}
require(changed_migrations == set(migration["new_paths"]), "unexpected migration path delta")
parent_migrations = [p for p in git("ls-tree", "-r", "--name-only", source["parent_sha"]).splitlines()
    if "/backend/apps/" in p and "/migrations/" in p and p.endswith(".py")]
for path in parent_migrations:
    require(blob(source["parent_sha"], path) == blob("HEAD", path), f"historical migration changed: {path}")

# Actual wrapper stdout receipt is embedded in identity; verify its byte hash before parsing.
rehearsal_capture = identity["rehearsal"]
receipt_raw = decode_capture(rehearsal_capture, "rehearsal receipt")
require(digest(receipt_raw) == "8c20aa36dee5994603d89d25f8be54deb1aa5a3ea11b9a092229792be85c9904", "independently approved actual R4 checkpoint receipt mismatch")
receipt = json.loads(receipt_raw.decode("utf-8"))
require(receipt["status"] == "PASS", "remote wrapper did not pass")
require(receipt["source_sha"] == source["sha"], "wrapper source SHA mismatch")
require(receipt["backup_sha256"] == rehearsal_capture["backup_sha256"], "wrapper backup SHA mismatch")
require(receipt["source_archive_sha256"] == rehearsal_capture["source_archive_sha256"], "wrapper archive SHA mismatch")
require(receipt["backup_sha256"] == "0ea79035253ad45a96cf9c0ba00f7178f0b2bfdcd99abadc11fd7fccc3dc1b57", "approved rehearsal backup mismatch")
require(receipt["source_archive_sha256"] == "629c24508369c71c673ff7d65c41f9fe6625ab767e407cf2251316ba9ba5012e", "approved source archive mismatch")
require(receipt["cleanup_verified"] is True, "wrapper cleanup was not verified")
require(receipt["protected_state_unchanged"] is True, "protected release files changed")
require(receipt["production_app_unchanged"] is True, "production app container changed")
require(receipt["test_artifacts_retained"] is True, "test artifacts were not retained")
require(receipt["approved_checkpoint_sha256"] == baseline["sha256"], "wrapper checkpoint binding mismatch")
require(receipt["production_roles_unchanged"] is True and receipt["production_roles_verified"] == 14, "production role preservation mismatch")
checks = receipt["isolation_checks"]
require(checks["db_network"] == "none" and checks["probe_shares_db_network"] is True, "network isolation checks failed")

# The probe uses its real nested receipt schema; do not infer proof from wrapper status.
probe = receipt["probe_receipt"]
require(probe["checkpoint_sha256"] == baseline["sha256"] and probe["checkpoint_tables_verified"] == 420 and probe["checkpoint_rows_verified"] == 3552466 and probe["checkpoint_metadata_tables_verified"] == 3, "restored backup does not exactly match approved checkpoint")
require(baseline["protected_tables"] == 420 and baseline["protected_rows"] == 3552466, "approved checkpoint row scope mismatch")
require(probe["status"] == "PASS", "database probe failed")
require(probe["source_sha"] == source["sha"], "probe source SHA mismatch")
require(probe["source_tree"] == source["tree_sha"], "probe source tree mismatch")
require(probe["before"] == {"tables": 423, "nodes": 541}, "probe baseline counts mismatch")
require(probe["after"] == {"tables": 423, "nodes": 542, "new_tables": 0,
    "old_data_tables_hashed": 420, "schema_delta": 0, "second_plan_empty": True}, "probe after-state mismatch")
tests = probe["tests"]
require(tests["tests"] >= 1 and all(tests[key] == 0 for key in ("failures","errors","skipped")), "actual MySQL claim tests not clean")
require(probe["index_cases"] == {"matching_existing_accepted": True, "conflicting_definitions_rejected": 4, "invalid_prefix_rejected_by_mysql": True, "reverse_preserved": True}, "physical MySQL index cases missing")

# Pin the actual local validation record, preserving rather than embellishing its limits.
local_capture = identity["local_validation"]
local_raw = decode_capture(local_capture, "local validation")
require(digest(local_raw) == "d0355b2faab650f713748a8e6a722375a2b3b227cb69a6cc6f8f103778e2a5e6", "approved local validation byte mismatch")
local = json.loads(local_raw)
require(local["status"] == "PASS" and local["source_sha"] == source["sha"] and local["source_tree_sha"] == source["tree_sha"], "local validation source mismatch")
require(local["migration_sha256"] == migration["canonical_sha256"], "local migration fingerprint mismatch")

# Retain original test execution provenance only for a proven two-line test-only delta.
previous_raw = decode_capture(local["previous_validation"], "previous regression execution")
require(digest(previous_raw) == "50c6130fb229397f9ae65bafbb8fd11b25083699296cd2e7bbd9a602d2633ab1", "previous execution evidence changed")
previous = json.loads(previous_raw)
previous_source = "52a77af5741c03591189249051687d267ac73dae"
require(previous["source_sha"] == previous_source and git("rev-parse", "HEAD^") == previous_source, "previous execution source is not exact parent commit")
require(git("rev-parse", previous_source + "^{tree}") == previous["source_tree_sha"], "previous executed tree mismatch")
retained = local["retained_scope_provenance"]
expected_test_paths = {"saas-collab-system/backend/tests/test_production_build_only_contract.py", "saas-collab-system/backend/tests/test_production_build_only_history.py"}
require(set(git("diff", "--name-only", previous_source, "HEAD").splitlines()) == expected_test_paths == set(retained["changed_paths"]), "retained regression scope changed beyond two historical tests")
new_index_line = b'"apps/sales_management/migrations/0013_warehouse_lookup_requested_index.py",'
for path in expected_test_paths:
    lines = blob("HEAD", path).splitlines(keepends=True)
    additions = [line for line in lines if line.strip() == new_index_line]
    require(len(additions) == 1 and b"".join(line for line in lines if line != additions[0]) == blob(previous_source, path), "historical test fix differs from exact new-index exclusion: " + path)
require(git("rev-parse", "HEAD:saas-collab-system/frontend") == git("rev-parse", previous_source + ":saas-collab-system/frontend") == retained["unchanged_frontend_tree"], "retained frontend regression bytes changed")
require(retained["executed_source_sha"] == previous_source and retained["artifact_sha256"] == digest(previous_raw), "retained execution provenance missing")
for key in ("frontend_tests", "frontend_build", "backend_combined", "abc_basis_orm"):
    require(local[key] == previous[key], "retained test execution was relabeled: " + key)
    log_name = previous[key]["log"]
    require(local["log_sha256"][log_name] == previous["log_sha256"][log_name], "retained execution log changed: " + log_name)
require(local["historical_contract_fix"]["passed"] == 66 and local["historical_contract_fix"]["source_sha"] == source["sha"], "current historical exclusion regression missing")
fix = local["historical_contract_fix"]
require(fix["source_tree"] == source["tree_sha"] and fix["files"] == {path: files[path] for path in expected_test_paths}, "current historical regression files differ from frozen Git")
require(local["log_sha256"][fix["log"]] == fix["log_sha256"] and re.fullmatch(r"[0-9a-f]{64}", fix["log_sha256"]) is not None, "current historical regression log binding missing")

require(local["frontend_tests"]["passed"] == 2592 and local["frontend_tests"]["files"] == 348 and local["frontend_build"]["use_mock"] is False, "current frontend acceptance missing")
require(local["backend_combined"]["passed"] == 134 and local["backend_combined"]["skipped"] == 1 and local["abc_basis_orm"]["passed"] == 10, "current backend regressions missing")
require(local["custody_posix"]["passed"] == 15 and local["custody_concurrency"]["processes"] == 16 and local["custody_concurrency"]["late_write_rejections"] == 8, "custody POSIX/concurrency evidence missing")
image_validation_raw = decode_capture(local["current_image_validation"], "current exact-source image validation")
image_validation = json.loads(image_validation_raw)
require(image_validation["status"] == "PASS" and image_validation["source_sha"] == image_validation["oci_revision"] == source["sha"] and image_validation["source_tree"] == source["tree_sha"], "current image validation not actual source PASS")
require(image_validation["image_id"] == local["local_image"]["image_id"] and image_validation["image"] == local["local_image"]["ref"], "current image ID/ref mismatch")
require(image_validation["validations"] == {"posix_custody":"15 passed","process":"16 synthetic processes; one idempotent reference; 8 closed-operation rejections","tls":"PASS; CA/hostname verified; health 200; unauthenticated 401; late write rejected; network none","model_check":"PASS","makemigrations":"No changes detected","permission_manifest":"PASS"}, "current image bounded checks missing")
require(local["local_image"]["oci_revision"] == source["sha"], "custody image source mismatch")
require(local["backend_image_checks"] == {"model_check":"PASS","makemigrations":"No changes detected","permission_manifest":"PASS","network":"none","log":"backend-image537-r3-local-model-check.log"}, "new image checks missing")
tls = local["custody_tls"]["result"]
require(tls["status"] == "PASS" and tls["source_sha"] == source["sha"] and tls["workers"] == 2 and tls["network"] == "none" and tls["tls_ca_verified"] and tls["tls_hostname_verified"] and tls["late_store_rejected"], "actual new custody TLS proof missing")
require(local["actual_mysql_pending"] is False and local["actual_mysql_receipt_sha256"] == digest(receipt_raw) and local["VM_deployment_complete"] is False and len(local["limits"]) >= 4, "preserve actual MySQL binding and deferred production acceptance limits")
require(identity["production_acceptance"] is False, "identity must not claim production acceptance")

# GitHub reads only; credentials are never embedded or printed.
token = os.environ.get("GH_API_TOKEN")
require(bool(token), "GH_API_TOKEN is required")

def api(path: str):
    request = urllib.request.Request("https://api.github.com/repos/dfcy-team/dfcy/" + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

pr = api(f"pulls/{source['pull_request']}")
require(pr["head"]["sha"] == source["sha"], "PR head mismatch")
require(pr["base"]["ref"] == "release/v519-v533-vm" and pr["base"]["sha"] == source["parent_sha"], "PR base mismatch")
expected_jobs = {
    "phase2-ci.yml": {"Repository safety and file guard", "Django and pytest", "Frontend build observation gate", "Docker Compose configuration", "RPA samples and required documents"},
    "phase3-ci.yml": {"Repository safety and forbidden file guard", "Phase 3 Django, data quality, and pytest", "Frontend build without dependency lifecycle scripts", "Docker Compose placeholder configuration", "RPA samples and Phase 3 documents"},
}
ci_runs = identity["source_ci_runs"]
require(set(ci_runs) == set(expected_jobs), "exact Phase 2 and Phase 3 CI runs required")
verified = set()
for workflow, run_id in ci_runs.items():
    run = api(f"actions/runs/{run_id}")
    require(run["id"] == run_id and run["head_sha"] == source["sha"], "CI run source mismatch")
    require(run["path"] == ".github/workflows/" + workflow and run["event"] == "pull_request", "CI workflow/event mismatch")
    require(run["run_attempt"] == 1 and run["head_branch"] == pr["head"]["ref"], "CI is not first attempt on current PR head")
    require(run["status"] == "completed" and run["conclusion"] == "success", "source CI did not pass")
    jobs = api(f"actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    names = {job["name"] for job in jobs["jobs"]}
    require(jobs["total_count"] == len(jobs["jobs"]) == 5 and names == expected_jobs[workflow], "expected CI job names/count mismatch")
    require(not (names & verified), "duplicate CI job name across workflows")
    for job in jobs["jobs"]:
        require(job["run_id"] == run_id and job["run_attempt"] == 1 and job["head_sha"] == source["sha"], "CI job source/attempt mismatch")
        require(job["status"] == "completed" and job["conclusion"] == "success", "source CI job did not pass")
    verified.update(names)
require(verified == set.union(*expected_jobs.values()), "not all ten source CI jobs verified")

print("V537 exact source, MySQL receipt, protected history, and first-attempt PR CI verified")
