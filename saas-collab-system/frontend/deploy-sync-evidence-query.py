"""Add the read-only source selector to the existing workspace API allowlist."""
import hashlib
import pathlib
import subprocess

root = pathlib.Path('/opt/saas-collab/production/operations/sync-evidence-20261109')
target = '/app/apps/integrations/views.py'
data = subprocess.check_output(['docker', 'exec', 'production-backend-1', 'cat', target])
assert hashlib.sha256(data).hexdigest() == 'a4a6dd33ef32e6cca789b060f31bf90b606df341e74af1b8d1d094063e0b0083'
original = data
crlf = b'\r\n' in data
data = data.replace(b'\r\n', b'\n')
needle = b'def integration_workspace_view(request):\n    allowed_query = {\n'
assert data.count(needle) == 1
updated = data.replace(needle, needle + b'        "record_source",\n')
needle = b'    params = request.query_params\n    if request.query_params.get("store_id"):'
assert updated.count(needle) == 1
updated = updated.replace(needle, b"    params = request.query_params\n    if params.get('record_source', '') not in ('', 'video', 'creator'):\n        raise ValidationError('Unknown collection record source.')\n    if request.query_params.get(\"store_id\"):")
compile(updated, target, 'exec')
if crlf:
    updated = updated.replace(b'\n', b'\r\n')
(root / 'backup' / 'views.py').write_bytes(original)
(root / 'views.py').write_bytes(updated)
subprocess.check_call(['docker', 'cp', str(root / 'views.py'), 'production-backend-1:' + target])
assert subprocess.check_output(['docker', 'exec', 'production-backend-1', 'cat', target]) == updated
subprocess.check_call(['docker', 'kill', '--signal=HUP', 'production-backend-1'])
print('API query allowlist deployed; no collection workers changed')
