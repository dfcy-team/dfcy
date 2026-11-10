"""Publish a versioned sync page without replacing the existing app entrypoint.

One-shot CAS deployment. Only the HTML import map and a new page asset change.
The original page remains available for rollback; collectors and APIs are untouched.
"""
import hashlib
import json
import pathlib
import subprocess

root = pathlib.Path('/opt/saas-collab/production/operations/sync-evidence-versioned-20261110')
container = 'production-frontend-1'
webroot = '/usr/share/nginx/html/'
manifest = json.loads((root / 'manifest.json').read_text())

def read(name):
    return subprocess.check_output(['docker', 'exec', container, 'cat', webroot + name])

def sha(data):
    return hashlib.sha256(data).hexdigest()

html = read('index.html')
assert b'type="importmap"' not in html, 'Existing import map needs manual reconciliation'
assert html.count(b'<script type="module"') == 1
assert b'/assets/index-v404-665f2bafaee8.js' in html, 'Entrypoint changed'
assert sha(read('assets/index-v404-665f2bafaee8.js')) == '665f2bafaee86dda2752e8a56ae8fac7cf4537dce50a1afac96bb19f92849dfc'
assert sha(read('assets/' + manifest['file'])) == '0ef227fd7224be2e3ac61a0479aa8262df869ab3c24fa33ace076e65266424d0', 'Original page changed'
for name, expected in {**manifest['dependencies'], **manifest['additions']}.items():
    if name == 'index-BCq0YIA9.js':
        assert read('assets/' + name).strip() == b'export * from "./index-v403-32efbbb01679.js";'
        assert read('assets/index-v403-32efbbb01679.js').strip() == b'export * from "./index-v404-665f2bafaee8.js";'
    else:
        assert sha(read('assets/' + name)) == expected, 'Dependency changed: ' + name
candidate = (root / manifest['file']).read_bytes()
assert sha(candidate) == manifest['after']
filename = 'SyncExecutionRecords-evidence-' + sha(candidate)[:12] + '.js'
mapping = {'imports': {'/assets/' + manifest['file']: '/assets/' + filename}}
insertion = ('<script type="importmap">' + json.dumps(mapping, separators=(',', ':')) + '</script>\n    ').encode()
new_html = html.replace(b'<script type="module"', insertion + b'<script type="module"', 1)
backup = root / 'index.before.html'
assert not backup.exists(), 'Already attempted; inspect instead of repeating'
backup.write_bytes(html)
(root / 'index.after.html').write_bytes(new_html)
(root / filename).write_bytes(candidate)
subprocess.check_call(['docker', 'cp', str(root / filename), container + ':' + webroot + 'assets/' + filename])
assert sha(read('assets/' + filename)) == manifest['after']
assert read('index.html') == html, 'HTML changed concurrently; stop'
subprocess.check_call(['docker', 'cp', str(root / 'index.after.html'), container + ':' + webroot + 'index.sync-evidence.tmp'])
subprocess.check_call(['docker', 'exec', container, 'mv', webroot + 'index.sync-evidence.tmp', webroot + 'index.html'])
assert read('index.html') == new_html
print(json.dumps({'status': 'deployed', 'page': filename, 'html_sha256': sha(new_html), 'backup': str(backup)}))
