"""Apply a reviewed additive hotfix package with CAS, backups and rollback.

Run on the host with a JSON package whose entries contain container, path,
before (SHA256 or null for absent files), after and base64 data. This does not
reload workers or modify business data. Activation is a separate checked step.
"""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def run(*args):
    return subprocess.run(args, check=True, capture_output=True).stdout


def current(container, path):
    result = subprocess.run(["docker", "exec", container, "cat", path], capture_output=True)
    if result.returncode == 0:
        return result.stdout
    exists = subprocess.run(["docker", "exec", container, "test", "-e", path])
    if exists.returncode == 1:
        return None
    raise RuntimeError("Cannot read " + path)


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def main():
    entries = json.loads(Path(sys.argv[1]).read_text())
    backup = Path(sys.argv[2]).resolve()
    if not str(backup).startswith('/opt/saas-collab/production/operations/sample-import-'):
        raise RuntimeError('Backup must use a dedicated sample-import operations directory')
    backup.mkdir(parents=True, exist_ok=False)
    backend_files = {'urls.py', 'views.py', 'services.py', 'sample_import_csv.py', 'sample_nickname.py', 'sample_import.py', 'sample_import_api.py'}
    seen = set()
    for i, entry in enumerate(entries):
        container, path = entry['container'], entry['path']
        allowed = (container == 'production-backend-1' and path.startswith('/app/apps/influencers/')
                   and path.removeprefix('/app/apps/influencers/') in backend_files)
        allowed |= container == 'production-frontend-1' and (
            path == '/usr/share/nginx/html/index.html'
            or (path.startswith('/usr/share/nginx/html/assets/sample-import-') and '..' not in path))
        if not allowed or (container, path) in seen:
            raise RuntimeError('Out-of-scope or duplicate target: ' + path)
        seen.add((container, path))
        data = base64.b64decode(entry['data'], validate=True)
        if len(data) > 10 * 1024 * 1024 or digest(data) != entry['after']:
            raise RuntimeError('Invalid payload: ' + path)
        old = current(container, path)
        if digest(old) != entry['before']:
            raise RuntimeError('Live file changed; abort before writes: ' + path)
        if old is not None:
            (backup / f'{i}.before').write_bytes(old)
        (backup / f'{i}.after').write_bytes(data)
    receipt = [{k: e[k] for k in ('container', 'path', 'before', 'after')} for e in entries]
    (backup / 'manifest.json').write_text(json.dumps(receipt, indent=2))
    applied = []
    try:
        for i, entry in enumerate(entries):
            if digest(current(entry['container'], entry['path'])) != entry['before']:
                raise RuntimeError('CAS changed during apply: ' + entry['path'])
            applied.append((i, entry))
            run('docker', 'cp', str(backup / f'{i}.after'), entry['container'] + ':' + entry['path'])
            if digest(current(entry['container'], entry['path'])) != entry['after']:
                raise RuntimeError('Readback failed: ' + entry['path'])
    except Exception:
        for i, entry in reversed(applied):
            # Do not overwrite a third party's concurrent patch during rollback.
            if digest(current(entry['container'], entry['path'])) != entry['after']:
                continue
            if entry['before'] is not None:
                run('docker', 'cp', str(backup / f'{i}.before'), entry['container'] + ':' + entry['path'])
            else:
                run('docker', 'exec', entry['container'], 'rm', '--', entry['path'])
        raise
    result = {'status': 'FILES_APPLIED_NOT_ACTIVATED', 'at': datetime.now(timezone.utc).isoformat(), 'files': receipt}
    (backup / 'receipt.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
