"""One-release overlay: preserve live GMV-only/scope changes and fence every write."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BACK, FRONT = 'production-backend-1', 'production-frontend-1'
ASSETS = '/usr/share/nginx/html/assets/'
FILES = ['integrations/gmv_max_overview.py', 'integrations/gmv_max_read.py',
         'integrations/gmv_max_schedule.py', 'integrations/gmv_max_sync.py',
         'integrations/management/commands/sync_tiktok_gmv_max_recent.py',
         'reports/tiktok_ads_services.py']


def read(container, path):
    return subprocess.check_output(['docker', 'exec', container, 'cat', path])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(container, path, data):
    subprocess.run(['docker', 'exec', '-i', container, 'sh', '-c',
        'cat > "$1.ads-status-tmp" && mv "$1.ads-status-tmp" "$1"', 'sh', path],
        input=data, check=True)


def node(source, name):
    return next(n for n in ast.parse(source).body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)


def replace_node(live, base, target, name):
    old = node(live, name)
    assert ast.dump(old) == ast.dump(node(base, name)), ('Changed live function', name)
    lines = live.splitlines(True)
    lines[old.lineno - 1:old.end_lineno] = [ast.get_source_segment(target, node(target, name)) + '\n']
    return ''.join(lines)


def once(source, old, new):
    assert source.count(old) == 1, ('Anchor changed', old[:90])
    return source.replace(old, new)


def backend_after(name, data):
    live = data.decode('utf-8').replace('\r\n', '\n')
    base = (ROOT / 'baseline/saas-collab-system/backend/apps' / name).read_text(encoding='utf-8')
    target = (ROOT / 'candidate/backend/apps' / name).read_text(encoding='utf-8')
    if name.endswith('gmv_max_overview.py'):
        for func in ['overview', 'shop_overview']:
            live = replace_node(live, base, target, func)
    elif name.endswith('gmv_max_sync.py'):
        for func in ['summarize', 'run_day']:
            live = replace_node(live, base, target, func)
    elif name.endswith('gmv_max_schedule.py'):
        live = replace_node(live, base, target, 'safe_error_code')
    elif name.endswith('sync_tiktok_gmv_max_recent.py'):
        live = replace_node(live, base, target, 'Command')
        live += '\nfrom django.db import DatabaseError\nfrom apps.integrations.models import IntegrationAuditLog\n'
    elif name.endswith('gmv_max_read.py'):
        assert 'def collection_days(' not in live
        live += '\nfrom datetime import timedelta\n\n' + ast.get_source_segment(target, node(target, 'collection_days')) + '\n'
    else:
        assert "if query.get('report_type') == 'gmv_max':" in live
        assert 'advertising_store_scope(user)' in live
        helper = ast.get_source_segment(target, node(target, '_gmv_max_collection'))
        live = once(live, 'def daily_spend_report(user, query):', helper + '\n\ndef daily_spend_report(user, query):')
        live = once(live, "        return {\n            'scope': 'GMVMax'", "        collection, collection_warning = _gmv_max_collection(user, visible, names, rows, query)\n        return {\n            'scope': 'GMVMax'")
        live = once(live, "            'gmv_max_snapshots': rows,", "            'gmv_max_snapshots': rows,\n            'gmv_max_collection_days': collection,")
        live = once(live, "            'warnings': ([warning] if warning else [])", "            'warnings': ([warning] if warning else [])\n                + ([collection_warning] if collection_warning else [])")
        live = once(live, '    return {"scope": "BASIC/AUCTION_CAMPAIGN"', "    gmv_collection, collection_warning = _gmv_max_collection(user, visible, names, gmv_rows, query)\n    if collection_warning:\n        warnings.append(collection_warning)\n    return {\"scope\": \"BASIC/AUCTION_CAMPAIGN\"")
        live = once(live, '            "gmv_max_snapshots": gmv_rows,', '            "gmv_max_snapshots": gmv_rows,\n            "gmv_max_collection_days": gmv_collection,')
    compile(live, name, 'exec')
    return live.encode()


mode = sys.argv[1]
if mode == 'prepare':
    backup = ROOT / 'backup'
    backup.mkdir(exist_ok=False)
    after = ROOT / 'after'
    after.mkdir(exist_ok=False)
    changes = []
    for i, name in enumerate(FILES):
        path = '/app/apps/' + name
        old = read(BACK, path)
        new = backend_after(name, old)
        (backup / str(i)).write_bytes(old)
        (after / str(i)).write_bytes(new)
        changes.append(dict(container=BACK, path=path, before=sha(old), after=sha(new), slot=str(i)))
    entry_html = read(FRONT, '/usr/share/nginx/html/index.html')
    main_path = re.search(rb'src="(/assets/[^"]+)"', entry_html).group(1).decode()
    entry_path = '/usr/share/nginx/html' + main_path
    entry = read(FRONT, entry_path)
    wrapper_name = 'MarketingAdvertising-GmvOnly20261104.js'
    assert entry.count(wrapper_name.encode()) == 2
    wrapper_path = ASSETS + wrapper_name
    old_wrapper = read(FRONT, wrapper_path)
    assert old_wrapper.count(b'TikTokGmvOnly-20261104.js') == 1
    module = (ROOT / 'candidate/frontend/gmv-overlay/TikTokGmvOnly-20261104.js').read_bytes()
    module_name = 'TikTokGmvStatus-' + sha(module)[:12] + '.js'
    for bindings, relative in re.findall(r'import\{([^}]+)\}from["\x27](\./[^"\x27]+)["\x27]', module.decode()):
        dependency = read(FRONT, ASSETS + relative[2:]).decode()
        exports = re.findall(r'export\{([^}]+)\}', dependency)
        available = {v.strip().split(' as ')[-1] for group in exports for v in group.split(',')}
        required = {v.strip().split(' as ')[0] for v in bindings.split(',')}
        assert required <= available, (relative, required - available)
    new_wrapper = old_wrapper.replace(b'TikTokGmvOnly-20261104.js', module_name.encode())
    new_wrapper_name = 'MarketingAdvertising-GmvStatus-' + sha(new_wrapper)[:12] + '.js'
    (ROOT / module_name).write_bytes(module)
    (ROOT / new_wrapper_name).write_bytes(new_wrapper)
    (backup / 'entry.html').write_bytes(entry_html)
    (backup / 'wrapper.js').write_bytes(old_wrapper)
    (backup / 'entry.js').write_bytes(entry)
    (after / 'entry.js').write_bytes(entry.replace(wrapper_name.encode(), new_wrapper_name.encode()))
    changes.append(dict(container=FRONT, path=entry_path, before=sha(entry),
                        after=sha((after / 'entry.js').read_bytes()), slot='entry.js'))
    ids = {c: subprocess.check_output(['docker', 'inspect', '--format', '{{.Id}}', c]).decode().strip()
           for c in [BACK, FRONT]}
    plan = dict(changes=changes, container_ids=ids, html_sha=sha(entry_html),
                new_assets=[module_name, new_wrapper_name],
                created_at=datetime.now(timezone.utc).isoformat())
    (ROOT / 'plan.json').write_text(json.dumps(plan, indent=2))
    print(json.dumps(plan))
elif mode in ('apply', 'rollback'):
    plan = json.loads((ROOT / 'plan.json').read_text())
    assert sha(read(FRONT, '/usr/share/nginx/html/index.html')) == plan['html_sha'], 'Entry changed'
    for c, identity in plan['container_ids'].items():
        assert subprocess.check_output(['docker', 'inspect', '--format', '{{.Id}}', c]).decode().strip() == identity, 'Container changed'
    if mode == 'apply':
        assert not (ROOT / 'receipt.json').exists(), 'Already applied; do not retry blindly'
        for change in plan['changes']:
            assert sha(read(change['container'], change['path'])) == change['before'], ('Concurrent change', change['path'])
        for asset in plan['new_assets']:
            absent = subprocess.run(['docker', 'exec', FRONT, 'test', '-e', ASSETS + asset]).returncode != 0
            assert absent, ('Asset already exists', asset)
        for asset in plan['new_assets']:
            put(FRONT, ASSETS + asset, (ROOT / asset).read_bytes())
        applied = []
        try:
            for change in plan['changes']:
                assert sha(read(change['container'], change['path'])) == change['before']
                put(change['container'], change['path'], (ROOT / 'after' / change['slot']).read_bytes())
                applied.append(change)
                assert sha(read(change['container'], change['path'])) == change['after']
        except Exception:
            for change in reversed(applied):
                slot = 'entry.js' if change['container'] == FRONT else change['slot']
                put(change['container'], change['path'], (ROOT / 'backup' / slot).read_bytes())
            raise
        subprocess.run(['docker', 'exec', BACK, 'python', '-c', 'import os,signal;os.kill(1,signal.SIGHUP)'], check=True)
        (ROOT / 'receipt.json').write_text(json.dumps(plan, indent=2))
        print('APPLIED: bounded files and entry references only; index.html, mappings, timers unchanged')
    else:
        for change in plan['changes']:
            assert sha(read(change['container'], change['path'])) == change['after'], ('Later change; rollback blocked', change['path'])
        for change in reversed(plan['changes']):
            slot = 'entry.js' if change['container'] == FRONT else change['slot']
            put(change['container'], change['path'], (ROOT / 'backup' / slot).read_bytes())
        subprocess.run(['docker', 'exec', BACK, 'python', '-c', 'import os,signal;os.kill(1,signal.SIGHUP)'], check=True)
        print('ROLLED_BACK: verified reports and harmless new assets retained')
else:
    raise SystemExit('Use prepare, apply or rollback')
