"""CAS-guarded ads-only overlay; retain the live entry and shared modules."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
FRONT = 'production-frontend-1'
BACK = 'production-backend-1'
ASSETS = '/usr/share/nginx/html/assets/'
JS = 'AdvertisingOverview-088lMSCV.js'
CSS = 'AdvertisingOverview-BAgiEk4g.css'
SERVICE = '/app/apps/reports/tiktok_ads_services.py'
HELPER = '/app/apps/integrations/gmv_max_overview.py'


def read(container, path):
    return subprocess.check_output(['docker', 'exec', container, 'cat', path])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def modules(source):
    return re.findall(r'(?:from|import)\s*[\"\x27](\./[^\"\x27]+)[\"\x27]', source)


if '--apply' not in sys.argv:
    before_js = read(FRONT, ASSETS + JS)
    before_css = read(FRONT, ASSETS + CSS)
    before_service = read(BACK, SERVICE)
    assert sha(before_js) == '1dba7c0b043cdafb2f3a32a6dc990b12af2bc03d1823af75e38f075e8ff1348d'
    assert sha(before_service) == 'ce6fa55884ebaeabfde2312dc9bd503a1e328fd5adcf2c6074aa8f28c8f32b34'
    assert subprocess.run(['docker', 'exec', BACK, 'test', '-e', HELPER]).returncode != 0
    built = (ROOT / 'built.js').read_text(encoding='utf-8')
    current_modules, built_modules = modules(before_js.decode()), modules(built)
    # Only transplant the rebuilt TikTok component. Preserve the live parent,
    # sibling reports and all their side-effect imports exactly as deployed.
    pairs = dict(zip(built_modules[:18], current_modules[:18]))
    for new, old in pairs.items():
        # Hashes differ because this worktree is not the full current production tree.
        assert re.sub(r'-[A-Za-z0-9_-]{8}\.js$', '.js', new) == re.sub(r'-[A-Za-z0-9_-]{8}\.js$', '.js', old), (new, old)
        assert subprocess.run(['docker', 'exec', FRONT, 'test', '-f', ASSETS + old[2:]]).returncode == 0
    imports, params, args = [], [], []
    for bindings, module in re.findall(r'import\{([^}]+)\}from"([^"]+)"', built):
        assert module in pairs
        renamed = []
        for binding in bindings.split(','):
            exported, local = binding.split(' as ')
            alias = 'adsOverviewPatch_' + local
            renamed.append(exported + ' as ' + alias)
            params.append(local)
            args.append(alias)
        imports.append('import{' + ','.join(renamed) + '}from"' + pairs[module] + '";')
    component = built[built.index('function q('):built.index(',Me={__name:"AdvertisingOverview"')]
    assert 'gmv_max_overview' in component
    wrapper = '\n'.join(imports) + '\nconst Ee=((' + ','.join(params) + ')=>{' + component + ';return ke;})(' + ','.join(args) + ');const '
    live = before_js.decode()
    built = live[:live.index('const we={__name:"TikTokAdsDailySpendOverview"')] + wrapper + live[live.index('Ve={__name:"AdvertisingOverview"'):]
    assert set(modules(built)) == set(current_modules)
    service = before_service.decode()
    anchor = '    return {"scope": "BASIC/AUCTION_CAMPAIGN"'
    assert service.count(anchor) == 1
    service = service.replace(anchor, '    from apps.integrations.gmv_max_overview import overview\n' + anchor)
    anchor = '            "gmv_max_snapshots": gmv_rows,'
    assert service.count(anchor) == 1
    service = service.replace(anchor, anchor + '\n            "gmv_max_overview": overview(gmv_rows, query["date_from"], query["date_to"]),')
    for name, data in [('before.js', before_js), ('before.css', before_css),
                       ('before-service.py', before_service), ('after.js', built.encode()),
                       ('after-service.py', service.encode())]:
        target = ROOT / name
        assert not target.exists(), 'Prepare only once; retain evidence'
        target.write_bytes(data)
    (ROOT / 'entry-before.html').write_bytes(read(FRONT, '/usr/share/nginx/html/index.html'))
    (ROOT / 'dependency-map.json').write_text(json.dumps(pairs, indent=2))
    print('Prepared. Validate after.js and Python before --apply.')
    sys.exit(0)

assert read(FRONT, '/usr/share/nginx/html/index.html') == (ROOT / 'entry-before.html').read_bytes()
changes = [(BACK, HELPER, 'gmv_max_overview.py', None),
           (BACK, SERVICE, 'after-service.py', 'before-service.py'),
           (FRONT, ASSETS + CSS, 'built.css', 'before.css'),
           (FRONT, ASSETS + JS, 'after.js', 'before.js')]
for container, path, source, backup in changes:
    if backup:
        assert read(container, path) == (ROOT / backup).read_bytes(), 'Concurrent change; stop'
    else:
        assert subprocess.run(['docker', 'exec', container, 'test', '-e', path]).returncode != 0
receipt = []
for container, path, source, backup in changes:
    subprocess.run(['docker', 'cp', str(ROOT / source), container + ':' + path + '.ads-tmp'], check=True)
    subprocess.run(['docker', 'exec', container, 'mv', path + '.ads-tmp', path], check=True)
    data = read(container, path)
    assert data == (ROOT / source).read_bytes()
    receipt.append({'container': container, 'path': path, 'sha256': sha(data), 'backup': backup})
assert read(FRONT, '/usr/share/nginx/html/index.html') == (ROOT / 'entry-before.html').read_bytes()
(ROOT / 'receipt.json').write_text(json.dumps(receipt, indent=2))
print('Ads-only files installed and verified. Entry unchanged; backend graceful reload required.')
