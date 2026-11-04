"""Frontend-only follow-up to the approved GMV collection-status overlay."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
FRONT = 'production-frontend-1'
ASSETS = '/usr/share/nginx/html/assets/'


def read(path):
    return subprocess.check_output(['docker', 'exec', FRONT, 'cat', path])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(path, data):
    subprocess.run(['docker', 'exec', '-i', FRONT, 'sh', '-c',
        'cat > "$1.coverage-tmp" && mv "$1.coverage-tmp" "$1"', 'sh', path], input=data, check=True)


if sys.argv[1] == 'prepare':
    receipt_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('/opt/saas-collab/production/hotfix-ads-collection-status-20261104-r1/receipt.json')
    previous = json.loads(receipt_path.read_text())
    previous_entry = next(c for c in previous['changes'] if c['container'] == FRONT) if 'changes' in previous else previous
    path = previous_entry['path']
    entry = read(path)
    assert sha(entry) == previous_entry['after'], 'Concurrent frontend update'
    wrappers = re.findall(rb'MarketingAdvertising-GmvStatus-[a-f0-9]+\.js', entry)
    assert len(wrappers) == 2 and wrappers[0] == wrappers[1]
    wrapper = read(ASSETS + wrappers[0].decode())
    old_modules = re.findall(rb'TikTokGmvStatus-[a-f0-9]+\.js', wrapper)
    assert len(old_modules) == 1
    module = (ROOT / 'module.js').read_bytes()
    for bindings, relative in re.findall(r'import\{([^}]+)\}from["\x27](\./[^"\x27]+)["\x27]', module.decode()):
        dependency = read(ASSETS + relative[2:]).decode()
        exports = re.findall(r'export\{([^}]+)\}', dependency)
        available = {v.strip().split(' as ')[-1] for group in exports for v in group.split(',')}
        required = {v.strip().split(' as ')[0] for v in bindings.split(',')}
        assert required <= available, (relative, required - available)
    name = 'TikTokGmvStatus-' + sha(module)[:12] + '.js'
    new_wrapper = wrapper.replace(old_modules[0], name.encode())
    wrapper_name = 'MarketingAdvertising-GmvStatus-' + sha(new_wrapper)[:12] + '.js'
    new_entry = entry.replace(wrappers[0], wrapper_name.encode())
    for file, content in [('before-entry.js', entry), ('before-wrapper.js', wrapper),
                          ('after-entry.js', new_entry), (name, module), (wrapper_name, new_wrapper)]:
        with (ROOT / file).open('xb') as output:
            output.write(content)
    plan = dict(path=path, before=sha(entry), after=sha(new_entry),
                html=sha(read('/usr/share/nginx/html/index.html')), assets=[name, wrapper_name],
                container_id=previous['container_ids'][FRONT] if 'container_ids' in previous else previous['container_id'])
    (ROOT / 'plan.json').write_text(json.dumps(plan, indent=2))
    print(json.dumps(plan))
elif sys.argv[1] == 'apply':
    plan = json.loads((ROOT / 'plan.json').read_text())
    assert not (ROOT / 'receipt.json').exists(), 'Do not reapply blindly'
    assert subprocess.check_output(['docker', 'inspect', '--format', '{{.Id}}', FRONT]).decode().strip() == plan['container_id']
    assert sha(read('/usr/share/nginx/html/index.html')) == plan['html']
    assert sha(read(plan['path'])) == plan['before']
    for name in plan['assets']:
        assert subprocess.run(['docker', 'exec', FRONT, 'test', '-e', ASSETS + name]).returncode != 0
    for name in plan['assets']:
        put(ASSETS + name, (ROOT / name).read_bytes())
    assert sha(read(plan['path'])) == plan['before']
    try:
        put(plan['path'], (ROOT / 'after-entry.js').read_bytes())
        assert sha(read(plan['path'])) == plan['after']
    except Exception:
        put(plan['path'], (ROOT / 'before-entry.js').read_bytes())
        raise
    (ROOT / 'receipt.json').write_text(json.dumps(plan, indent=2))
    print('APPLIED: frontend text/layout only; no backend reload or data changes')
else:
    raise SystemExit('Use prepare or apply')
