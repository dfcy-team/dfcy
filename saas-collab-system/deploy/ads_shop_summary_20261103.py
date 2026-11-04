"""Bounded, CAS-guarded overlay for the inspected Aliyun release only."""
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
JS = ASSETS + 'AdvertisingOverview-088lMSCV.js'
SERVICE = '/app/apps/reports/tiktok_ads_services.py'
HELPER = '/app/apps/integrations/gmv_max_overview.py'


def read(container, path):
    return subprocess.check_output(['docker', 'exec', container, 'cat', path])


def sha(data):
    return hashlib.sha256(data).hexdigest()


if '--apply' not in sys.argv:
    live = read(FRONT, JS)
    service = read(BACK, SERVICE)
    helper = read(BACK, HELPER)
    assert sha(live) == 'dfd0721cb40029dd506a6ab9f7b9f058cf1e07cea4bb938d3ce925326790189d'
    assert sha(service) == 'b223cf9ea9385993971a869eb28fe76533d3299e44ae6278c36e365d379a59d1'
    assert sha(helper) == '4b163037ce52315731eb3955d96e1da6dad4567080d9996a14f2dd5eded52686'
    built = (ROOT / 'built.js').read_text(encoding='utf-8')
    old_map = json.loads(Path('/opt/saas-collab/production/hotfix-ads-overview-20261102/dependency-map.json').read_text())
    modules = re.findall(r'(?:from|import)\s*["\x27](\./[^"\x27]+)["\x27]', built)[:18]
    normalize = lambda s: re.sub(r'-[A-Za-z0-9_-]{8}\.js$', '.js', s)
    pairs = dict(zip(modules, old_map.values()))
    for new, old in pairs.items():
        assert normalize(new) == normalize(old), (new, old)
        subprocess.run(['docker', 'exec', FRONT, 'test', '-f', ASSETS + old[2:]], check=True)
    imports, params, args = [], [], []
    for bindings, module in re.findall(r'import\{([^}]+)\}from"([^"]+)"', built):
        renamed = []
        for binding in bindings.split(','):
            exported, local = binding.split(' as ')
            alias = 'shopSummaryPatch_' + local
            renamed.append(exported + ' as ' + alias)
            params.append(local)
            args.append(alias)
        imports.append('import{' + ','.join(renamed) + '}from"' + pairs[module] + '";')
    end = re.search(r',\w+=\{__name:"AdvertisingOverview"', built).start()
    component = built[built.index('function '):end]
    match = re.search(r'(\w+)=\w+\(\w+,\[\["__scopeId","(data-v-[a-f0-9]+)"\]\]\)$', component)
    component_name = match.group(1)
    # This patch does not change CSS; keep the live component scope.
    component = component.replace(match.group(2), 'data-v-0ff39d79')
    wrapper = '\n'.join(imports) + '\nconst Ee=((' + ','.join(params) + ')=>{' + component + ';return ' + component_name + ';})(' + ','.join(args) + ');const '
    source = live.decode()
    after = source[:source.index('\nimport{')] + '\n' + wrapper + source[source.index('Ve={__name:"AdvertisingOverview"'):]
    updated = service.decode()
    anchor = '                 "mapping_timezone": m.timezone, "collection_enabled": m.enabled,'
    assert updated.count(anchor) == 1
    updated = updated.replace(anchor, anchor + '\n                 "historical_binding_confirmed": any(_locally_verified(m, [s], s.config_fingerprint) for s in sessions),')
    updated = updated.replace('import overview\n', 'import overview, shop_overview\n')
    anchor = '            "gmv_max_snapshots": gmv_rows,'
    assert updated.count(anchor) == 1
    updated = updated.replace(anchor, anchor + '\n            "gmv_max_shop_overview": shop_overview(gmv_rows, selected_subjects, query["date_from"], query["date_to"]),')
    compile(updated, SERVICE, 'exec')
    compile((ROOT / 'helper.py').read_text(), HELPER, 'exec')
    for name, data in [('before.js', live), ('before-service.py', service), ('before-helper.py', helper),
                       ('after.js', after.encode()), ('after-service.py', updated.encode()),
                       ('entry.html', read(FRONT, '/usr/share/nginx/html/index.html'))]:
        assert not (ROOT / name).exists(), 'Do not overwrite backups'
        (ROOT / name).write_bytes(data)
    print('Prepared; validate JavaScript before applying.')
    sys.exit(0)

changes = [(BACK, HELPER, 'helper.py', 'before-helper.py'),
           (BACK, SERVICE, 'after-service.py', 'before-service.py'),
           (FRONT, JS, 'after.js', 'before.js')]
assert read(FRONT, '/usr/share/nginx/html/index.html') == (ROOT / 'entry.html').read_bytes()
for container, path, source, backup in changes:
    assert read(container, path) == (ROOT / backup).read_bytes(), 'Concurrent change; abort'
receipt = []
for container, path, source, backup in changes:
    subprocess.run(['docker', 'cp', str(ROOT / source), container + ':' + path + '.shop-tmp'], check=True)
    subprocess.run(['docker', 'exec', container, 'mv', path + '.shop-tmp', path], check=True)
    assert read(container, path) == (ROOT / source).read_bytes()
    receipt.append(dict(container=container, path=path, sha256=sha(read(container, path)), backup=backup))
(ROOT / 'receipt.json').write_text(json.dumps(receipt, indent=2))
print('Installed. Gunicorn graceful reload required; do not restart the container.')
