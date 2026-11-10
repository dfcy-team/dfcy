"""Repair only the sync-record page; retain the current v404 entry and APIs."""
import hashlib
import json
import pathlib
import subprocess

root = pathlib.Path('/opt/saas-collab/production/operations/sync-evidence-deps-20261110')
container = 'production-frontend-1'
assets = '/usr/share/nginx/html/assets/'
manifest = json.loads((root / 'manifest.json').read_text())
def read(name):
    return subprocess.check_output(['docker', 'exec', container, 'cat', assets + name])
def sha(data):
    return hashlib.sha256(data).hexdigest()

old = read(manifest['file'])
assert sha(old) == '0957480d600c2492447465a7bed331d44f6a805b4f8c2857e3f2b3ddd1b43351', 'Page changed; stop'
assert sha(read('index-v404-665f2bafaee8.js')) == '665f2bafaee86dda2752e8a56ae8fac7cf4537dce50a1afac96bb19f92849dfc'
for name, expected in manifest['dependencies'].items():
    if name == 'index-BCq0YIA9.js':
        assert read(name).strip() == b'export * from "./index-v403-32efbbb01679.js";'
        assert read('index-v403-32efbbb01679.js').strip() == b'export * from "./index-v404-665f2bafaee8.js";'
    else:
        assert sha(read(name)) == expected, 'Dependency changed: ' + name
new = (root / manifest['file']).read_bytes()
assert sha(new) == manifest['after']
backup = root / 'before.js'
assert not backup.exists()
backup.write_bytes(old)
subprocess.check_call(['docker', 'cp', str(root / manifest['file']), container + ':' + assets + manifest['file']])
assert sha(read(manifest['file'])) == manifest['after']
print('PASS: repaired sync-record dependency graph; no root/backend/worker changes')
