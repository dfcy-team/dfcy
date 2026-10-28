"""Fail-closed provenance gate for the fixed V317-320 production release."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

P = "27eb1bc28f7052c988fa8f7c32a5420b36596a1c"
C = "7d7c62e10b2ff70303a3aad330dd50835d2cfa21"
H = "98de2fa0fe8c8001c1f6ea58f0720043773e374d"
S = "766b93faf52e61fb5d65644302633951b594888a"
M = "adb253bb7b213d6fbd6cc65f0967c4aba345accd"
S_TREE = "4ca09de4155cbf2d600a304127766fddbeffc421"
H_TREE = "0f97b642946964caa06e45e269e2d5e6d5bf8a1a"
PR = 415
OWNER = "2422808586-coder"
REPO = "dfcy-team/dfcy"
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


def validate(root, controller_sha, repo, pr, reviews, check_runs):
    require(isinstance(reviews, list) and len(reviews) < 100, "review listing incomplete")
    require(repo == REPO, "repository mismatch")
    require(controller_sha == git(root, "rev-parse", "HEAD"), "controller checkout mismatch")
    require(controller_sha == git(root, "rev-parse", "origin/main"), "controller is not latest main")
    require(git(root, "merge-base", "--is-ancestor", M, controller_sha) == "", "M is not a controller ancestor")
    require(git(root, "show", "-s", "--format=%P", S).split() == [P], "S parent mismatch")
    require(git(root, "show", "-s", "--format=%P", H).split() == [S, C], "H parents mismatch")
    require(git(root, "show", "-s", "--format=%T", S) == S_TREE, "S tree mismatch")
    require(git(root, "show", "-s", "--format=%T", H) == H_TREE, "H tree mismatch")
    require(git(root, "show", "-s", "--format=%P", M).split() == [C], "M parent mismatch")
    require(git(root, "show", "-s", "--format=%T", M) == H_TREE, "M tree mismatch")
    s_paths = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", P, S).splitlines())
    h_paths = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", C, H).splitlines())
    require(len(s_paths) == 27 and s_paths == h_paths, "S/H path sets differ")
    def entries(commit):
        result = {}
        for line in git(root, "ls-tree", "-r", "--full-tree", commit).splitlines():
            metadata, path = line.split("\t", 1)
            result[path] = metadata
        return result
    trees = {sha: entries(sha) for sha in (P, C, S, H)}
    for path in s_paths:
        require(trees[P].get(path) == trees[C].get(path)
                and trees[S].get(path) == trees[H].get(path), "S/H entries differ")
    require(pr.get("number") == PR and pr.get("base", {}).get("ref") == "main"
            and pr.get("base", {}).get("repo", {}).get("full_name") == REPO
            and pr.get("head", {}).get("repo", {}).get("full_name") == REPO
            and pr.get("head", {}).get("sha") == H and pr.get("merged") is True
            and pr.get("merge_commit_sha") == M, "PR 415 identity mismatch")
    owner_reviews = [r for r in reviews if r.get("user", {}).get("login") == OWNER
                     and r.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}]
    require(owner_reviews and owner_reviews[-1].get("state") == "APPROVED"
            and owner_reviews[-1].get("commit_id") == H, "latest owner approval mismatch")
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
    pr = api(repo, f"pulls/{PR}", token)
    reviews = api(repo, f"pulls/{PR}/reviews?per_page=100", token)
    require(isinstance(reviews, list) and len(reviews) < 100, "review listing incomplete")
    checks = api(repo, f"commits/{M}/check-runs?per_page=100", token)
    check_runs = checks.get("check_runs", [])
    require(checks.get("total_count") == len(check_runs), "check listing incomplete")
    # Each check run must be tied to its actual commit; query the same 10 contexts on all three SHAs.
    for sha in (S, H):
        payload = api(repo, f"commits/{sha}/check-runs?per_page=100", token)
        require(payload.get("total_count") == len(payload.get("check_runs", [])), "check listing incomplete")
        check_runs.extend(payload.get("check_runs", []))
    validate(root, controller, repo, pr, reviews, check_runs)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, HTTPError, URLError, subprocess.SubprocessError, KeyError, TypeError, json.JSONDecodeError):
        print("Batch provenance validation failed.", file=sys.stderr)
        raise SystemExit(1)
