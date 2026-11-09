"""Scoped gate hotfix; never enables a capability or starts collection."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parent
def run(*a): return subprocess.check_output(a)
def sha(b): return hashlib.sha256(b).hexdigest()
def shell(code): return run('docker','exec','production-backend-1','python','manage.py','shell','--no-imports','-c',code).decode()
items = [
 ('models.py','/app/apps/integrations/models.py','3df2b0d2e0dcdb323024fcd2dba5e5451586378d71522a0484376628a2e9d24f'),
 ('views.py','/app/apps/integrations/views.py','0f54ccd20ed86376ab95765ebea0e58be179f631486c5631d65ae9afde05c0f3'),
 ('tiktok_creator_lookup.py','/app/apps/influencers/tiktok_creator_lookup.py','697541fc8cb049b23090740d0c877f86b47887210ecc0cad4a87a038d882a499'),
 ('tiktok_video_sync.py','/app/apps/influencers/tiktok_video_sync.py','b285ede26989115464d984badd17e05f5c064b8099fd55009d2cb523bebe307e'),
]
new = [('creator_video_capability.py','/app/apps/integrations/creator_video_capability.py'),
       ('0061_creator_video_capability_choices.py','/app/apps/integrations/migrations/0061_creator_video_capability_choices.py')]
print(shell("from django.db.migrations.recorder import MigrationRecorder; assert MigrationRecorder.Migration.objects.filter(app='integrations',name='0060_gmv_max_audit_lookup_index').exists(); print('MIGRATION_BASE_OK')"))
for src,dest,expected in items:
    content=run('docker','exec','production-backend-1','cat',dest)
    assert sha(content)==expected, dest
    assert not (root/(src+'.before')).exists(), 'Already attempted'
    (root/(src+'.before')).write_bytes(content)
for src,dest in new:
    assert subprocess.run(['docker','exec','production-backend-1','test','-e',dest]).returncode==1
page='/usr/share/nginx/html/assets/IntegrationCapabilityMatrix-F6iz7urt.js'
oldpage=run('docker','exec','production-frontend-1','cat',page)
assert sha(oldpage)=='9e9878049cbdad6f250504fdd2c50b15d36362acc24eacdf7a165b8774c6d460'
(root/'page.before').write_bytes(oldpage)
for src,dest in [(s,d) for s,d,_ in items]+new:
    run('docker','cp',str(root/src),'production-backend-1:'+dest+'.new')
    run('docker','exec','production-backend-1','mv',dest+'.new',dest)
try:
    sql=run('docker','exec','production-backend-1','python','manage.py','sqlmigrate','integrations','0061').decode()
    assert not any(x in sql.upper() for x in ['ALTER TABLE','CREATE TABLE','DROP TABLE','UPDATE ']),sql
    print(shell("from apps.integrations.models import ConnectionCapability; from apps.integrations.serializers import ConnectionCapabilityWriteSerializer; assert 'VIDEO' in ConnectionCapability.CapabilityCode.values; s=ConnectionCapabilityWriteSerializer(data=dict(capability_code='VIDEO',read_enabled=True,write_enabled=False,sync_mode='manual',source_priority=100,status='active')); assert s.is_valid(),s.errors; print('SERIALIZER_OK')"))
    print(run('docker','exec','production-backend-1','python','manage.py','migrate','integrations','0061','--noinput').decode())
except BaseException:
    for src,dest,_ in items:
        run('docker','cp',str(root/(src+'.before')),'production-backend-1:'+dest)
    raise
run('docker','cp',str(root/'IntegrationCapabilityMatrix-F6iz7urt.js'),'production-frontend-1:'+page+'.new')
run('docker','exec','production-frontend-1','mv',page+'.new',page)
# Update only hashes for reviewed files; preserve unrelated drift and all schedules.
manifest_paths=[
 '/opt/saas-collab/production/hotfix-tk-video-sync-20261031/runtime-manifest.json',
 '/opt/saas-collab/production/tk-two-shop-nightly-20261105/tk_two_shop_manifest.json',
 '/opt/saas-collab/production/nightly-recovery-20261109/manifest.json']
for index,p in enumerate(manifest_paths):
    path=Path(p); raw=path.read_bytes(); data=json.loads(raw)
    for src,dest,expected in items:
        if dest in data:
            assert data[dest]==expected, 'Manifest drift: '+dest
            data[dest]=sha((root/src).read_bytes())
    (root/f'manifest-{index}.before').write_bytes(raw)
    data['/app/apps/integrations/creator_video_capability.py']=sha((root/'creator_video_capability.py').read_bytes())
    path.write_text(json.dumps(data,indent=2))
run('docker','kill','--signal=HUP','production-backend-1')
receipt={'status':'GATES_APPLIED','capabilities_enabled':False,'tasks_started':False,
         'page_sha256':sha(run('docker','exec','production-frontend-1','cat',page))}
(root/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
