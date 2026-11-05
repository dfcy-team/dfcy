"""Admission for the two-file V384 insert-only derivative; no dispatch or deployment."""
import json
import sys

from verify_v384_cloud_source import IDENTITY, REPO, _api, _git

HEAD = "d8c28d8cfed9a97f372b5b91074d3b22461110bb"
TREE = "2de94ee86d7d32a017c7a654b05df429fd9f3aa7"
BASE = "6ec185c9f6805f87737e8695c5799ae197fb24f0"
FILES = {"saas-collab-system/backend/apps/influencers/" + p for p in
         ("models.py", "tests/test_cloud_insert_contract.py")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(sha, git=_git, api=_api):
    require(sha == HEAD and git("rev-parse", HEAD + "^{tree}") == TREE, "source identity")
    require(git("rev-list", "--parents", "-n", "1", HEAD) == HEAD + " " + BASE, "parent")
    require(set(git("diff", "--name-only", BASE, HEAD).splitlines()) == FILES, "file scope")
    pr = api("pulls/515")
    require(pr["number"] == 515 and pr["state"] == "open" and
            all(pr[k]["repo"]["full_name"] == REPO for k in ("head", "base")) and
            (pr["head"]["sha"], pr["head"]["ref"]) == (HEAD, "release/v384-insert-compat-20261105") and
            (pr["base"]["sha"], pr["base"]["ref"]) == (BASE, "release/v384-cloud-notes-20261105"), "PR identity")
    names = []
    for run_id, workflow in [(42046962744, "phase2-ci.yml"), (42046962680, "phase3-ci.yml")]:
        path = f"actions/runs/{run_id}"
        run = api(path)
        require(run["id"] == run_id and run["head_sha"] == HEAD and run["run_attempt"] == 1 and
                run["path"] == ".github/workflows/" + workflow and run["status"] == "completed" and
                run["conclusion"] == "success", "run identity or result")
        page = api(path + "/attempts/1/jobs?per_page=100")
        require(page["total_count"] == len(page["jobs"]) == 5, "job inventory")
        for job in page["jobs"]:
            require(job["run_id"] == run_id and job["head_sha"] == HEAD and
                    job["status"] == "completed" and job["conclusion"] == "success", "job result")
            names.append(job["name"])
    require(sorted(names) == sorted(json.loads(IDENTITY.read_text())["checks"]), "ten named checks")


if __name__ == "__main__":
    verify(sys.argv[1])
