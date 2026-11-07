"""Verify the frozen V392 source, its exact linear ancestry, and required CI checks."""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

CI = Path(__file__).with_name("v392-source-identity.json")
identity = json.loads(CI.read_text(encoding="utf-8"))
assert identity["source_sha"] == "701c623c72f936e95467c21abc2f3f671004e16a"
assert identity["parent_sha"] == "53cb7f3030f34e18d6d9e00eb4d35f17a985c1d4"
assert identity["pull_request"] == 528 and identity["version"] == "2.44.392"
assert identity["source_commit_count"] == 2
assert identity["source_commits"] == [
    "8798b2d8909caac4b4e188d98b246c8b5da57b0e",
    "701c623c72f936e95467c21abc2f3f671004e16a",
]


def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()


def blob(path):
    object_id = git("rev-parse", f"{identity['source_sha']}:{path}")
    return subprocess.check_output(["git", "cat-file", "blob", object_id])


assert os.environ["GITHUB_REPOSITORY"] == "dfcy-team/dfcy"
assert os.environ["GITHUB_REF"] == "refs/heads/main"
assert os.environ["REQUESTED_ACTION"] == "deploy"
assert os.environ["REQUESTED_TRANSPORT"] == "ssh"
assert git("rev-parse", "HEAD") == identity["source_sha"]
assert git("rev-parse", "HEAD~2") == identity["parent_sha"]
assert git("rev-list", "--count", identity["parent_sha"] + "..HEAD") == "2"
assert [git("rev-parse", f"HEAD~{n}") for n in (1, 0)] == identity["source_commits"]
changed = set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines())
assert changed == set(identity["files"])
assert len(changed) == 3
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
assert identity["migration_sha256"] == "e162017f18188b443c5a1c9a340345285157ffd3b623c1981b35a56703d4a318"
added_migrations = {path for path in changed if "/migrations/" in path}
assert not added_migrations

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
print("V392 frozen source, PR head, full migration fingerprint, and ten exact-source CI checks verified")
