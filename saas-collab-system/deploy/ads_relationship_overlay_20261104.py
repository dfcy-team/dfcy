"""CAS-guarded relationship overlay on the inspected status/display release."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BACK, FRONT = 'production-backend-1', 'production-frontend-1'
ASSETS = '/usr/share/nginx/html/assets/'
EXISTING = ['integrations/gmv_max_read.py', 'integrations/gmv_max_sync.py',
    'integrations/management/commands/sync_tiktok_gmv_max_recent.py', 'reports/tiktok_ads_services.py']
NEW = ['integrations/gmv_max_relationship.py', 'integrations/management/commands/verify_tiktok_gmv_relationships.py']


def read(container, path):
    return subprocess.check_output(['docker', 'exec', container, 'cat', path])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(container, path, data):
    subprocess.run(['docker', 'exec', '-i', container, 'sh', '-c',
        'cat > "$1.relation-tmp" && mv "$1.relation-tmp" "$1"', 'sh', path], input=data, check=True)


def node(source, name):
    return next(n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)


def replace(source, old, new):
    assert source.count(old) == 1, ('Anchor changed', old[:80])
    return source.replace(old, new)


def merged(name, live):
    source = live.decode().replace('\r\n', '\n')
    base = (ROOT / 'baseline/saas-collab-system/backend/apps' / name).read_text()
    target = (ROOT / 'candidate/backend/apps' / name).read_text()
    if name.endswith('tiktok_ads_services.py'):
        assert 'advertising_store_scope(user)' in source
        helper = ast.get_source_segment(target, node(target, '_gmv_relationship_report'))
        source = replace(source, 'def daily_spend_report(user, query):', helper + '\n\ndef daily_spend_report(user, query):')
        anchor = "            'gmv_max_shop_overview': shop_overview(rows, selected, query['date_from'], query['date_to']),"
        source = replace(source, anchor, anchor + "\n            **_gmv_relationship_report(user, visible, rows, selected, query),")
        anchor = '            "gmv_max_overview": overview(gmv_rows, query[\'date_from\'], query[\'date_to\']),'
        source = replace(source, anchor, anchor + '\n            **_gmv_relationship_report(user, visible, gmv_rows, selected_subjects, query),')
    else:
        func = 'stored_days' if name.endswith('gmv_max_read.py') else 'run_day' if name.endswith('gmv_max_sync.py') else 'Command'
        old = node(source, func)
        assert ast.dump(old) == ast.dump(node(base, func)), ('Live function changed', name)
        lines = source.splitlines(True)
        lines[old.lineno - 1:old.end_lineno] = [ast.get_source_segment(target, node(target, func)) + '\n']
        source = ''.join(lines)
        if func == 'Command':
            source += '\nfrom apps.integrations.gmv_max_relationship import probe_relationship\n'
    compile(source, name, 'exec')
    return source.encode()


if sys.argv[1] == 'prepare':
    (ROOT / 'backup').mkdir(exist_ok=False)
    (ROOT / 'after').mkdir(exist_ok=False)
    changes = []
    for index, name in enumerate(EXISTING):
        path = '/app/apps/' + name
        old = read(BACK, path)
        new = merged(name, old)
        (ROOT / 'backup' / str(index)).write_bytes(old)
        (ROOT / 'after' / str(index)).write_bytes(new)
        changes.append(dict(container=BACK, path=path, slot=str(index), before=sha(old), after=sha(new)))
    new_files = []
    for name in NEW:
        path = '/app/apps/' + name
        assert subprocess.run(['docker', 'exec', BACK, 'test', '-e', path]).returncode != 0, ('Already exists', path)
        data = (ROOT / 'candidate/backend/apps' / name).read_bytes()
        compile(data, name, 'exec')
        new_files.append(dict(path=path, source=name, sha256=sha(data)))
    prior = json.loads(Path('/opt/saas-collab/production/hotfix-ads-coverage-display-20261104-r2/receipt.json').read_text())
    entry = read(FRONT, prior['path'])
    assert sha(entry) == prior['after']
    wrappers = re.findall(rb'MarketingAdvertising-GmvStatus-[a-f0-9]+\.js', entry)
    assert len(wrappers) == 2 and wrappers[0] == wrappers[1]
    wrapper = read(FRONT, ASSETS + wrappers[0].decode())
    old_module = re.findall(rb'TikTokGmvStatus-[a-f0-9]+\.js', wrapper)
    assert len(old_module) == 1
    module = (ROOT / 'candidate/frontend/gmv-overlay/TikTokGmvOnly-20261104.js').read_bytes()
    for bindings, relative in re.findall(r'import\{([^}]+)\}from["\x27](\./[^"\x27]+)["\x27]', module.decode()):
        dependency = read(FRONT, ASSETS + relative[2:]).decode()
        exports = re.findall(r'export\{([^}]+)\}', dependency)
        available = {v.strip().split(' as ')[-1] for group in exports for v in group.split(',')}
        required = {v.strip().split(' as ')[0] for v in bindings.split(',')}
        assert required <= available, (relative, required - available)
    module_name = 'TikTokGmvStatus-' + sha(module)[:12] + '.js'
    wrapper_new = wrapper.replace(old_module[0], module_name.encode())
    wrapper_name = 'MarketingAdvertising-GmvStatus-' + sha(wrapper_new)[:12] + '.js'
    (ROOT / module_name).write_bytes(module)
    (ROOT / wrapper_name).write_bytes(wrapper_new)
    (ROOT / 'backup/entry.js').write_bytes(entry)
    (ROOT / 'after/entry.js').write_bytes(entry.replace(wrappers[0], wrapper_name.encode()))
    changes.append(dict(container=FRONT, path=prior['path'], slot='entry.js', before=sha(entry),
                        after=sha((ROOT / 'after/entry.js').read_bytes())))
    plan = dict(changes=changes, new_files=new_files, assets=[module_name, wrapper_name],
        html_sha=sha(read(FRONT, '/usr/share/nginx/html/index.html')),
        ids={c: subprocess.check_output(['docker','inspect','--format','{{.Id}}',c]).decode().strip() for c in [BACK, FRONT]})
    (ROOT / 'plan.json').write_text(json.dumps(plan, indent=2))
    print(json.dumps(plan))
elif sys.argv[1] == 'apply':
    plan = json.loads((ROOT / 'plan.json').read_text())
    assert not (ROOT / 'receipt.json').exists()
    assert sha(read(FRONT, '/usr/share/nginx/html/index.html')) == plan['html_sha']
    for c, identity in plan['ids'].items():
        assert subprocess.check_output(['docker','inspect','--format','{{.Id}}',c]).decode().strip() == identity
    for item in plan['changes']:
        assert sha(read(item['container'], item['path'])) == item['before'], ('Concurrent change', item['path'])
    for item in plan['new_files']:
        assert subprocess.run(['docker','exec',BACK,'test','-e',item['path']]).returncode != 0
    for name in plan['assets']:
        assert subprocess.run(['docker','exec',FRONT,'test','-e',ASSETS + name]).returncode != 0
    for item in plan['new_files']:
        data = (ROOT / 'candidate/backend/apps' / item['source']).read_bytes()
        assert sha(data) == item['sha256']
        put(BACK, item['path'], data)
    for name in plan['assets']:
        put(FRONT, ASSETS + name, (ROOT / name).read_bytes())
    applied = []
    try:
        for item in plan['changes']:
            assert sha(read(item['container'], item['path'])) == item['before']
            put(item['container'], item['path'], (ROOT / 'after' / item['slot']).read_bytes())
            applied.append(item)
            assert sha(read(item['container'], item['path'])) == item['after']
    except Exception:
        for item in reversed(applied):
            put(item['container'], item['path'], (ROOT / 'backup' / item['slot']).read_bytes())
        raise
    subprocess.run(['docker','exec',BACK,'python','-c','import os,signal;os.kill(1,signal.SIGHUP)'],check=True)
    (ROOT / 'receipt.json').write_text(json.dumps(plan, indent=2))
    print('APPLIED: ID relationship/coverage overlay; no binding changes or report amount writes')
else:
    raise SystemExit('Use prepare or apply')
