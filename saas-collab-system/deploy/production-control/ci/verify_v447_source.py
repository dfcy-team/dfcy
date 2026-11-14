"""Verify the frozen V447 source, its exact linear ancestry, and required CI checks."""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

CI = Path(__file__).with_name("v447-source-identity.json")
identity = json.loads(CI.read_text(encoding="utf-8"))
assert identity["source_sha"] == "0a677d00f468ad28d482f298615753dbc170799f"
assert identity["parent_sha"] == "43b484dc0c94f5bc39335070a057e2612dc2cd82"
assert identity["pull_request"] == 580 and identity["version"] == "2.44.447"
assert identity["source_commit_count"] == 4
assert len(identity["source_commits"]) == 4


def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()


def blob(path):
    object_id = git("rev-parse", f"{identity['source_sha']}:{path}")
    return subprocess.check_output(["git", "cat-file", "blob", object_id])


assert os.environ["GITHUB_REPOSITORY"] == "dfcy-team/dfcy"
assert os.environ["GITHUB_REF"] == "refs/heads/main"
assert len(os.environ["EXPECTED_CONTROL_SHA"]) == 40 and os.environ["EXPECTED_CONTROL_SHA"] == os.environ["GITHUB_SHA"], "controller changed between authorization and dispatch"
assert os.environ["REQUESTED_ACTION"] == "deploy"
assert os.environ["REQUESTED_TRANSPORT"] == "ssh"
assert git("rev-parse", "HEAD") == identity["source_sha"]
assert git("rev-parse", "HEAD~4") == identity["parent_sha"]
assert git("rev-list", "--count", identity["parent_sha"] + "..HEAD") == "4"
assert git("rev-list", "--reverse", "--first-parent", identity["parent_sha"] + "..HEAD").splitlines() == identity["source_commits"]
rehearsal = identity["migration_rehearsal"]
assert rehearsal["status"] == "PASS" and rehearsal["network"] == "none"
assert rehearsal["source_sha"] == identity["source_sha"] and rehearsal["parent_sha"] == identity["parent_sha"]
assert rehearsal["source_tree_sha"] == git("rev-parse", "HEAD^{tree}")
assert rehearsal["migration_sha256"] == identity["migration_sha256"]
assert (rehearsal["tables_before"], rehearsal["tables_after"]) == (384, 403)
assert (rehearsal["before_nodes"], rehearsal["after_nodes"]) == (490, 506)
assert rehearsal["old_columns_unchanged"] is True and rehearsal["second_migrate_idempotent"] is True
assert rehearsal["protected_tables"] == 157 and rehearsal["protected_rows"] > 0
assert len(rehearsal["new_table_rows"]) == 19 and not any(rehearsal["new_table_rows"].values())
assert sorted(".".join(node) for node in rehearsal["exact_added_nodes"]) == sorted(identity["expected_pending_migrations"])
for key in ("backup_sha256", "receipt_sha256", "applied_nodes_sha256"):
    assert len(rehearsal[key]) == 64 and all(ch in "0123456789abcdef" for ch in rehearsal[key])
changed = set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines())
assert changed == set(identity["files"])
assert len(changed) == 197
for path, digest in identity["files"].items():
    assert hashlib.sha256(blob(path)).hexdigest() == digest, path

migration_paths = sorted(
    path for path in git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    if "/backend/apps/" in path and "/migrations/" in path and path.endswith(".py")
)
migrations = hashlib.sha256()
for path in migration_paths:
    migrations.update(path.split("/backend/", 1)[1].encode())
    migrations.update(blob(path))
assert migrations.hexdigest() == identity["migration_sha256"]
assert identity["migration_sha256"] == "db6b8588efa9d23955e9d055f247353a8e2c5acf1c081b4ec6289d847dd9a120"
added_migrations = {path for path in changed if "/migrations/" in path}
assert added_migrations == set(['saas-collab-system/backend/apps/finance/migrations/0015_warehouse_bill_format_rule.py', 'saas-collab-system/backend/apps/flash_sales/migrations/0001_initial.py', 'saas-collab-system/backend/apps/flash_sales/migrations/0002_permissions.py', 'saas-collab-system/backend/apps/flash_sales/migrations/0003_dispatch_watermark.py', 'saas-collab-system/backend/apps/flash_sales/migrations/0004_slot_reservation_history.py', 'saas-collab-system/backend/apps/flash_sales/migrations/0005_plan_deleted_at.py', 'saas-collab-system/backend/apps/flash_sales/migrations/__init__.py', 'saas-collab-system/backend/apps/integrations/migrations/0059_developer_warehouse_account.py', 'saas-collab-system/backend/apps/integrations/migrations/0060_best_ecapi_platform.py', 'saas-collab-system/backend/apps/integrations/migrations/0061_best_platform_master.py', 'saas-collab-system/backend/apps/integrations/migrations/0062_merge_warehouse_gmv_branches.py', 'saas-collab-system/backend/apps/integrations/migrations/0065_merge_warehouse_native_collection.py', 'saas-collab-system/backend/apps/masterdata/migrations/0023_platform_connector_fields.py', 'saas-collab-system/backend/apps/masterdata/migrations/0024_backfill_platform_connectors.py', 'saas-collab-system/backend/apps/sales_management/migrations/0008_order_warehouse_lookup.py', 'saas-collab-system/backend/apps/sales_management/migrations/0009_order_warehouse_schedule.py', 'saas-collab-system/backend/apps/sales_management/migrations/0010_aftersales_warehouse_return_no.py'])
assert all(git("diff", "--diff-filter=A", "--name-only", identity["parent_sha"], "HEAD", "--", p) == p for p in added_migrations)

required = {
    "Repository safety and file guard", "Django and pytest",
    "Frontend build observation gate", "Docker Compose configuration",
    "RPA samples and required documents", "Repository safety and forbidden file guard",
    "Phase 3 Django, data quality, and pytest",
    "Frontend build without dependency lifecycle scripts",
    "Docker Compose placeholder configuration", "RPA samples and Phase 3 documents",
}


def api(path):
    request = urllib.request.Request(
        "https://api.github.com/repos/dfcy-team/dfcy/" + path,
        headers={"Authorization": "Bearer " + os.environ["GH_API_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


assert identity['release_generation']=='r1'
assert len(identity['baseline_file_sha256'])==64 and identity['baseline_file_sha256']==os.environ['EXPECTED_BASELINE_SHA']

pr = api("pulls/" + str(identity["pull_request"]))
assert pr["head"]["sha"] == identity["source_sha"]
assert pr["head"]["repo"]["full_name"] == "dfcy-team/dfcy"
assert pr["base"]["ref"] == "release/v433-v434-vm" and pr["base"]["sha"] == identity["parent_sha"]
assert pr["base"]["repo"]["full_name"] == "dfcy-team/dfcy"
assert identity["source_ci_runs"] == {'phase2-ci.yml': 43615273203, 'phase3-ci.yml': 43615273174}
verified = set()
for workflow, run_id in identity["source_ci_runs"].items():
    run = api(f"actions/runs/{run_id}")
    assert run["id"] == run_id and run["head_sha"] == identity["source_sha"]
    assert run["path"] == ".github/workflows/" + workflow
    assert run["event"] == "pull_request" and run["run_attempt"] == 1
    assert run["head_branch"] == "release/v435-v447-vm"
    assert run["status"] == "completed" and run["conclusion"] == "success"
    jobs = api(f"actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    assert jobs["total_count"] == len(jobs["jobs"]) == 5
    names = {job["name"] for job in jobs["jobs"]}
    assert len(names) == 5 and names <= required and not names & verified
    assert all(job["run_id"] == run_id and job["run_attempt"] == 1 and job["head_sha"] == identity["source_sha"]
               and job["status"] == "completed" and job["conclusion"] == "success"
               for job in jobs["jobs"])
    verified |= names
assert verified == required
print("V447 frozen source, PR head, full migration fingerprint, and ten exact authorized CI jobs verified")
