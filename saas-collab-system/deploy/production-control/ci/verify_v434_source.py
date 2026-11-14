"""Verify the frozen V434 source, its exact linear ancestry, and required CI checks."""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

CI = Path(__file__).with_name("v434-source-identity.json")
identity = json.loads(CI.read_text(encoding="utf-8"))
assert identity["source_sha"] == "43b484dc0c94f5bc39335070a057e2612dc2cd82"
assert identity["parent_sha"] == "04d25c53034e60968d33b3e66253223b5b436339"
assert identity["pull_request"] == 567 and identity["version"] == "2.44.434"
assert identity["source_commit_count"] == 2
assert len(identity["source_commits"]) == 2


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
assert git("rev-parse", "HEAD~2") == identity["parent_sha"]
assert git("rev-list", "--count", identity["parent_sha"] + "..HEAD") == "2"
assert git("rev-list", "--reverse", "--first-parent", identity["parent_sha"] + "..HEAD").splitlines() == identity["source_commits"]
changed = set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines())
assert changed == set(identity["files"])
assert len(changed) == 8
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
assert identity["migration_sha256"] == "6d7996619422dd11ca952d8162c5b13e27ea4e683df809901ef07d95a53a9d4a"
added_migrations = {path for path in changed if "/migrations/" in path}
assert not added_migrations
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
assert pr["base"]["ref"] == "release/v420-v432-vm" and pr["base"]["sha"] == identity["parent_sha"]
assert pr["base"]["repo"]["full_name"] == "dfcy-team/dfcy"
assert identity["source_ci_runs"] == {'phase2-ci.yml': 43579223164, 'phase3-ci.yml': 43579223167}
verified = set()
for workflow, run_id in identity["source_ci_runs"].items():
    run = api(f"actions/runs/{run_id}")
    assert run["id"] == run_id and run["head_sha"] == identity["source_sha"]
    assert run["path"] == ".github/workflows/" + workflow
    assert run["event"] == "pull_request" and run["run_attempt"] == 1
    assert run["head_branch"] == "release/v433-v434-vm"
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
print("V434 frozen source, PR head, full migration fingerprint, and ten exact authorized CI jobs verified")
