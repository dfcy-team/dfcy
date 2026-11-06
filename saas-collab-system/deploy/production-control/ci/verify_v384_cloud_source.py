"""Fail-closed authorization for the immutable V384 cloud build source."""
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

IDENTITY = Path(__file__).with_name("v384-cloud-source-identity.json")
REPO = "dfcy-team/dfcy"
SHA = re.compile(r"^[0-9a-f]{40}$")
HEX256 = re.compile(r"^[0-9a-f]{64}$")


def _git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def _api(path, opener=None):
    request = urllib.request.Request(
        "https://api.github.com/repos/" + REPO + "/" + path,
        headers={"Authorization": "Bearer " + os.environ["GH_API_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with (opener or urllib.request.urlopen)(request, timeout=30) as response:
        return json.load(response)


def verify(requested_sha, *, identity=None, git=_git, api=_api):
    identity = identity or json.loads(IDENTITY.read_text(encoding="utf-8"))
    source = identity["source_sha"]
    if requested_sha != source or not SHA.fullmatch(requested_sha):
        raise ValueError("request is not the approved V384 source")
    for key in ("source_tree", "parent_sha", "pull_request_head_sha", "pull_request_base_sha"):
        if not SHA.fullmatch(identity[key]):
            raise ValueError("invalid pinned " + key)
    if identity["pull_request_head_sha"] != source:
        raise ValueError("PR head pin differs from source")
    if len(identity["files"]) != 7 or any(not HEX256.fullmatch(v) for v in identity["files"].values()):
        raise ValueError("invalid exact file inventory")
    if not HEX256.fullmatch(identity["migration_sha256"]):
        raise ValueError("invalid migration fingerprint")

    if git("rev-parse", source + "^{tree}") != identity["source_tree"]:
        raise ValueError("source tree mismatch")
    parent = identity["reviewed_parent"]
    fixture = "saas-collab-system/backend/scripts/sales_mysql_fixture.py"
    if git("rev-list", "--parents", "-n", "1", source) != source + " " + parent:
        raise ValueError("fixture parent mismatch")
    if git("diff-tree", "--no-commit-id", "--name-only", "-r", source) != fixture:
        raise ValueError("fixture-only change required")
    if hashlib.sha256(subprocess.check_output(["git", "show", source + ":" + fixture])).hexdigest() != identity["fixture_sha256"]:
        raise ValueError("fixture hash mismatch")
    if git("rev-list", "--parents", "-n", "1", parent) != parent + " " + identity["parent_sha"]:
        raise ValueError("source parent mismatch")
    names = set(git("diff-tree", "--no-commit-id", "--name-only", "-r", parent).splitlines())
    if names != set(identity["files"]):
        raise ValueError("source file inventory mismatch")
    for name, expected in identity["files"].items():
        if hashlib.sha256(subprocess.check_output(["git", "show", source + ":" + name])).hexdigest() != expected:
            raise ValueError("source file hash mismatch: " + name)

    pr = api("pulls/" + str(identity["pull_request"]))
    if (pr["number"] != identity["pull_request"] or pr["state"] != "open"
            or pr["head"]["sha"] != source or pr["head"]["repo"]["full_name"] != REPO
            or pr["base"]["ref"] != "main" or pr["base"]["repo"]["full_name"] != REPO
            or pr["base"]["sha"] != identity["pull_request_base_sha"]):
        raise ValueError("PR identity or base mismatch")
    endpoint = "commits/" + source + "/check-runs?per_page=100&page="
    first = api(endpoint + "1")
    total = first.get("total_count")
    if not isinstance(total, int) or total < 0:
        raise ValueError("check-run total_count missing or invalid")
    checks = list(first.get("check_runs", []))
    for page in range(2, (total + 99) // 100 + 1):
        result = api(endpoint + str(page))
        if result.get("total_count") != total:
            raise ValueError("check-run count changed during pagination")
        checks.extend(result.get("check_runs", []))
    if len(checks) != total or len({c.get("id") for c in checks}) != total:
        raise ValueError("check-run pages truncated or duplicated")
    latest = {}
    for check in sorted(checks, key=lambda item: item["id"]):
        if check["name"] in identity["checks"]:
            latest[check["name"]] = check
    required = set(identity["checks"])
    if len(required) != 10 or set(latest) != required:
        raise ValueError("required check set missing or duplicated by identity")
    if any(c["status"] != "completed" or c["conclusion"] != "success" or c["head_sha"] != source
           for c in latest.values()):
        raise ValueError("required source check is not completed successfully")
    return identity["migration_sha256"]


if __name__ == "__main__":
    import sys
    print(verify(sys.argv[1]))
