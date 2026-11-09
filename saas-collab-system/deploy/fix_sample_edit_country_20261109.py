"""Apply the narrow sample-editor fix to the identified Aliyun frontend build."""
import hashlib
import json
from pathlib import Path
import subprocess

container = "production-frontend-1"
base = "/usr/share/nginx/html/"
entry = "assets/index-C6T8h0h3.js"
chunk = "SampleFulfillmentList-country-81901eff98b3.js"
receipt = Path("/opt/saas-collab/production/hotfix-sample-edit-country-20261109-r2")


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
country = b'String((String(R.value?.id)===String(n.store)?R.value?.country_code:"")||ge.value?.country_code||"").trim().toUpperCase()'
replacements = [
    (b'const country=String(R.value?.country_code||"").trim().toUpperCase()', b'const country=' + country),
    (b'"model-value":k.site_code,readonly:""', b'"model-value":k.site_code||(m.value?' + country + b':""),readonly:""'),
    (b'return{site_code:_.site_code,requested_sku:', b'return{site_code:_.site_code||' + country + b',requested_sku:'),
]
assert hashlib.sha256(source).hexdigest() == "81901eff98b3e8abd57b937cf43fdd953f371a0d153f529f015be51b9b5cb433"
fixed = source
for needle, patch in replacements:
    assert fixed.count(needle) == 1, needle
    fixed = fixed.replace(needle, patch)
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
