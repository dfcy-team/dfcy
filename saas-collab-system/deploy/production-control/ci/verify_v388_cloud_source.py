"""Fail-closed identity check for the V388 cloud build-only draft."""
import json
import os
import re
import subprocess
import urllib.request

REPO = "dfcy-team/dfcy"
SOURCE = "d477e713c604cbcd9db0c92fbd1d0bf74e5bb38b"
TREE = "9dcbca560727c28ce358215c222dd161fbe19e20"
PARENT = "d31be33b0cf34988bd574756913d4c9644d8dfd5"
PR_NUMBER = 521
HEAD_REF = "codex/v388-cloud-ui-20261107"
BASE_REF = "codex/v385-v388-vm-release-20261106"
FILES = {
    "saas-collab-system/frontend/src/data/releaseNotes.json",
    "saas-collab-system/frontend/src/views/sales-management/SalesOperations.vue",
    "saas-collab-system/frontend/tests/sales-operations.spec.js",
}
PHASES = {
    42308488585: (310562800, (
        "Repository safety and file guard", "Django and pytest",
        "Frontend build observation gate", "Docker Compose configuration",
        "RPA samples and required documents")),
    42308488689: (311188731, (
        "Repository safety and forbidden file guard",
        "Phase 3 Django, data quality, and pytest",
        "Frontend build without dependency lifecycle scripts",
        "Docker Compose placeholder configuration",
        "RPA samples and Phase 3 documents")),
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


def verify(requested_sha, *, git=_git, api=_api):
    if requested_sha != SOURCE or not SHA.fullmatch(requested_sha):
        raise ValueError("requested commit is not the pinned V388 cloud source")
    if git("rev-parse", SOURCE + "^{tree}") != TREE:
        raise ValueError("source tree mismatch")
    if git("rev-list", "--parents", "-n", "1", SOURCE) != SOURCE + " " + PARENT:
        raise ValueError("source parent mismatch")
    names = set(git("diff-tree", "--no-commit-id", "--name-only", "-r", SOURCE).splitlines())
    if names != FILES:
        raise ValueError("exact three-file source subdiff mismatch")
    pr = api("pulls/" + str(PR_NUMBER))
    if (pr.get("number") != PR_NUMBER or pr.get("state") != "open" or pr.get("merged") is not False
            or pr.get("draft") is not True or pr.get("auto_merge", False) is not None
            or pr.get("head", {}).get("sha") != SOURCE
            or pr.get("head", {}).get("ref") != HEAD_REF
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
    runs = []
    for run_id, (workflow_id, expected_jobs) in PHASES.items():
        run = api("actions/runs/" + str(run_id))
        associated = [(p.get("number"), p.get("head", {}).get("sha"), p.get("base", {}).get("sha"))
                      for p in run.get("pull_requests", [])]
        if (run.get("id") != run_id or run.get("workflow_id") != workflow_id
                or associated != [(PR_NUMBER, SOURCE, PARENT)]
                or run.get("event") != "pull_request" or run.get("head_sha") != SOURCE
                or run.get("head_branch") != HEAD_REF or run.get("run_attempt") != 1
                or run.get("path") != (".github/workflows/phase2-ci.yml" if run_id == 42308488585
                                        else ".github/workflows/phase3-ci.yml")
                or run.get("status") != "completed" or run.get("conclusion") != "success"):
            raise ValueError("required workflow run identity/state mismatch")
        page = api("actions/runs/" + str(run_id) + "/attempts/1/jobs?per_page=100&page=1")
        total = page.get("total_count")
        jobs = page.get("jobs", [])
        if not isinstance(total, int) or total != len(expected_jobs) or len(jobs) != total:
            raise ValueError("workflow jobs missing, extra, or truncated")
        if {j.get("name") for j in jobs} != set(expected_jobs):
            raise ValueError("workflow job names mismatch")
        if any(j.get("status") != "completed" or j.get("conclusion") != "success"
               or type(j.get("id")) is not int or j["id"] <= 0
               or j.get("run_id") != run_id or j.get("head_sha") != SOURCE
               or j.get("run_attempt") != 1 or j.get("check_run_url") !=
               f"https://api.github.com/repos/{REPO}/check-runs/{j['id']}" for j in jobs):
            raise ValueError("workflow job not successful on attempt 1")
        runs.extend(jobs)
    check_runs = api("commits/" + SOURCE + "/check-runs?per_page=100&page=1")
    checks = check_runs.get("check_runs", [])
    if check_runs.get("total_count") != len(checks) or len(checks) != 10:
        raise ValueError("source check-runs truncated or unexpected")
    checks_by_id = {str(c.get("id")): c for c in checks if c.get("app", {}).get("id") == 15368}
    expected_names = {name for _, names in PHASES.values() for name in names}
    matched = set()
    for job in runs:
        check_id = job.get("check_run_url", "").rstrip("/").split("/")[-1]
        check = checks_by_id.get(check_id)
        if (check is None or check.get("name") != job.get("name")
                or check.get("head_sha") != SOURCE or check.get("status") != "completed"
                or check.get("conclusion") != "success"):
            raise ValueError("workflow job does not map to successful source Actions check")
        matched.add(check["name"])
    if len({j.get("id") for j in runs}) != 10 or matched != expected_names:
        raise ValueError("workflow jobs do not map exactly to ten expected source checks")
    return SOURCE


if __name__ == "__main__":
    import sys
    print(verify(sys.argv[1]))
