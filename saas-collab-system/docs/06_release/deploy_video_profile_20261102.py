"""Bounded production patch; refuse changed source or active video workers."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path('/opt/saas-collab/production/hotfix-video-profile-20261102')
def run(*args):return subprocess.check_output(args)
def digest(data):return hashlib.sha256(data).hexdigest()
target='/app/apps/influencers/tiktok_video_sync.py'
old=run('docker','exec','production-backend-1','cat',target)
expected='de566500c8a8bee8e8c44fad8e7f2e474512136b9526c9153035b41875964e30'
if digest(old)!=expected:raise SystemExit('Video source drift; no overwrite.')
for unit in ('saas-tk-video-nightly.service','saas-tk-video-backfill-20261031.service','saas-tk-video-resume-20261031.service'):
    state=run('systemctl','show',unit,'-p','ActiveState','--value').decode().strip()
    if state in ('active','activating','deactivating'):raise SystemExit('Video worker is active.')
manifest_path=Path('/opt/saas-collab/production/hotfix-tk-video-sync-20261031/runtime-manifest.json')
manifest_before=manifest_path.read_bytes()
manifest=json.loads(manifest_before)
if manifest.get(target)!=expected:raise SystemExit('Unexpected video manifest.')
asset='/usr/share/nginx/html/assets/InfluencerList-BbjPKNMM.js'
js=run('docker','exec','production-frontend-1','cat',asset)
needle='e[83]||(e[83]=m("h3",null,"历史经营指标",-1))'
insert='''m("h3",null,"API 视频关联（已核对）"),m("p",{class:"muted"},"按同店铺已登记视频 ID 核对达人；不是按昵称自动认领。这里只展示正式入库覆盖，不代表全部视频或已完成送样。"),Object.keys(f.value.profile?.historical_performance?.api_video_observations||{}).length?m("div",null,Object.entries(f.value.profile.historical_performance.api_video_observations).map(([code,item])=>m("p",{key:code},code+"："+item.video_count+" 个视频，"+item.daily_rows+" 条日指标；"+item.first_date+" 至 "+item.last_date))):m("p",{class:"muted"},"尚无通过身份核对的 API 视频关联记录。"),'''
source=js.decode()
if source.count(needle)!=1:raise SystemExit('Unexpected frontend chunk.')
after=source.replace(needle,insert+needle).encode()
if '--apply' not in sys.argv:
    (ROOT/'video.before.py').write_bytes(old)
    (ROOT/'manifest.before.json').write_bytes(manifest_before)
    (ROOT/'frontend.before.js').write_bytes(js)
    (ROOT/'frontend.after.js').write_bytes(after)
    print('Prepared; check frontend.after.js syntax before --apply.')
else:
    if (ROOT/'video.before.py').read_bytes()!=old or (ROOT/'frontend.before.js').read_bytes()!=js:
        raise SystemExit('Prepared backups do not match production.')
    if (ROOT/'frontend.after.js').read_bytes()!=after:raise SystemExit('Prepared asset differs.')
    for name,destination in (
        ('tiktok_video_sync.py',target),
        ('video_registered_reconcile.py','/app/apps/influencers/video_registered_reconcile.py'),
        ('reconcile_registered_tiktok_videos.py','/app/apps/influencers/management/commands/reconcile_registered_tiktok_videos.py')):
        subprocess.check_call(['docker','cp',str(ROOT/name),'production-backend-1:'+destination])
        if digest(run('docker','exec','production-backend-1','cat',destination))!=digest((ROOT/name).read_bytes()):
            raise SystemExit('Backend readback differs.')
    manifest[target]=digest((ROOT/'tiktok_video_sync.py').read_bytes())
    if manifest_path.read_bytes()!=manifest_before:raise SystemExit('Manifest changed concurrently.')
    pending=manifest_path.with_suffix('.pending')
    pending.write_text(json.dumps(manifest,indent=2));pending.replace(manifest_path)
    subprocess.check_call(['docker','cp',str(ROOT/'frontend.after.js'),'production-frontend-1:'+asset+'.pending'])
    subprocess.check_call(['docker','exec','production-frontend-1','mv',asset+'.pending',asset])
    if run('docker','exec','production-frontend-1','cat',asset)!=after:raise SystemExit('Frontend readback differs.')
    (ROOT/'receipt.json').write_text(json.dumps({'video_before':expected,'video_after':manifest[target],
        'frontend_before':digest(js),'frontend_after':digest(after),'restart':False},indent=2))
    print('Deployed and read back; no service restart.')
