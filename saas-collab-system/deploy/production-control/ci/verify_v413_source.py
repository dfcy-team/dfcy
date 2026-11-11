"""Verify the frozen V413 source, its exact linear ancestry, and required CI checks."""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

CI = Path(__file__).with_name("v413-source-identity.json")
identity = json.loads(CI.read_text(encoding="utf-8"))
assert identity["source_sha"] == "756fc2c4f60054aea45896e185fc81747304a9bf"
assert identity["parent_sha"] == "7b4115fa9ff9a9ef6decf820e677f5daefc2bb1f"
assert identity["pull_request"] == 559 and identity["version"] == "2.44.413"
assert identity["source_commit_count"] == 9
assert len(identity["source_commits"]) == 9


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
assert git("rev-parse", "HEAD~9") == identity["parent_sha"]
assert git("rev-list", "--count", identity["parent_sha"] + "..HEAD") == "9"
assert git("rev-list", "--reverse", "--first-parent", identity["parent_sha"] + "..HEAD").splitlines() == identity["source_commits"]
changed = set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines())
assert changed == set(identity["files"])
assert len(changed) == 40
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
assert identity["migration_sha256"] == "9e00dac6b4605af6fd95d3385702f8b1f1dbbfdfb2f4520eacc25e4897cb57c5"
added_migrations = {path for path in changed if "/migrations/" in path}
assert added_migrations == {
    'saas-collab-system/backend/apps/supply_chain/migrations/0062_inbound_notification.py',
    'saas-collab-system/backend/apps/supply_chain/migrations/0067_merge_payment_plans_inbound_notification.py',
}
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
assert pr["base"]["ref"] == "main"
assert pr["base"]["repo"]["full_name"] == "dfcy-team/dfcy"
assert identity["source_ci_runs"] == {'phase2-ci.yml': 42975435327, 'phase3-ci.yml': 42975441708}
verified = set()
for workflow, run_id in identity["source_ci_runs"].items():
    run = api(f"actions/runs/{run_id}")
    assert run["id"] == run_id and run["head_sha"] == identity["source_sha"]
    assert run["path"] == ".github/workflows/" + workflow
    assert run["event"] == "workflow_dispatch" and run["run_attempt"] == 1
    assert run["head_branch"] == "release/v411-v413-vm"
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
print("V413 frozen source, PR head, full migration fingerprint, and ten exact authorized CI jobs verified")
