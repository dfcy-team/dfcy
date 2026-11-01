"""Local release integration: checked production build and post-deploy notes receipt.

Does not deploy, allocate release numbers, or modify the official production ledger.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parents[1] / 'frontend'
NOTES = FRONTEND / 'src/data/releaseNotes.json'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['build', 'confirm'])
    parser.add_argument('--version', required=True)
    parser.add_argument('--history', required=True)
    parser.add_argument('--deployment-receipt')
    parser.add_argument('--url')
    parser.add_argument('--output')
    args = parser.parse_args()
    subprocess.run([sys.executable, str(HERE/'release_notes.py'), 'check', '--notes', str(NOTES), '--history', str(Path(args.history).resolve()), '--version', args.version], check=True)
    if args.command == 'build':
        env = {**os.environ, 'VITE_USE_MOCK': 'false', 'VITE_API_BASE_URL': ''}
        subprocess.run([shutil.which('npm.cmd' if os.name == 'nt' else 'npm') or 'npm', 'run', 'build'], cwd=FRONTEND, env=env, check=True)
        assert (FRONTEND/'dist/release-notes.json').read_bytes() == NOTES.read_bytes()
        return
    if not (args.deployment_receipt and args.url and args.output):
        parser.error('confirm requires --deployment-receipt --url --output')
    evidence = json.loads(Path(args.deployment_receipt).read_text(encoding='utf-8'))
    if evidence.get('status') != 'PASS' or evidence.get('version') != args.version:
        raise ValueError('Deployment controller must provide PASS with exact version; failed/pending deployments cannot register')
    if not args.url.startswith('https://'):
        raise ValueError('HTTPS release-notes.json URL required')
    request = urllib.request.Request(args.url, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=20) as response:
        live = response.read(1024 * 1024 + 1)
    if live != NOTES.read_bytes():
        raise ValueError('Live release notes differ from the verified source')
    normalized = {'status': 'PASS', 'version': args.version, 'release_notes_sha256': hashlib.sha256(live).hexdigest()}
    # Temporary evidence does not overwrite a previous successful receipt.
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        receipt = Path(folder)/'receipt.json'
        receipt.write_text(json.dumps(normalized), encoding='utf-8')
        subprocess.run([sys.executable, str(HERE/'release_notes.py'), 'finalize', '--notes', str(NOTES), '--version', args.version, '--receipt', str(receipt), '--output', str(Path(args.output).resolve())], check=True)

if __name__ == '__main__':
    main()
