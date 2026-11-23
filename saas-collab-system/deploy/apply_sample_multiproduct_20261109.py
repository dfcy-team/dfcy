"""Install a SHA-guarded sample route and service delta; never migrate or backfill."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

fill_missing = "--fill-missing" in sys.argv[1:]
root = Path("/opt/saas-collab/production/hotfix-sample-multiproduct-20261109" + ("-fill" if fill_missing else ""))
plan = json.load(sys.stdin)
front = "production-frontend-1"
back = "production-backend-1"
expected_containers = {front: "f015d311dc49", back: "2def693b4ad7"}
expected_paths = {
    "/app/apps/influencers/services.py",
    "/app/apps/influencers/" + ("serializers.py" if fill_missing else "views.py"),
    "/usr/share/nginx/html/assets/index-BCq0YIA9.js",
}
html_path = "/usr/share/nginx/html/index.html"
expected_entry = b"/assets/index-BCq0YIA9.js"


def docker(*args):
    return subprocess.check_output(["docker", *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_container(container):
    assert docker("inspect", "-f", "{{.Id}}", container).decode().startswith(expected_containers[container])


def read(item):
    return docker("exec", item["container"], "cat", item["path"])


def install(item, file):
    check_container(item["container"])
    temp = item["path"] + ".multiproduct-stage"
    docker("cp", str(file), item["container"] + ":" + temp)
    docker("exec", item["container"], "chmod", "644", temp)
    docker("exec", item["container"], "mv", temp, item["path"])


def reload_backend():
    docker("exec", back, "python", "-c", "import os,signal;os.kill(1,signal.SIGHUP)")


def health():
    req = urllib.request.Request("http://127.0.0.1:8000/api/internal/health/",
                                 headers={"Host": "localhost", "X-Forwarded-Proto": "https"})
    for _ in range(18):
        try:
            with urllib.request.urlopen(req, timeout=3) as result:
                if result.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise RuntimeError("Backend health probe failed")


assert len(plan) in ({4, 5} if fill_missing else {5}) and {x["path"] for x in plan if x["before"]} == expected_paths
assert plan[-1]["path"].endswith("/index-BCq0YIA9.js")
for container in expected_containers:
    check_container(container)
assert expected_entry in docker("exec", front, "cat", html_path)
root.mkdir(mode=0o700)
originals = {}
for i, item in enumerate(plan):
    data = base64.b64decode(item["data"], validate=True)
    assert digest(data) == item["after"]
    if item["before"]:
        originals[i] = read(item)
        assert digest(originals[i]) == item["before"], item["path"]
        (root / f"backup-{i}").write_bytes(originals[i])
    else:
        assert item["container"] == front and item["path"].startswith(
            "/usr/share/nginx/html/assets/SampleFulfillmentList-multiproduct-")
        assert subprocess.run(["docker", "exec", front, "test", "-e", item["path"]]).returncode == 1
    if item["path"].endswith(".py"):
        compile(data, item["path"], "exec")
    (root / f"new-{i}").write_bytes(data)

changed = []
try:
    for i, item in enumerate(plan):
        if i == len(plan) - 1:
            assert expected_entry in docker("exec", front, "cat", html_path)
        if item["before"]:
            assert read(item) == originals[i], "Live file changed"
        install(item, root / f"new-{i}")
        changed.append(i)
        assert digest(read(item)) == item["after"]
        if i == 1:
            docker("exec", back, "python", "manage.py", "check")
            reload_backend()
            time.sleep(3)
            health()
except Exception:
    for i in reversed(changed):
        if i in originals and digest(read(plan[i])) == plan[i]["after"]:
            install(plan[i], root / f"backup-{i}")
    if any(plan[i]["container"] == back for i in changed):
        reload_backend()
    raise

receipt = [{k: v for k, v in x.items() if k != "data"} for x in plan]
(root / "receipt.json").write_text(json.dumps(receipt, indent=2))
print(json.dumps({"database_writes": 0, "receipt": str(root / "receipt.json"), "files": receipt}))
