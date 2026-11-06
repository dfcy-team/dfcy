"""Scoped single-day video runner; never enables creator queries implicitly."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
LOCK = '/opt/saas-collab/production/hotfix-tk-video-sync-20261031/worker.lock'
SHOPS = (15, 67)


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def command(store):
    if store not in SHOPS:
        raise ValueError('Shop outside approved scope')
    return ['docker', 'exec', 'production-backend-1', 'python', 'manage.py',
            'sync_tiktok_shop_videos', '--actor-id', '1', '--tenant-id', '1',
            '--store-id', str(store), '--days', '1', '--apply', '--pause', '2']


def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    with open(LOCK, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Existing video worker active; no duplicate dispatched')
        manifest = json.loads((ROOT / 'tk_two_shop_manifest.json').read_text())
        if not manifest:
            raise SystemExit('Empty manifest')
        for path, expected in manifest.items():
            data = subprocess.check_output(['docker', 'exec', 'production-backend-1', 'cat', path])
            if digest(data) != expected:
                raise SystemExit('Source changed: ' + path)
        if args.check:
            print('CHECK_OK: tenant1 stores15,67; previous complete day; no refresh/backfill')
            return
        failed = []
        for store in SHOPS:
            if subprocess.run(command(store)).returncode:
                failed.append(store)
        if failed:
            raise SystemExit('Failed stores: ' + str(failed))


if __name__ == '__main__':
    main()
