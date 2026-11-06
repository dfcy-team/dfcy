"""Verify the frozen V391 source, its exact linear ancestry, and required CI checks."""
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

identity = json.loads(Path(__file__).with_name("v391-source-identity.json").read_text(encoding="utf-8"))
assert identity["source_sha"] == "a0c83685394f5b6db0eafe15a5ddf32ddbef2c84"
assert identity["parent_sha"] == "d31be33b0cf34988bd574756913d4c9644d8dfd5"
assert identity["pull_request"] == 523 and identity["version"] == "2.44.391"
assert identity["source_commit_count"] == 4
assert identity["source_commits"] == [
    "0777910a6d34d1027af0f91b001b09b2d713ec9c",
    "67fcf53e0c29c91bb39038512db2f21b6dd7864e",
    "d3ed24cf220d5f285a44d9652497691d2de31eb2",
    "a0c83685394f5b6db0eafe15a5ddf32ddbef2c84",
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
assert git("rev-parse", "HEAD~4") == identity["parent_sha"]
assert git("rev-list", "--count", identity["parent_sha"] + "..HEAD") == "4"
assert [git("rev-parse", "HEAD~" + str(n)) for n in (3, 2, 1, 0)] == identity["source_commits"]
changed = set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines())
assert changed == set(identity["files"])
assert len(changed) == 14
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
assert expected_migrations == {"saas-collab-system/backend/apps/products/migrations/0031_empty_bundle_skus_to_standard.py"}
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
print("V391 frozen source, PR head, full migration fingerprint, and ten exact-source CI checks verified")
