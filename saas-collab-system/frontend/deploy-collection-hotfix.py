"""CAS-guarded narrow hotfix; no task/timer or worker changes."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text())
targets = [('production-backend-1', '/app/apps/integrations/views.py', 'views.py',
            'bcfdfa3d1c7e3ffb1d296e604f7864e0a7579abbd15a9b6339e50627c61280cd'),
           ('production-frontend-1', '/usr/share/nginx/html/assets/' + manifest['file'],
            manifest['file'], manifest['before'])]
def run(*args):
    return subprocess.check_output(args)
def digest(data):
    return hashlib.sha256(data).hexdigest()
backups = []
for container, dest, source, expected in targets:
    data = run('docker', 'exec', container, 'cat', dest)
    assert digest(data) == expected, 'Live source changed: ' + dest
    backup = root / (source + '.before')
    assert not backup.exists(), 'Already attempted; reconcile before retry'
    backup.write_bytes(data)
    backups.append((container, dest, source, expected))
helper = '/app/apps/integrations/collection_progress.py'
assert subprocess.run(['docker','exec','production-backend-1','test','-e',helper]).returncode == 1
run('docker','cp',str(root / 'collection_progress.py'),'production-backend-1:' + helper)
changed = []
try:
    for container, dest, source, expected in backups:
        assert digest(run('docker','exec',container,'cat',dest)) == expected
        temp = dest + '.collection-progress-new'
        run('docker','cp',str(root / source),container + ':' + temp)
        run('docker','exec',container,'mv',temp,dest)
        changed.append((container,dest,source))
    check = "from apps.integrations.collection_progress import store_collection_progress; from apps.integrations.models import MarketplaceStoreAuthorization; a=MarketplaceStoreAuthorization.objects.filter(tenant_id=1,platform='tiktok').first(); assert a; r=store_collection_progress(tenant_id=1,store_id=a.store_id,platform='tiktok',can_view=True); assert len(r)==2; print('READONLY_CHECK_OK',[(x['code'],x['latest_status']) for x in r])"
    print(run('docker','exec','production-backend-1','python','manage.py','shell','--no-imports','-c',check).decode())
except BaseException:
    for container,dest,source in reversed(changed):
        run('docker','cp',str(root / (source+'.before')),container+':'+dest)
    raise
run('docker','kill','--signal=HUP','production-backend-1')
receipt = {'status':'FILES_APPLIED_WEB_RELOAD_REQUESTED','files':[
    dict(container=c,path=d,sha256=digest(run('docker','exec',c,'cat',d))) for c,d,s in changed],
    'timers_changed':False,'collection_started':False}
(root/'receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
