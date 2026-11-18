"""Apply only the corrected archive component, with entry CAS and rollback."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

container = 'production-frontend-1'
root = Path('/opt/saas-collab/production/hotfix-archive-api-20261105')
entry = '/usr/share/nginx/html/assets/index-CFS-lxl7.js'
expected = '8a79b7eebe6a5ca73447fdc73a84e71405542128ad4bfc6ecd6b7748d19bcf58'
old_name = 'InfluencerList-archives-41eab5a57852.js'
run = lambda *args: subprocess.check_output(args)
digest = lambda data: hashlib.sha256(data).hexdigest()
data = base64.b64decode(sys.argv[1], validate=True)
before = run('docker', 'exec', container, 'cat', entry)
assert digest(before) == expected, 'Live entry changed; stop rather than overwrite'
assert before.count(old_name.encode()) == 2
assert not root.exists(), 'Never replay an existing deployment receipt'
root.mkdir(mode=0o700)
(root / 'entry-before.js').write_bytes(before)
name = 'InfluencerList-archives-' + digest(data)[:12] + '.js'
after = before.replace(old_name.encode(), name.encode())


def install(content, target):
    stage = root / 'stage.js'
    stage.write_bytes(content)
    run('docker', 'cp', str(stage), container + ':' + target + '.stage')
    run('docker', 'exec', container, 'chmod', '644', target + '.stage')
    run('docker', 'exec', container, 'mv', target + '.stage', target)
    assert run('docker', 'exec', container, 'cat', target) == content


install(data, '/usr/share/nginx/html/assets/' + name)
assert digest(run('docker', 'exec', container, 'cat', entry)) == expected
try:
    install(after, entry)
except Exception:
    install(before, entry)
    raise
receipt = {'entry': entry, 'before': expected, 'after': digest(after),
           'component': name, 'component_sha256': digest(data), 'database_writes': 0}
(root / 'receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
