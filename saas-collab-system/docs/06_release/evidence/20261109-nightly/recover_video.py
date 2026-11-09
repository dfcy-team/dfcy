"""One-shot, hash-fenced operational repair. Does not modify application code."""
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/opt/saas-collab/production')
OLD = ROOT / 'hotfix-tk-video-sync-20261031'
TWO = ROOT / 'tk-two-shop-nightly-20261105'
MODEL = '/app/apps/influencers/models.py'
SYNC = '/app/apps/influencers/tiktok_video_sync.py'
MODEL_HASH = '940b062daf416fa46c7acd49f6ba094d7f2240caa01ef0783f3d33c889ba6063'
SYNC_HASH = 'b285ede26989115464d984badd17e05f5c064b8099fd55009d2cb523bebe307e'


def digest(b):
    return hashlib.sha256(b.replace(b'\r\n', b'\n')).hexdigest()


def main():
    with (OLD / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        changes = []
        for path in [OLD / 'runtime-manifest.json', TWO / 'tk_two_shop_manifest.json']:
            before = path.read_bytes()
            manifest = json.loads(before)
            for filename, expected in manifest.items():
                actual = digest(subprocess.check_output(['docker', 'exec', 'production-backend-1', 'cat', filename]))
                approved = MODEL_HASH if filename == MODEL else SYNC_HASH if filename == SYNC else expected
                if actual != approved:
                    raise RuntimeError('Unreviewed source: ' + filename)
                manifest[filename] = actual
            changes.append((path, before, json.dumps(manifest, indent=2).encode()))
        path = OLD / 'run_tk_video_nightly_20261031.py'
        before = path.read_bytes()
        code = before.decode()
        assert "'--all-authorized', '--days', '30', '--apply', '--pause', '2'" in code
        assert "if '--initial' not in sys.argv:\n    command.append('--refresh')" in code
        code = code.replace("'--all-authorized', '--days', '30', '--apply', '--pause', '2'",
                            "'--all-authorized', '--days', '7', '--apply', '--pause', '10'")
        code = code.replace("if '--initial' not in sys.argv:\n    command.append('--refresh')",
                            "# Missing complete days only; completed batches are idempotently skipped.")
        compile(code, str(path), 'exec')
        changes.append((path, before, code.encode()))
        for path, before, after in changes:
            assert path.read_bytes() == before
            backup = path.with_name(path.name + '.before-20261109')
            with backup.open('xb') as f:
                f.write(before)
            temp = path.with_name(path.name + '.pending-20261109')
            with temp.open('xb') as f:
                f.write(after)
            temp.replace(path)
            assert path.read_bytes() == after
            print('VERIFIED', path.name, flush=True)


if __name__ == '__main__':
    main()
