"""Fail-closed provenance gate for preparing the V330 cumulative candidate."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = "dfcy-team/dfcy"
CONFIG = Path(__file__).with_name("v330-release-identity.json")
CONTEXTS = {
    "Django and pytest", "Docker Compose configuration", "Docker Compose placeholder configuration",
    "Frontend build observation gate", "RPA samples and required documents",
    "Frontend build without dependency lifecycle scripts", "Repository safety and forbidden file guard",
    "RPA samples and Phase 3 documents", "Repository safety and file guard",
    "Phase 3 Django, data quality, and pytest",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def identity(config_path=CONFIG):
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    for key in ("source_sha", "integration_sha", "merge_commit_sha", "pull_request_number",
                "review_policy"):
        require(data.get(key) not in (None, ""), f"V330 identity is unbound: {key}")
    require(data["review_policy"] == "ci_only", "unsupported review policy")
    return data


def git(root, *args):
    p = subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args],
                       check=True, capture_output=True, timeout=20)
    return p.stdout.decode().strip()


def api(repo, path, token):
    request = Request(f"https://api.github.com/repos/{repo}/{path}", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "batch-provenance-gate",
    })
    with urlopen(request, timeout=20) as response:
        require(response.status == 200, "GitHub API request failed")
        return json.loads(response.read())


def validate(root, controller_sha, repo, pr, check_runs, config=None):
    cfg = config or identity()
    P, C, S, H, M = (cfg[k] for k in ("source_parent", "integration_parent",
                                        "source_sha", "integration_sha", "merge_commit_sha"))
    PR = cfg["pull_request_number"]
    require(cfg.get("review_policy") == "ci_only", "unsupported review policy")
    require(repo == REPO, "repository mismatch")
    require(controller_sha == git(root, "rev-parse", "HEAD"), "controller checkout mismatch")
    require(controller_sha == git(root, "rev-parse", "origin/main"), "controller is not latest main")
    require(git(root, "merge-base", "--is-ancestor", M, controller_sha) == "", "M is not a controller ancestor")
    require(git(root, "show", "-s", "--format=%P", S).split() == [P], "S parent mismatch")
    require(git(root, "show", "-s", "--format=%P", H).split() == [C], "H parent mismatch")
    require(git(root, "show", "-s", "--format=%T", S) == cfg["source_tree"], "S tree mismatch")
    require(git(root, "show", "-s", "--format=%T", H) == cfg["integration_tree"], "H tree mismatch")
    require(git(root, "show", "-s", "--format=%P", M).split() == [C], "M parent mismatch")
    require(git(root, "show", "-s", "--format=%T", M) == cfg["integration_tree"], "M tree mismatch")
    s_paths = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", P, S).splitlines())
    h_paths = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", C, H).splitlines())
    require(len(s_paths) == cfg["source_path_count"] and h_paths <= s_paths,
            "integration path set exceeds approved business paths")
    def entries(commit):
        result = {}
        for line in git(root, "ls-tree", "-r", "--full-tree", commit).splitlines():
            metadata, path = line.split("\t", 1)
            result[path] = metadata
        return result
    trees = {sha: entries(sha) for sha in (P, C, S, H)}
    for path in s_paths:
        require(trees[S].get(path) == trees[H].get(path), "S/H business entries differ")
    for path in set(trees[C]) | set(trees[H]):
        if path not in s_paths:
            require(trees[C].get(path) == trees[H].get(path), "integration changed unapproved path")
    require(pr.get("number") == PR and pr.get("base", {}).get("ref") == "main"
            and pr.get("base", {}).get("repo", {}).get("full_name") == REPO
            and pr.get("head", {}).get("repo", {}).get("full_name") == REPO
            and pr.get("head", {}).get("sha") == H and pr.get("merged") is True
            and pr.get("merge_commit_sha") == M, "V330 PR identity mismatch")
    for sha in (S, H, M):
        group = [c for c in check_runs if c.get("head_sha") == sha]
        require(len(group) == 10 and {c.get("name") for c in group} == CONTEXTS,
                "required SHA CI set incomplete")
        require(all(c.get("status") == "completed" and c.get("conclusion") == "success"
                    and c.get("app", {}).get("id") == 15368
                    and c.get("app", {}).get("slug") == "github-actions"
                    for c in group), "required SHA CI failure")


def main():
    root = Path(sys.argv[1]).resolve(strict=True)
    token, repo, controller = os.environ.get("GH_API_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_SHA", "")
    require(bool(token) and re.fullmatch(r"[0-9a-f]{40}", controller) is not None, "workflow identity missing")
    cfg = identity()
    pr = api(repo, f"pulls/{cfg['pull_request_number']}", token)
    checks = api(repo, f"commits/{cfg['merge_commit_sha']}/check-runs?per_page=100", token)
    check_runs = checks.get("check_runs", [])
    require(checks.get("total_count") == len(check_runs), "check listing incomplete")
    # Each check run must be tied to its actual commit; query the same 10 contexts on all three SHAs.
    for sha in (cfg["source_sha"], cfg["integration_sha"]):
        payload = api(repo, f"commits/{sha}/check-runs?per_page=100", token)
        require(payload.get("total_count") == len(payload.get("check_runs", [])), "check listing incomplete")
        check_runs.extend(payload.get("check_runs", []))
    validate(root, controller, repo, pr, check_runs, cfg)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, HTTPError, URLError, subprocess.SubprocessError, KeyError, TypeError, json.JSONDecodeError):
        print("Batch provenance validation failed.", file=sys.stderr)
        raise SystemExit(1)
