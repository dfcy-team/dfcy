"""Read-only VM/cloud container credential consistency gate; prints no credentials."""
import hashlib,json,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
def service_names():
    all_names=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
    return sorted(n for n in all_names if any(n==prefix+'-backend-1' or n.startswith(prefix+'-celery-') for prefix in ('application','production')))
CODE="""import django;django.setup()
import hashlib,json,inspect
from pathlib import Path
from celery.signals import worker_init,beat_init
from apps.integrations.credential_access import checked_custody_backend,check_worker_credentials
from apps.integrations.production_settings import runtime_snapshot,validate_runtime_config,SAFE_DEFAULTS
from django.core.exceptions import ValidationError
r=runtime_snapshot()
backend=checked_custody_backend()
assert r['valid'] and r['source']=='database'
assert type(backend).__name__=='HttpCustodyBackend'
assert any(receiver is check_worker_credentials for key,receiver in worker_init.receivers)
assert any(receiver is check_worker_credentials for key,receiver in beat_init.receivers)
bad=dict(r['config']);bad['platforms']=dict(bad['platforms']);bad['platforms']['unknown_provider']={}
try:validate_runtime_config(bad)
except ValidationError:pass
else:raise AssertionError('UNKNOWN_PROVIDER_ACCEPTED')
assert SAFE_DEFAULTS['platforms']['best_ecapi']['contract_approved'] is False
from apps.integrations.readonly_clients import ShopeeReadonlyClient
assert 'retrieve_marketplace_credentials' in ShopeeReadonlyClient._request.__code__.co_names
print(json.dumps({'valid':True,'version':r['effective_version'],'custody_backend':type(backend).__name__,'helper_sha256':hashlib.sha256(Path('/app/apps/integrations/credential_access.py').read_bytes()).hexdigest(),'worker_startup_guard':True,'beat_startup_guard':True,'shared_readonly_credentials':True}))
"""
def verify_one(name):
    completed=subprocess.run(['docker','exec',name,'python','-c',CODE],capture_output=True,text=True)
    if completed.returncode:return name,{'valid':False,'error':'READINESS_CHECK_FAILED'}
    return name,json.loads(completed.stdout)
def verify(names=None):
    names=service_names() if names is None else names
    if not names:
        return {'status':'FAIL','services':{}}
    with ThreadPoolExecutor(max_workers=3) as pool:rows=dict(pool.map(verify_one,names))
    valid=all(row.get('valid') for row in rows.values())
    if valid:
        valid=len({row['version'] for row in rows.values()})==1 and len({row['helper_sha256'] for row in rows.values()})==1
    return {'status':'PASS' if valid else 'FAIL','services':rows}
if __name__=='__main__':
    result=verify()
    print(json.dumps(result))
    sys.exit(0 if result['status']=='PASS' else 1)
