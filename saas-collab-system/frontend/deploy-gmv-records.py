"""One-shot, narrow additive display hotfix with backup and concurrent-change fences."""
import hashlib
import json
import pathlib
import re
import subprocess
root=pathlib.Path('/opt/saas-collab/production/operations/gmv-records-20261110')
backend='production-backend-1'
frontend='production-frontend-1'
web='/usr/share/nginx/html/'
def run(*args): return subprocess.check_output(args)
def read(container,path): return run('docker','exec',container,'cat',path)
def sha(data): return hashlib.sha256(data).hexdigest()
assert not (root/'receipt.json').exists(), 'Already deployed'
changes={
 'views.py':("not in ('', 'video', 'creator'):","not in ('', 'video', 'creator', 'gmv_max'):"),
 'workspace_service.py':("params.get('record_source') in ('video', 'creator'):","params.get('record_source') in ('video', 'creator', 'gmv_max'):"),
 'collection_records.py':('def collection_records(user, params):',
    "def collection_records(user, params):\n    if params.get('record_source') == 'gmv_max':\n        from .gmv_max_records import gmv_max_records\n        return gmv_max_records(user, params)")}
prepared=[]
for file,(old,new) in changes.items():
    target='/app/apps/integrations/'+file
    before=read(backend,target)
    assert before.decode().count(old)==1, file
    after=before.decode().replace(old,new).encode()
    compile(after,target,'exec')
    assert not (root/(file+'.before')).exists(), 'Previous attempt; inspect before retry'
    (root/(file+'.before')).write_bytes(before)
    (root/(file+'.after')).write_bytes(after)
    prepared.append((target,before,root/(file+'.after')))
new_module=(root/'gmv_max_records.py').read_bytes()
compile(new_module,'gmv_max_records.py','exec')
assert subprocess.run(['docker','exec',backend,'test','-e','/app/apps/integrations/gmv_max_records.py']).returncode==1
html=read(frontend,web+'index.html')
assert sha(html)=='392dbdcb33894705619c9f0bd72620d3d07fda3086ce6a022f94841b9a6f5f4f','HTML changed'
m=json.loads((root/'manifest.json').read_text())
for name,digest in m['dependencies'].items():
    if name=='index-BCq0YIA9.js':
        assert read(frontend,web+'assets/'+name).strip()==b'export * from "./index-v403-32efbbb01679.js";'
    else: assert sha(read(frontend,web+'assets/'+name))==digest,name
assert read(frontend,web+'assets/index-v403-32efbbb01679.js').strip()==b'export * from "./index-v404-665f2bafaee8.js";'
assert sha(read(frontend,web+'assets/index-v404-665f2bafaee8.js'))=='665f2bafaee86dda2752e8a56ae8fac7cf4537dce50a1afac96bb19f92849dfc'
page=(root/m['file']).read_bytes()
assert sha(page)==m['after']
name='SyncExecutionRecords-gmv-'+sha(page)[:12]+'.js'
(root/name).write_bytes(page)
for file,digest in {**m['additions'],name:sha(page)}.items():
    assert sha((root/file).read_bytes())==digest
    run('docker','cp',str(root/file),frontend+':'+web+'assets/'+file)
match=re.search(rb'<script type="importmap">(.*?)</script>',html)
mapping=json.loads(match[1])
mapping['imports']['/assets/'+m['file']]='/assets/'+name
after_html=html[:match.start(1)]+json.dumps(mapping,separators=(',',':')).encode()+html[match.end(1):]
(root/'index.before.html').write_bytes(html)
(root/'index.after.html').write_bytes(after_html)
for target,before,after in prepared:
    assert read(backend,target)==before,'Concurrent backend change'
    run('docker','cp',str(after),backend+':'+target+'.new')
    run('docker','exec',backend,'mv',target+'.new',target)
run('docker','cp',str(root/'gmv_max_records.py'),backend+':/app/apps/integrations/gmv_max_records.py')
run('docker','exec',backend,'python','-c','import os,signal; os.kill(1,signal.SIGHUP)')
assert read(frontend,web+'index.html')==html
run('docker','cp',str(root/'index.after.html'),frontend+':'+web+'index.gmv.tmp')
run('docker','exec',frontend,'mv',web+'index.gmv.tmp',web+'index.html')
assert read(frontend,web+'index.html')==after_html
receipt={'page':name,'html_sha256':sha(after_html),'collectors_restarted':False,'tasks_created':0}
(root/'receipt.json').write_text(json.dumps(receipt))
print(json.dumps(receipt))
