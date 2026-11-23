"""Share the existing video lock; never overlap this added workload."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

mode = sys.argv[1]
assert mode in ('affiliate', 'creator')
root = Path(__file__).resolve().parent
with open('/opt/saas-collab/production/hotfix-tk-video-sync-20261031/worker.lock', 'a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Other recovery worker active; no duplicate dispatched')
    if os.getloadavg()[0] > 3:
        raise SystemExit('Load guard: postponed')
    for path, expected in json.loads((root / 'manifest.json').read_text()).items():
        content = subprocess.check_output(['docker', 'exec', 'production-backend-1', 'cat', path])
        if hashlib.sha256(content).hexdigest() != expected:
            raise SystemExit('Source changed; revalidate before ingestion: ' + path)
    with (root / 'nightly_worker.py').open('rb') as source:
        result = subprocess.run(['docker', 'exec', '-i', '-e', 'NIGHTLY_MODE=' + mode,
            'production-backend-1', 'nice', '-n', '10', 'python', 'manage.py', 'shell',
            '--no-imports'], stdin=source)
    raise SystemExit(result.returncode)
