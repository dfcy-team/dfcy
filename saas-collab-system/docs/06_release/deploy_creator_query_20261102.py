"""CAS-protected creator-query-only hotfix. Run on the production host."""
import hashlib
from pathlib import Path
import subprocess

root = Path('/opt/saas-collab/production/hotfix-creator-query-20261102')
files = {
    'apps/integrations/production_settings.py': '59eb67f4f4c5130f0dae14baa09a7dfad1ec8f1fe344223318f05f18fb2ee515',
    'apps/influencers/tiktok_creator_lookup.py': '152a863770dbcb50dc207b75a980b5547da12d1cf1b27fb3ed631fafd9182b64',
}
for path, digest in files.items():
    old = subprocess.check_output(['docker', 'exec', 'production-backend-1', 'cat', '/app/' + path])
    assert hashlib.sha256(old).hexdigest() == digest, 'Production drift: ' + path
    (root / (Path(path).name + '.before')).write_bytes(old)
for path in files:
    source = root / Path(path).name
    subprocess.run(['docker', 'cp', str(source), 'production-backend-1:/app/' + path], check=True)
    current = subprocess.check_output(['docker', 'exec', 'production-backend-1', 'cat', '/app/' + path])
    assert current == source.read_bytes()
print('Two files deployed and read back; approval remains unchanged.')
