"""Apply the narrow sample-editor fix to the identified Aliyun frontend build."""
import hashlib
import json
from pathlib import Path
import subprocess

container = "production-frontend-1"
base = "/usr/share/nginx/html/"
entry = "assets/index-C6T8h0h3.js"
chunk = "SampleFulfillmentList-DRb80YkC.js"
receipt = Path("/opt/saas-collab/production/hotfix-sample-edit-country-20261109")


def run(*args):
    return subprocess.check_output(["docker", *args])


def read(name):
    return run("exec", container, "cat", base + name)


def install(path, name):
    dest = base + name
    run("cp", str(path), container + ":" + dest + ".country-stage")
    run("exec", container, "chmod", "644", dest + ".country-stage")
    run("exec", container, "mv", dest + ".country-stage", dest)


html = read("index.html")
assert entry.encode() in html
original = read(entry)
assert original.count(chunk.encode()) == 2
source = read("assets/" + chunk)
needle = b'q.value=l,T.value=(v=l.items)!=null&&v.length?l.items.map(x=>({...x})):[ye()],N.value=!0,await ae(!1)}'
patch = needle[:-1] + b';if(m.value?.id===l.id&&N.value&&!l.items?.length){const country=String(R.value?.country_code||"").trim().toUpperCase();if(country)for(const item of T.value)if(!item.site_code)item.site_code=country}}'
assert source.count(needle) == 1
fixed = source.replace(needle, patch)
sha = hashlib.sha256(fixed).hexdigest()
name = "SampleFulfillmentList-country-" + sha[:12] + ".js"
updated = original.replace(chunk.encode(), name.encode())
receipt.mkdir(mode=0o700)
(receipt / "entry-before.js").write_bytes(original)
(receipt / "entry-after.js").write_bytes(updated)
(receipt / name).write_bytes(fixed)
install(receipt / name, "assets/" + name)
assert read("assets/" + name) == fixed
assert read("index.html") == html and read(entry) == original
try:
    install(receipt / "entry-after.js", entry)
    assert read(entry) == updated
except Exception:
    install(receipt / "entry-before.js", entry)
    raise
result = {"chunk": name, "sha256": sha, "entry": entry, "database_writes": 0}
(receipt / "receipt.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
