"""Package only a verified route and backend delta from the production revision."""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
fill_missing = "--fill-missing" in sys.argv[2:]
src = root / "sample-multiproduct-release/saas-collab-system"
front = src / "frontend"
live = {k: base64.b64decode(v) for k, v in json.loads(
    (root / "sample-multiproduct-live.json").read_text(encoding="utf-8-sig")
).items()}
entry = "assets/index-BCq0YIA9.js"
old = "SampleFulfillmentList-DG61rFoQ.js"
old_css = "SampleFulfillmentList-5Oz_9taB.css"


def only(dir_path, pattern):
    result, = dir_path.glob(pattern)
    return result


def imports(js):
    return re.findall(rb'import(?:\{[^}]+\}from)?"\./([^"]+\.js)"', js)


def replace_imports(js, mapping):
    return re.sub(rb'(import(?:\{[^}]+\}from)?"\./)([^"]+\.js)"',
                  lambda m: m[1] + mapping[m[2]] + b'"', js)


base = only(front / "dist/assets", "SampleFulfillmentList-*.js").read_bytes()
deployed = live["assets/" + old]
base_names = imports(base)
live_names = imports(deployed)
assert len(base_names) == len(live_names)
base_to_live = dict(zip(base_names, live_names))
assert replace_imports(base, base_to_live) == deployed, "Baseline does not reproduce the current route"
new_assets = front / ("dist-multiproduct-fill/assets" if fill_missing else "dist-multiproduct/assets")
patched = only(new_assets, "SampleFulfillmentList-*.js").read_bytes()
patched_names = imports(patched)
assert len(patched_names) == len(base_names), "Route acquired dependencies"
mapping = dict(zip(patched_names, live_names))
# Compare named exports at the import boundary, not minified local aliases.
def signature(js):
    return [tuple(sorted(x.split(b" as ")[0] for x in m.split(b","))) if m else ()
            for m in re.findall(rb'import(?:\{([^}]+)\}from)?"\./[^"]+\.js"', js)]


assert signature(patched) == signature(base)
def stem(name):
    return re.sub(rb"-[A-Za-z0-9_-]{8}\.js$", b"", name)


for original, new in zip(base_names, patched_names):
    assert stem(original) == stem(new), (original, new)
patched = replace_imports(patched, mapping)
assert set(imports(patched)) == set(live_names)
css = only(new_assets, "SampleFulfillmentList-*.css").read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


js_name = "SampleFulfillmentList-multiproduct-" + digest(patched)[:12] + ".js"
css_name = "SampleFulfillmentList-multiproduct-" + digest(css)[:12] + ".css"
main = live[entry]
backend_names = ("services.py", "views.py")
if fill_missing:
    live = {k: base64.b64decode(v) for k, v in json.loads(
        (root / "sample-multiproduct-fill-live.json").read_text(encoding="utf-8-sig")
    ).items()}
    main = live[entry]
    assert digest(main) == "490e65b2bb4cc40746fca46794df5716fe23fb9888ae9b6f85c1c20f0f107bff"
    assert digest(live["services.py"]) == "6d195ef7f7d1e362efe3d13e8ed2563c6c3590c3aae6586a2499e6e020b2974a"
    old = "SampleFulfillmentList-multiproduct-b93ed19df8c5.js"
    old_css = "SampleFulfillmentList-multiproduct-3abf5112c646.css"
    backend_names = ("services.py", "serializers.py")
assert main.count(old.encode()) == 2 and main.count(old_css.encode()) == 1
new_entry = main.replace(old.encode(), js_name.encode()).replace(old_css.encode(), css_name.encode())
files = []


def add(container, path, data, previous=None):
    files.append({"container": container, "path": path,
                  "before": digest(previous) if previous is not None else None,
                  "after": digest(data), "data": base64.b64encode(data).decode()})


for name in backend_names:
    add("production-backend-1", "/app/apps/influencers/" + name,
        (src / "backend/apps/influencers" / name).read_bytes(), live[name])
for name, data in ((js_name, patched), (css_name, css)):
    (root / name).write_bytes(data)
    if name not in {old, old_css}:
        add("production-frontend-1", "/usr/share/nginx/html/assets/" + name, data)
add("production-frontend-1", "/usr/share/nginx/html/" + entry, new_entry, main)
(root / ("sample-multiproduct-fill-package.json" if fill_missing else "sample-multiproduct-deploy-package.json")).write_text(json.dumps(files))
print(js_name, css_name)
