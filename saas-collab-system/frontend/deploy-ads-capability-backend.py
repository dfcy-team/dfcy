"""Apply only the reviewed read-request configuration scope, with a rollback copy."""
import hashlib
import pathlib
import subprocess

root = pathlib.Path('/opt/saas-collab/production/operations/ads-capability-20261110')
root.mkdir(parents=True, exist_ok=True)
container = 'production-backend-1'
target = '/app/apps/integrations/ads_capability_api.py'
def run(*args):
    return subprocess.check_output(args)
old = run('docker', 'exec', container, 'cat', target)
source = old.decode()
assert 'from .production_settings import runtime_snapshot_scope' not in source
anchor = 'from .models import IntegrationAuditLog, TikTokAdsAdvertiserMapping\n'
line = '    return success_response({"items": [capability_row(m, request.user) for m in visible_mappings(request.user)]})'
assert source.count(anchor) == source.count(line) == 1
new = source.replace(anchor, anchor + 'from .production_settings import runtime_snapshot_scope\n').replace(line,
    '    # Reuse configuration only within this read; mutations still revalidate fresh state.\n'
    '    with runtime_snapshot_scope():\n    ' + line).encode()
compile(new, target, 'exec')
assert not (root / 'ads_capability_api.before.py').exists(), 'Already attempted; inspect first'
(root / 'ads_capability_api.before.py').write_bytes(old)
(root / 'ads_capability_api.after.py').write_bytes(new)
assert run('docker', 'exec', container, 'cat', target) == old
run('docker', 'cp', str(root / 'ads_capability_api.after.py'), container + ':' + target + '.new')
run('docker', 'exec', container, 'mv', target + '.new', target)
assert run('docker', 'exec', container, 'cat', target) == new
run('docker', 'exec', container, 'python', '-c', 'import os,signal; os.kill(1, signal.SIGHUP)')
print('WEB_RELOADED', hashlib.sha256(new).hexdigest())
