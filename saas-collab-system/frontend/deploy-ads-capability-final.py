import pathlib
import subprocess
root = pathlib.Path('/opt/saas-collab/production/operations/ads-capability-20261110')
container, target = 'production-backend-1', '/app/apps/integrations/ads_capability_api.py'
def run(*args): return subprocess.check_output(args)
old = run('docker','exec',container,'cat',target)
assert old == (root/'ads_capability_api.after.py').read_bytes(), 'Concurrent change'
new = (root/'ads_capability_api.optimized.py').read_bytes()
compile(new,target,'exec')
run('docker','cp',str(root/'ads_capability_api.optimized.py'),container+':'+target+'.new')
run('docker','exec',container,'mv',target+'.new',target)
assert run('docker','exec',container,'cat',target) == new
run('docker','exec',container,'python','-c','import os,signal; os.kill(1,signal.SIGHUP)')
print('OPTIMIZED_WEB_RELOADED')
