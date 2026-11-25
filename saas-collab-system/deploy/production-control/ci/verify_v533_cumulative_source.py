"""Read-only verification of the exact cumulative V533 source control."""
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

EXPECTED_SOURCE = "081b87a0a6c2e153ae889b855e3aecbfd2e3ba20"
EXPECTED_TREE = "192b90a01d360178e6d005e2f569db316d0f10cd"
EXPECTED_PARENT = "9728c548cce4c21d9cbc99aea7407298b4056fc7"
EXPECTED_MIGRATIONS = "7aa23366d74fa436a3144284dc72f0452771c40a0e14b438f219f1dfcd6f5c30"
IDENTITY_NAME = "v533-cumulative-source-identity.json"


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
require(identity_path.is_file(), "V533 source identity missing")
identity = json.loads(identity_path.read_text(encoding="utf-8"))

# Exact candidate, parent, and five-commit first-parent chain.
source = identity["source"]
require(source["sha"] == EXPECTED_SOURCE, "source SHA is not current V533 candidate")
require(source["tree_sha"] == EXPECTED_TREE, "source tree SHA mismatch")
require(source["parent_sha"] == EXPECTED_PARENT, "source parent SHA mismatch")
require(source["commit_count"] == 5 and len(source["commits"]) == 5, "expected five cumulative source commits")
require(source["pull_request"] == 637, "unexpected source pull request")
require(git("rev-parse", "HEAD") == source["sha"], "Git HEAD does not match source")
require(git("rev-parse", "HEAD^{tree}") == source["tree_sha"], "Git tree does not match source tree")
require(git("rev-parse", f"HEAD~{source['commit_count']}") == source["parent_sha"], "Git parent mismatch")
require(git("rev-list", "--count", source["parent_sha"] + "..HEAD") == "5", "Git source commit count mismatch")
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
require(baseline["sha256"] == "0c22a7a6d640e8ce420357aa81b5867dfae03c3e6a848c946ae6d3ea2305c86f", "independently approved V518 baseline mismatch")
require(re.fullmatch(r"[0-9a-f]{64}", baseline["sha256"]) is not None, "invalid approved baseline digest")
require(bool(os.environ.get("EXPECTED_BASELINE_SHA")) and baseline["sha256"] == os.environ["EXPECTED_BASELINE_SHA"], "baseline SHA environment binding mismatch")
require(baseline["source_sha"] == source["parent_sha"] and baseline["version"] == "2.44.518", "approved baseline source/version mismatch")
require((baseline["tables"], baseline["migration_nodes"]) == (415,531), "approved baseline counts mismatch")

protected_menu = identity["protected_menu_files"]
require(isinstance(protected_menu, dict) and bool(protected_menu), "protected menu hash map missing")
for path, expected in protected_menu.items():
    parent_bytes = blob(source["parent_sha"], path)
    head_bytes = blob("HEAD", path)
    require(parent_bytes == head_bytes, f"protected menu file changed: {path}")
    require(digest(parent_bytes) == expected, f"protected menu baseline SHA mismatch: {path}")

# Recompute the full canonical migration fingerprint and preserve every old migration.
migration = identity["migration"]
require(migration["canonical_sha256"] == EXPECTED_MIGRATIONS, "unexpected V533 canonical migration SHA")
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
require(digest(receipt_raw) == "442c1fba8a846fc375606760d623f50c5b544814a5c6ebd2e6b4d1f20c7d4195", "independently approved actual R4 checkpoint receipt mismatch")
receipt = json.loads(receipt_raw.decode("utf-8"))
require(receipt["status"] == "PASS", "remote wrapper did not pass")
require(receipt["source_sha"] == source["sha"], "wrapper source SHA mismatch")
require(receipt["backup_sha256"] == rehearsal_capture["backup_sha256"], "wrapper backup SHA mismatch")
require(receipt["source_archive_sha256"] == rehearsal_capture["source_archive_sha256"], "wrapper archive SHA mismatch")
require(receipt["backup_sha256"] == "36d4fc017dd48b70740ec9fb5440b6e0a89c5d479c0d0fa99040ccb905d319cf", "approved rehearsal backup mismatch")
require(receipt["source_archive_sha256"] == "611cef0e5d76c9e15111bbff375c03bfa50a0f9940287afc1c2ffceaacdd8fb2", "approved source archive mismatch")
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
require(probe["checkpoint_sha256"] == baseline["sha256"] and probe["checkpoint_tables_verified"] == 412 and probe["checkpoint_rows_verified"] == 3552466 and probe["checkpoint_metadata_tables_verified"] == 3, "restored backup does not exactly match approved checkpoint")
require(baseline["protected_tables"] == 412 and baseline["protected_rows"] == 3552466, "approved checkpoint row scope mismatch")
require(probe["status"] == "PASS", "database probe failed")
require(probe["source_sha"] == source["sha"], "probe source SHA mismatch")
require(probe["source_tree"] == source["tree_sha"], "probe source tree mismatch")
require(probe["before"] == {"tables": 415, "nodes": 531}, "probe baseline counts mismatch")
require(probe["after"] == {"tables": 423, "nodes": 541, "new_tables": 8,
    "old_data_tables_hashed": 412, "schema_delta": 9, "second_plan_empty": True}, "probe after-state mismatch")
tests = probe["tests"]
require(tests == {"tests": 17, "failures": 0, "errors": 0, "skipped": 0}, "probe tests not clean")

# Pin the actual local validation record, preserving rather than embellishing its limits.
local_capture = identity["local_validation"]
local_raw = decode_capture(local_capture, "local validation")
require(hashlib.sha256(local_raw).hexdigest() == "d06ccba8960cecf7630022dca2388627fcc7926f35373520eb871986cd808253", "independently approved local validation bytes mismatch")
local = json.loads(local_raw.decode("utf-8"))
require(local["status"] == "PASS_LOCAL_TARGETED_FULL_CI_REQUIRED", "local validation status mismatch")
require(local["source_sha"] == source["sha"] and local["source_tree_sha"] == source["tree_sha"], "local validation source binding mismatch")
require(local["canonical_migration_sha256"] == migration["canonical_sha256"], "local validation migration binding mismatch")
require(local["production_deployment"] is False and local["actual_mysql_rehearsal"] == "PENDING_NEW_SOURCE", "local validation must remain labeled pre-rehearsal")
require(local["backend_tests"]["financial_modules_passed"] == 48 and local["backend_tests"]["compatibility_modules_passed"] == 87 and local["backend_tests"]["strengthened_graph_archive_followup_passed"] == 4 and local["backend_tests"]["skipped"] == 0, "current local targeted test evidence mismatch")
require(local["historical_composite"]["current_revision_claim"] is False, "historical tests cannot be relabeled as current")
require(local["docker_backend"]["source_label"] == source["sha"] and local["docker_backend"]["context"] == "exact_git_archive_canonical_lf" and local["docker_backend"]["network"] == "none", "actual current backend Docker proof mismatch")
require(local["docker_backend"]["model_check"] == "PASS" and local["docker_backend"]["makemigrations"] == "No changes detected" and local["docker_backend"]["permission_manifest"] == "PASS", "current backend model/manifest checks missing")
require(local["frontend_inputs_unchanged_from_r4"] is True and len(local["limits"])>=5, "local scope limitations missing")
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
require(pr["base"]["ref"] == "release/v491-v517-vm" and pr["base"]["sha"] == source["parent_sha"], "PR base mismatch")
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

print("V533 exact source, MySQL receipt, protected history, and first-attempt PR CI verified")
