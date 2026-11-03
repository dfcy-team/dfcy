"""CAS-guarded overlay for the inspected production assets. Run preflight first."""
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACK = 'production-backend-1'
FRONT = 'production-frontend-1'
ASSETS = '/usr/share/nginx/html/assets/'
FILES = {
    'tiktok_ads_services.py': ('reports', 'ad4548c00f32aea4e43afa268e5db3eb68a8a7cc5d4831f9c5cb6d5a33149b8a'),
    'tiktok_ads_views.py': ('reports', '15dc2fedab1a004b0bf0ff942ac3b508321b75072cf959920cad70b97b218f5b'),
    'gmv_max_read.py': ('integrations', '0632dbd135773c3651d494191ef937d5227c90fe763fa30c1007d18ba1c1d375'),
    'gmv_max_overview.py': ('integrations', '4b163037ce52315731eb3955d96e1da6dad4567080d9996a14f2dd5eded52686'),
}


def read(container, path):
    return subprocess.check_output(['docker', 'exec', container, 'cat', path])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(container, path, data):
    subprocess.run(['docker', 'exec', '-i', container, 'sh', '-c', 'cat > "$1.tmp" && mv "$1.tmp" "$1"', 'sh', path], input=data, check=True)


changes = []
for name, (app, expected) in FILES.items():
    path = '/app/apps/' + app + '/' + name
    old, new = read(BACK, path), (ROOT / name).read_bytes()
    assert sha(old) == expected, ('Concurrent backend change', name)
    compile(new, name, 'exec')
    changes.append((BACK, path, old, new))

module_name = 'TikTokGmvOnly-20261104.js'
module = (ROOT / module_name).read_bytes()
for bindings, relative in re.findall(r'import\{([^}]+)\}from["\x27](\./[^"\x27]+)["\x27]', module.decode()):
    dependency = read(FRONT, ASSETS + relative[2:]).decode()
    exports = re.findall(r'export\{([^}]+)\}', dependency)
    available = {item.strip().split(' as ')[-1] for block in exports for item in block.split(',')}
    required = {item.strip().split(' as ')[0] for item in bindings.split(',')}
    assert required <= available, (relative, required - available)

wrapper_path = ASSETS + 'MarketingAdvertising-C5tNwVy_.js'
old_wrapper = read(FRONT, wrapper_path)
assert sha(old_wrapper) == '30db559b71f37aec634dd33ddadfea03683ae5957c879917c6dc029296a67a12'
assert old_wrapper.count(b'b(ye,{key:') == 1
new_wrapper_name = 'MarketingAdvertising-GmvOnly20261104.js'
wrapper = ('import GmvOnly from "./' + module_name + '";').encode() + old_wrapper.replace(b'b(ye,{key:', b'b(GmvOnly,{key:')
entry_path = ASSETS + 'index-BjiGsb4W.js'
entry = read(FRONT, entry_path)
assert entry.count(b'MarketingAdvertising-C5tNwVy_.js') == 2
new_entry = entry.replace(b'MarketingAdvertising-C5tNwVy_.js', new_wrapper_name.encode())
changes.append((FRONT, entry_path, entry, new_entry))

if '--apply' not in sys.argv:
    import difflib
    for container, path, old, new in changes[:4]:
        print(''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile=path, tofile=path)))
    print('PREFLIGHT_OK: imports, source syntax and live fingerprints verified')
    sys.exit(0)

backup = ROOT / ('backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
backup.mkdir(exist_ok=False)
for container, path, old, new in changes:
    assert read(container, path) == old, ('Concurrent change', path)
    (backup / (container + '-' + Path(path).name)).write_bytes(old)
receipt = [{'container': c, 'path': p, 'before': sha(o), 'after': sha(n)} for c, p, o, n in changes]
(ROOT / 'receipt.json').write_text(json.dumps(receipt, indent=2))
applied = []
try:
    put(FRONT, ASSETS + module_name, module)
    put(FRONT, ASSETS + new_wrapper_name, wrapper)
    for container, path, old, new in changes:
        assert read(container, path) == old
        put(container, path, new)
        applied.append((container, path, old))
        assert read(container, path) == new
    subprocess.run(['docker', 'exec', BACK, 'python', '-c', 'import os,signal; os.kill(1,signal.SIGHUP)'], check=True)
except Exception:
    for container, path, old in reversed(applied):
        put(container, path, old)
    subprocess.run(['docker', 'exec', BACK, 'python', '-c', 'import os,signal; os.kill(1,signal.SIGHUP)'], check=True)
    raise
print('APPLIED: receipt.json and backup/ retained; no database writes or task changes')
