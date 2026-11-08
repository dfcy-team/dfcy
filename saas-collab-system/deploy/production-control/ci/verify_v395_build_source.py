"""Fail-closed admission for the exact V395 release-notes-only build candidate."""
import hashlib
import json
import os
import re
import subprocess
import urllib.request

REPO = "dfcy-team/dfcy"
SOURCE = "2f0593f8c8f5cb493899a1fe66f45063bdb5af98"
TREE = "344fd074342fce130f2c1462469eaafb3dc9c55c"
PARENT = "580dbe33b857841a78d71b9bc1e810e6b4e9e810"
PR_NUMBER = 535
HEAD_REF = "codex/v395-cloud-notes-20261108"
BASE_REF = "codex/inventory-operations-20261107"
NOTES_PATH = "saas-collab-system/frontend/src/data/releaseNotes.json"
NOTES_SHA256 = "8f08f15fcf6c86505d62dfd3bc3e9599edd72548a37d2267df5a4942ba3bcc33"
MIGRATION_SHA256 = "e162017f18188b443c5a1c9a340345285157ffd3b623c1981b35a56703d4a318"
PHASES = {
    42455929668: (310562800, ".github/workflows/phase2-ci.yml"),
    42455929675: (311188731, ".github/workflows/phase3-ci.yml"),
}
EXPECTED_NAMES = {
    "Repository safety and file guard", "Django and pytest", "Frontend build observation gate",
    "Docker Compose configuration", "RPA samples and required documents",
    "Repository safety and forbidden file guard", "Phase 3 Django, data quality, and pytest",
    "Frontend build without dependency lifecycle scripts", "Docker Compose placeholder configuration",
    "RPA samples and Phase 3 documents",
}
SHA = re.compile(r"^[0-9a-f]{40}$")


def _git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def _api(path):
    request = urllib.request.Request(
        "https://api.github.com/repos/" + REPO + "/" + path,
        headers={"Authorization": "Bearer " + os.environ["GH_API_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def migration_fingerprint(git=_git, blob=None):
    paths = sorted(path for path in git("ls-tree", "-r", "--name-only", SOURCE).splitlines()
                   if path.startswith("saas-collab-system/backend/apps/")
                   and len(path.split("/backend/", 1)[1].split("/")) == 4
                   and "/migrations/" in path and path.endswith(".py"))
    digest = hashlib.sha256()
    if blob is None and paths:
        proc = subprocess.run(["git", "cat-file", "--batch"], input="".join(
            SOURCE + ":" + path + "\n" for path in paths).encode(), text=False,
            stdout=subprocess.PIPE, check=True)
        raw = memoryview(proc.stdout)
        offset = 0
        contents = {}
        for path in paths:
            end = proc.stdout.index(b"\n", offset)
            header = proc.stdout[offset:end].decode().split()
            if len(header) != 3 or header[1] != "blob":
                raise ValueError("migration blob missing from pinned source")
            size = int(header[2])
            start, stop = end + 1, end + 1 + size
            contents[path] = bytes(raw[start:stop])
            offset = stop + 1
    else:
        contents = None
    for path in paths:
        digest.update(path.split("/backend/", 1)[1].encode())
        content = blob(path) if blob else contents[path]
        digest.update(content.replace(b"\r\n", b"\n"))
    if not paths:
        raise ValueError("missing source migration files")
    return digest.hexdigest()


def verify(requested_sha, *, git=_git, api=_api, blob=None):
    if requested_sha != SOURCE or not SHA.fullmatch(requested_sha):
        raise ValueError("requested commit is not the pinned V395 build source")
    if git("rev-parse", SOURCE + "^{tree}") != TREE:
        raise ValueError("source tree mismatch")
    if git("rev-list", "--parents", "-n", "1", SOURCE) != SOURCE + " " + PARENT:
        raise ValueError("source parent mismatch")
    # The candidate is exactly the release-notes-only child of its approved source.
    if git("diff", "--name-only", PARENT, SOURCE).splitlines() != [NOTES_PATH]:
        raise ValueError("exact release-notes-only source subdiff mismatch")
    notes = blob(NOTES_PATH) if blob else subprocess.check_output(["git", "cat-file", "blob", SOURCE + ":" + NOTES_PATH])
    if hashlib.sha256(notes).hexdigest() != NOTES_SHA256:
        raise ValueError("release notes fingerprint mismatch")
    pr = api("pulls/" + str(PR_NUMBER))
    if (pr.get("number") != PR_NUMBER or pr.get("state") != "open" or pr.get("merged") is not False
            or pr.get("draft") is not True or pr.get("auto_merge", False) is not None
            or pr.get("head", {}).get("sha") != SOURCE or pr.get("head", {}).get("ref") != HEAD_REF
            or pr.get("head", {}).get("repo", {}).get("full_name") != REPO
            or pr.get("base", {}).get("ref") != BASE_REF
            or pr.get("base", {}).get("repo", {}).get("full_name") != REPO
            or pr.get("base", {}).get("sha") != PARENT):
        raise ValueError("draft PR identity/state mismatch")
    merge_sha = pr.get("merge_commit_sha")
    if not isinstance(merge_sha, str) or not SHA.fullmatch(merge_sha):
        raise ValueError("PR synthetic merge commit is missing")
    synthetic = api("git/commits/" + merge_sha)
    if (synthetic.get("sha") != merge_sha or synthetic.get("tree", {}).get("sha") != TREE
            or [p.get("sha") for p in synthetic.get("parents", [])] != [PARENT, SOURCE]):
        raise ValueError("PR synthetic merge tree or exact parent order mismatch")
    names_seen = set()
    job_ids = set()
    all_jobs = []
    for run_id, (workflow_id, workflow_path) in PHASES.items():
        run = api("actions/runs/" + str(run_id))
        associated = [(p.get("number"), p.get("head", {}).get("sha"), p.get("base", {}).get("sha"))
                      for p in run.get("pull_requests", [])]
        if (run.get("id") != run_id or run.get("workflow_id") != workflow_id
                or associated != [(PR_NUMBER, SOURCE, PARENT)]
                or run.get("path") != workflow_path or run.get("event") != "pull_request"
                or run.get("head_sha") != SOURCE or run.get("head_branch") != HEAD_REF
                or run.get("run_attempt") != 1 or run.get("status") != "completed"
                or run.get("conclusion") != "success"):
            raise ValueError("required workflow run identity/state mismatch")
        page = api(f"actions/runs/{run_id}/attempts/1/jobs?per_page=100&page=1")
        jobs = page.get("jobs", [])
        if page.get("total_count") != 5 or len(jobs) != 5:
            raise ValueError("workflow jobs missing, extra, or truncated")
        for job in jobs:
            if (job.get("status") != "completed" or job.get("conclusion") != "success"
                    or job.get("run_id") != run_id or job.get("head_sha") != SOURCE
                    or job.get("run_attempt") != 1 or type(job.get("id")) is not int or job["id"] <= 0):
                raise ValueError("workflow job not successful on attempt 1")
            if job.get("check_run_url") != f"https://api.github.com/repos/{REPO}/check-runs/{job['id']}":
                raise ValueError("workflow job check-run URL mismatch")
            job_ids.add(job["id"])
            names_seen.add(job.get("name"))
            all_jobs.append(job)
    if len(job_ids) != 10 or names_seen != EXPECTED_NAMES:
        raise ValueError("required phase2/phase3 jobs do not match exactly ten expected checks")
    checks = api("commits/" + SOURCE + "/check-runs?per_page=100&page=1")
    check_runs = checks.get("check_runs", [])
    if checks.get("total_count") != len(check_runs) or len(check_runs) != 10:
        raise ValueError("source check-runs truncated or unexpected")
    checks_by_id = {str(c.get("id")): c for c in check_runs if c.get("app", {}).get("id") == 15368}
    matched_names = set()
    for job in all_jobs:
        check = checks_by_id.get(str(job["id"]))
        if (check is None or check.get("name") != job.get("name") or check.get("head_sha") != SOURCE
                or check.get("status") != "completed" or check.get("conclusion") != "success"):
            raise ValueError("workflow job does not map to successful source Actions check")
        matched_names.add(check["name"])
    if matched_names != EXPECTED_NAMES:
        raise ValueError("workflow jobs do not map exactly to ten expected source checks")
    migration_sha = migration_fingerprint(git=git, blob=blob)
    if migration_sha != MIGRATION_SHA256:
        raise ValueError("source migration fingerprint mismatch")
    return migration_sha


if __name__ == "__main__":
    import sys
    print(verify(sys.argv[1]))
