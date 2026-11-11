"""Apply only PR505 source hunks to inspected live files, preserving hotfixes."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
live = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig'))
stage = root / 'stage'
stage.mkdir(parents=True, exist_ok=False)
for name, value in live.items():
    if not name.startswith('backend/'):
        continue
    p = stage / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(base64.b64decode(value))
patch = subprocess.check_output(['git', 'diff', '4c891fcb^', 'ea2d0fc9', '--', 'backend/apps/influencers'])
(root / 'source.patch').write_bytes(patch)
for flag in ['--check', None]:
    cmd = ['git', 'apply', '--unsafe-paths', '-p2'] + ([flag] if flag else []) + [str(root / 'source.patch')]
    subprocess.run(cmd, cwd=stage, check=True)
plan = []
def add(container, path, before, after):
    sha = lambda value: hashlib.sha256(value).hexdigest()
    plan.append({'container':container,'path':path,'before':sha(before) if before is not None else None,
                 'after':sha(after),'data':base64.b64encode(after).decode()})
for p in (stage/'backend').rglob('*.py'):
    data = p.read_bytes();compile(data,str(p),'exec')
    name = p.relative_to(stage).as_posix()
    before = base64.b64decode(live[name]) if name in live else None
    add('production-backend-1', '/app/'+name.removeprefix('backend/'), before, data)
asset = (root/'InfluencerList.js').read_bytes()
name = 'InfluencerList-archives-'+hashlib.sha256(asset).hexdigest()[:12]+'.js'
add('production-frontend-1','/usr/share/nginx/html/assets/'+name,None,asset)
entry = base64.b64decode(live['assets/index-CFS-lxl7.js'])
assert entry.count(b'InfluencerList-D8W-NjjE.js') == 2
add('production-frontend-1','/usr/share/nginx/html/assets/index-CFS-lxl7.js',entry,
    entry.replace(b'InfluencerList-D8W-NjjE.js',name.encode()))
(root/'plan.json').write_text(json.dumps(plan))
print(json.dumps([{k:v for k,v in row.items() if k!='data'} for row in plan],indent=2))
