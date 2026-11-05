"""Preserve current live views; patch only sampling draft country propagation."""
import hashlib
import json
from pathlib import Path
import subprocess

container = 'production-backend-1'
target = '/app/apps/influencers/views.py'
root = Path('/opt/saas-collab/production/hotfix-sampling-draft-country-20261105')
run = lambda *args: subprocess.check_output(args)
before = run('docker', 'exec', container, 'cat', target)
expected = '1485e223967ee9847e11a58d559898dcae5168af7ecbad1b11d3b874b751f238'
assert hashlib.sha256(before).hexdigest() == expected, 'Live views changed; rebase instead of overwriting'
assert not root.exists(), 'Do not replay a deployed hotfix'
old = '''        scope_store = None
        if allowed_countries(request.user, self.write_permission_code) is not None:
            store_id = request.data.get("store_id")
'''
new = '''        scope_store = None
        store_id = request.data.get("store_id")
        # Keep sampling drafts visible to country-scoped colleagues even when
        # the creator has all-scope access. Never trust an unchecked store ID.
        if store_id not in (None, "") or allowed_countries(request.user, self.write_permission_code) is not None:
'''
old_guard = '''            else:
                require_object(request.user, influencer, self.write_permission_code)
'''
new_guard = '''            elif allowed_countries(request.user, self.write_permission_code) is not None:
                require_object(request.user, influencer, self.write_permission_code)
'''
source = before.decode()
if '\r\n' in source:
    old, new, old_guard, new_guard = (value.replace('\n', '\r\n') for value in (old, new, old_guard, new_guard))
assert source.count(old) == source.count(old_guard) == 1
after = source.replace(old, new).replace(old_guard, new_guard).encode()
compile(after, target, 'exec')
root.mkdir(mode=0o700)
(root / 'views-before.py').write_bytes(before)
(root / 'views-after.py').write_bytes(after)
assert run('docker', 'exec', container, 'cat', target) == before
run('docker', 'cp', str(root / 'views-after.py'), container + ':' + target + '.stage')
run('docker', 'exec', container, 'chmod', '644', target + '.stage')
run('docker', 'exec', container, 'mv', target + '.stage', target)
assert run('docker', 'exec', container, 'cat', target) == after
run('docker', 'exec', container, 'python', '-c', 'import os,signal;os.kill(1,signal.SIGHUP)')
receipt = {'before': expected, 'after': hashlib.sha256(after).hexdigest(),
           'database_writes': 0, 'permission_changes': 0}
(root / 'receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
