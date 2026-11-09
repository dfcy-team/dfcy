"""Scoped display-only deploy. Run preflight first, then --apply."""
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path('/opt/saas-collab/production/operations/sync-evidence-20261109')
BACKEND = 'production-backend-1'
FRONTEND = 'production-frontend-1'
ASSETS = '/usr/share/nginx/html/assets/'
SERVICE = '/app/apps/integrations/workspace_service.py'
HELPER = '/app/apps/integrations/collection_records.py'


def run(*args):
    return subprocess.check_output(args)


def read(container, path):
    return run('docker', 'exec', container, 'cat', path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


manifest = json.loads((ROOT / 'manifest.json').read_text())
service = read(BACKEND, SERVICE)
assert digest(service) == '93e4b7accc550148bbdf5ae8e434e98e19c96ce5b2ca1d23aece5f9f8fd5fb8d', 'Backend changed; stop'
old_page = read(FRONTEND, ASSETS + manifest['file'])
assert digest(old_page) == manifest['before'], 'Page changed; stop'
for name, checksum in manifest['dependencies'].items():
    assert digest(read(FRONTEND, ASSETS + name)) == checksum, 'Live dependency changed: ' + name
needle = b'    """Bound repeated runtime-setting reads to this workspace request."""\n'
assert service.count(needle) == 1
replacement = needle + b"    if mode == 'sync-runs' and params.get('record_source') in ('video', 'creator'):\n        from .collection_records import collection_records\n        return collection_records(user, params)\n"
candidate = service.replace(needle, replacement)
compile(candidate, SERVICE, 'exec')
helper = (ROOT / 'collection_records.py').read_bytes()
compile(helper, HELPER, 'exec')
page = (ROOT / manifest['file']).read_bytes()
assert digest(page) == manifest['after']
for name, checksum in manifest['additions'].items():
    assert digest((ROOT / name).read_bytes()) == checksum
    exists = subprocess.run(['docker', 'exec', FRONTEND, 'test', '-e', ASSETS + name]).returncode == 0
    if exists:
        assert digest(read(FRONTEND, ASSETS + name)) == checksum, 'Refuse overwrite dependency'
assert subprocess.run(['docker', 'exec', BACKEND, 'test', '-e', HELPER]).returncode != 0, 'Helper already exists; reconcile first'
print('PASS preflight: live hashes, dependencies, syntax; no schedule changes', flush=True)
if '--apply' not in sys.argv:
    raise SystemExit(0)
backup = ROOT / 'backup'
backup.mkdir(exist_ok=False)
(backup / 'workspace_service.py').write_bytes(service)
(backup / manifest['file']).write_bytes(old_page)
(ROOT / 'workspace_service.py').write_bytes(candidate)
for name in manifest['additions']:
    run('docker', 'cp', str(ROOT / name), FRONTEND + ':' + ASSETS + name)
run('docker', 'cp', str(ROOT / 'collection_records.py'), BACKEND + ':' + HELPER)
run('docker', 'cp', str(ROOT / 'workspace_service.py'), BACKEND + ':' + SERVICE)
assert digest(read(BACKEND, SERVICE)) == digest(candidate)
run('docker', 'kill', '--signal=HUP', BACKEND)
run('docker', 'cp', str(ROOT / manifest['file']), FRONTEND + ':' + ASSETS + manifest['file'])
assert digest(read(FRONTEND, ASSETS + manifest['file'])) == manifest['after']
(ROOT / 'applied.json').write_text(json.dumps({'backend': digest(candidate), 'page': manifest['after'], 'scope': 'display-only'}, indent=2))
print('APPLIED: backend graceful reload, sync page only; workers/timers untouched')
