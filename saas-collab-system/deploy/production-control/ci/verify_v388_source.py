"""Verify the frozen V388 source and its exact ten required CI checks."""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

identity = json.loads(Path(__file__).with_name("v388-source-identity.json").read_text(encoding="utf-8"))
assert identity["source_sha"] == "7c8e5b0b06d77c84b3032e3eaffae6d8d4a42f33"
assert identity["parent_sha"] == "23031cd05a99534d04f7c4f9c287f38c4d3975c6"
assert identity["pull_request"] == 518 and identity["version"] == "2.44.388"
assert identity["source_commit_count"] == 8

def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()

def blob(path):
    return subprocess.check_output(["git", "cat-file", "blob", f"{identity['source_sha']}:{path}"])

assert os.environ["GITHUB_REPOSITORY"] == "dfcy-team/dfcy"
assert os.environ["GITHUB_REF"] == "refs/heads/main"
assert os.environ["REQUESTED_ACTION"] == "deploy"
assert os.environ["REQUESTED_TRANSPORT"] == "ssh"
assert git("rev-parse", "HEAD") == identity["source_sha"]
assert git("rev-parse", "HEAD~" + str(identity["source_commit_count"])) == identity["parent_sha"]
assert git("rev-list", "--count", identity["parent_sha"] + "..HEAD") == str(identity["source_commit_count"])
changed = set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines())
assert changed == set(identity["files"])
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
added_migrations = {path for path in changed if "/migrations/" in path}
expected_migrations = set(identity["migration_paths"]["already_applied"] + identity["migration_paths"]["pending"])
assert added_migrations == expected_migrations
assert not any("/migrations/" in path for path in changed - expected_migrations)

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

pr = api("pulls/" + str(identity["pull_request"]))
assert pr["head"]["sha"] == identity["source_sha"]
assert pr["head"]["repo"]["full_name"] == "dfcy-team/dfcy"
assert pr["base"]["ref"] == "main"
assert pr["base"]["repo"]["full_name"] == "dfcy-team/dfcy"
checks = api("commits/" + identity["source_sha"] + "/check-runs?per_page=100")
latest = {}
for check in sorted(checks["check_runs"], key=lambda item: item["id"]):
    if check["name"] in required:
        latest[check["name"]] = check
assert set(latest) == required
assert all(check["status"] == "completed" and check["conclusion"] == "success"
           and check["head_sha"] == identity["source_sha"] for check in latest.values())
print("V388 frozen source, PR head, and ten exact-source CI checks verified")
