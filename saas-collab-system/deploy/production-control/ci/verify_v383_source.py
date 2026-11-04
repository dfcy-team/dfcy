"""Verify the single approved V383 application source before the normal build."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

identity = json.loads(Path(__file__).with_name("v383-source-identity.json").read_text())
def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()

assert os.environ["GITHUB_REPOSITORY"] == "dfcy-team/dfcy"
assert os.environ["GITHUB_REF"] == "refs/heads/main"
assert os.environ["REQUESTED_ACTION"] == "deploy"
assert os.environ["REQUESTED_TRANSPORT"] == "ssh"
assert git("rev-parse", "HEAD") == identity["source_sha"]
subprocess.check_call(["git", "merge-base", "--is-ancestor", identity["parent_sha"], "HEAD"])
assert git("rev-list", "--count", identity["parent_sha"]+"..HEAD") == str(identity["commit_count"])
assert set(git("diff", "--name-only", identity["parent_sha"], "HEAD").splitlines()) == set(identity["files"])
for name, digest in identity["files"].items():
    content = subprocess.check_output(["git", "show", "HEAD:"+name])
    assert hashlib.sha256(content).hexdigest() == digest

def api(path):
    request = urllib.request.Request("https://api.github.com/repos/dfcy-team/dfcy/"+path,
        headers={"Authorization":"Bearer "+os.environ["GH_API_TOKEN"],
                 "Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

pr = api("pulls/"+str(identity["pull_request"]))
assert pr["head"]["sha"] == identity["source_sha"]
checks = api("commits/"+identity["source_sha"]+"/check-runs?per_page=100")
required = {
"Repository safety and file guard", "Django and pytest",
"Frontend build observation gate", "Docker Compose configuration",
"RPA samples and required documents", "Repository safety and forbidden file guard",
"Phase 3 Django, data quality, and pytest",
"Frontend build without dependency lifecycle scripts",
"Docker Compose placeholder configuration", "RPA samples and Phase 3 documents"}
latest = {}
for check in sorted(checks["check_runs"], key=lambda item:item["id"]):
    if check["name"] in required:
        latest[check["name"]] = check
assert set(latest) == required
assert all(check["status"] == "completed" and check["conclusion"] == "success"
           for check in latest.values())
print("V383 frozen source and ten CI checks verified")
