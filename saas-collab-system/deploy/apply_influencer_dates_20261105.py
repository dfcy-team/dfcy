"""Apply a reviewed date-only overlay, refusing changed production targets."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path('/opt/saas-collab/production/hotfix-influencer-dates-20261105')
plan = json.loads(Path(sys.argv[1]).read_text())
expected_ids = {'production-backend-1': '06a0e051addd', 'production-frontend-1': '12c237f23d16'}


def run(*args):
    return subprocess.check_output(args)


def read(item):
    return run('docker', 'exec', item['container'], 'cat', item['path'])


def write(item, data):
    tmp = root / 'stage'
    tmp.write_bytes(data)
    run('docker', 'cp', str(tmp), item['container'] + ':' + item['path'] + '.dates-stage')
    run('docker', 'exec', item['container'], 'chmod', '644', item['path'] + '.dates-stage')
    run('docker', 'exec', item['container'], 'mv', item['path'] + '.dates-stage', item['path'])


def digest(data):
    return hashlib.sha256(data).hexdigest()


for container, prefix in expected_ids.items():
    assert run('docker', 'inspect', '-f', '{{.Id}}', container).decode().strip().startswith(prefix)
assert not root.exists(), 'Existing deployment receipt: do not replay'
originals = {}
for index, item in enumerate(plan):
    data = base64.b64decode(item['data'])
    assert digest(data) == item['after']
    if item['path'].endswith('.py'):
        compile(data, item['path'], 'exec')
    if item['before'] is None:
        exists = subprocess.run(['docker', 'exec', item['container'], 'test', '-e', item['path']]).returncode == 0
        assert not exists, 'New target exists'
    else:
        originals[index] = read(item)
        assert digest(originals[index]) == item['before'], 'Concurrent target change'

root.mkdir(parents=True)
for index, data in originals.items():
    (root / f'backup-{index}').write_bytes(data)
(root / 'plan.json').write_text(json.dumps(plan))
changed = []
try:
    # Install the helper before its caller, and activate frontend routes last.
    order = sorted(range(len(plan)), key=lambda n: 0 if plan[n]['path'].endswith('/date_filters.py') else 2 if '/index-' in plan[n]['path'] else 1)
    for index in order:
        item = plan[index]
        if item['before'] is not None:
            assert digest(read(item)) == item['before'], 'Concurrent change before write'
        write(item, base64.b64decode(item['data']))
        changed.append(index)
        assert digest(read(item)) == item['after']
    run('docker', 'exec', 'production-backend-1', 'python', '-c', 'import os,signal;os.kill(1,signal.SIGHUP)')
except Exception:
    for index in reversed(changed):
        if index in originals and digest(read(plan[index])) == plan[index]['after']:
            write(plan[index], originals[index])
    run('docker', 'exec', 'production-backend-1', 'python', '-c', 'import os,signal;os.kill(1,signal.SIGHUP)')
    raise
receipt = [{k: v for k, v in p.items() if k != 'data'} for p in plan]
(root / 'receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps({'applied': True, 'receipt': str(root / 'receipt.json'), 'files': receipt}))
