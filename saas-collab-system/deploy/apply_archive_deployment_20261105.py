"""Backup, bounded PR505 overlay, additive migration, then route activation."""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path('/opt/saas-collab/production/hotfix-archive-shopee-20261105')
BACK='production-backend-1';FRONT='production-frontend-1'
plan=json.loads(Path(sys.argv[1]).read_text())

def run(*args, data=None):
    return subprocess.check_output(args, input=data)

def read(c,p):return run('docker','exec',c,'cat',p)
def sha(data):return hashlib.sha256(data).hexdigest()
def write(item,data):
    p=ROOT/'stage-file';p.write_bytes(data)
    run('docker','cp',str(p),item['container']+':'+item['path']+'.archive-stage')
    run('docker','exec',item['container'],'chmod','644',item['path']+'.archive-stage')
    run('docker','exec',item['container'],'mv',item['path']+'.archive-stage',item['path'])
def shell(code):
    return run('docker','exec','-i',BACK,'python','manage.py','shell','-c','import sys;exec(sys.stdin.read())',data=code.encode())

assert not ROOT.exists(), 'Existing receipt: never replay this script'
for c,prefix in [(BACK,'06a0e051addd'),(FRONT,'12c237f23d16')]:
    assert run('docker','inspect','-f','{{.Id}}',c).decode().strip().startswith(prefix)
originals={}
for index,item in enumerate(plan):
    data=base64.b64decode(item['data']);assert sha(data)==item['after']
    if item['before'] is None:
        assert subprocess.run(['docker','exec',item['container'],'test','-e',item['path']]).returncode!=0
    else:
        originals[index]=read(item['container'],item['path']);assert sha(originals[index])==item['before'],item['path']
    if item['path'].endswith('.py'):compile(data,item['path'],'exec')
    if item['path'].endswith('.js') and 'InfluencerList-archives-' in item['path']:
        for bindings,name in re.findall(r'import\{([^}]+)\}from"\./([^"/]+)"',data.decode()):
            source=read(FRONT,'/usr/share/nginx/html/assets/'+name).decode()
            exported=set()
            for block in re.findall(r'export\{([^}]+)\}',source):
                for binding in block.split(','):
                    exported.add(binding.strip().split(' as ')[-1])
            for binding in bindings.split(','):
                requested=binding.strip().split(' as ')[0]
                assert requested in exported,(name,requested)
ROOT.mkdir(parents=True,mode=0o700)
(ROOT/'plan.json').write_text(json.dumps(plan))
for index,data in originals.items():(ROOT/f'backup-{index}').write_bytes(data)

backup_code='''
import gzip,json,os,hashlib
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction,connection
from apps.influencers.models import Influencer
os.umask(0o077)
with transaction.atomic():
 with connection.cursor() as c:
  c.execute('SET TRANSACTION READ ONLY')
  c.execute('SHOW CREATE TABLE influencers_influencer');schema=c.fetchone()[1]
 rows=list(Influencer.objects.filter(tenant_id=1).order_by('pk').values())
 body=json.dumps({'schema':schema,'rows':rows},cls=DjangoJSONEncoder,sort_keys=True).encode()
 with open('/tmp/archive-migration-before-20261105.json.gz','xb') as out:
  with gzip.GzipFile(fileobj=out,mode='wb') as f:f.write(body)
 print(json.dumps({'rows':len(rows),'legacy_sha256':hashlib.sha256(json.dumps(rows,cls=DjangoJSONEncoder,sort_keys=True).encode()).hexdigest()}))
'''
(ROOT/'database-before.txt').write_bytes(shell(backup_code))
run('docker','cp',BACK+':/tmp/archive-migration-before-20261105.json.gz',str(ROOT/'database-before.json.gz'))
changed=[]
try:
    # Workers are not restarted. Existing cached models are compatible with
    # additive fields; DB constraints prevent reactivation of deleted rows.
    for index,item in enumerate(plan):
        if item['container']!=BACK:continue
        if item['before'] is not None:assert sha(read(BACK,item['path']))==item['before']
        write(item,base64.b64decode(item['data']));changed.append(index)
    migration_code='''
from django.db import connection
from django.core.management import call_command
with connection.cursor() as c:c.execute('SET SESSION lock_wait_timeout=5')
call_command('migrate','influencers','0045_influencer_shopee_platform',interactive=False,verbosity=1)
'''
    (ROOT/'migration.txt').write_bytes(shell(migration_code))
    verification_code='''
import json,gzip,hashlib
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection,transaction
from django.db.migrations.recorder import MigrationRecorder
from apps.influencers.models import Influencer,InfluencerPlatformAccount
with transaction.atomic():
 with connection.cursor() as c:c.execute('SET TRANSACTION READ ONLY')
 assert MigrationRecorder.Migration.objects.filter(app='influencers',name='0045_influencer_shopee_platform').exists()
 assert 'shopee' in InfluencerPlatformAccount.Platform.values
 assert not Influencer.objects.filter(is_deleted=True).exists()
 before=json.loads(gzip.open('/tmp/archive-migration-before-20261105.json.gz','rt').read())['rows']
 fields=list(before[0]);ids=[r['id'] for r in before]
 after=list(Influencer.objects.filter(tenant_id=1,pk__in=ids).order_by('pk').values(*fields))
 fingerprint=lambda rows:hashlib.sha256(json.dumps(rows,cls=DjangoJSONEncoder,sort_keys=True).encode()).hexdigest()
 preserved=fingerprint(before)==fingerprint(after)
 print(json.dumps({'migration_applied':True,'shopee_supported':True,'deleted_rows':0,'legacy_fields_unchanged':preserved,'legacy_rows':len(before)}))
'''
    (ROOT/'database-after.txt').write_bytes(shell(verification_code))
    run('docker','exec',BACK,'python','-c','import os,signal;os.kill(1,signal.SIGHUP)')
    for index,item in enumerate(plan):
        if item['container']!=FRONT:continue
        if item['before'] is not None:assert sha(read(FRONT,item['path']))==item['before']
        write(item,base64.b64decode(item['data']));changed.append(index)
    for item in plan:assert sha(read(item['container'],item['path']))==item['after']
except Exception:
    for index in reversed(changed):
        item=plan[index]
        if index in originals and sha(read(item['container'],item['path']))==item['after']:
            write(item,originals[index])
    # Leave additive columns and successful migration receipts intact. Dropping
    # columns on an exception could destroy subsequent user data.
    run('docker','exec',BACK,'python','-c','import os,signal;os.kill(1,signal.SIGHUP)')
    (ROOT/'failed.txt').write_text('Stopped; original existing code restored where hashes matched. Inspect migration state before any retry.')
    raise
receipt=[{k:v for k,v in p.items() if k!='data'} for p in plan]
(ROOT/'receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps({'deployed':True,'receipt':str(ROOT/'receipt.json'),'database_backup_bytes':(ROOT/'database-before.json.gz').stat().st_size}))
