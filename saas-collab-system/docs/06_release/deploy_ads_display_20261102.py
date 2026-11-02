"""Bounded advertising-only asset patch. No app entry or account changes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

container = 'production-frontend-1'
asset = '/usr/share/nginx/html/assets/AdvertisingOverview-DxaI_qd7.js'
root = Path('/opt/saas-collab/production/hotfix-ads-display-20261102')
def read():
    return subprocess.check_output(['docker', 'exec', container, 'cat', asset])
old = read()
text = old.decode()
changes = {
    'GMV Max 已存单日快照': 'GMV Max 广告数据（已入库）',
    '仅展示已采集快照，不触发同步；不与下方 BASIC 消耗或商城 GMV 合计，不同币种分开查看。': '按店铺、广告主、报表时区和完整日期核对；默认不含今天。ROI=报表收入/消耗，平均订单成本=消耗/报表订单数，分母为零显示破折号。不与 BASIC 或商城 GMV 合计。',
    'BASIC 竞价广告日消耗': 'BASIC 竞价消耗（不含 GMV Max；为零不代表全部广告为零）',
    'e(a,{prop:"orders",label:"报表订单"})': 'e(a,{prop:"orders",label:"报表订单"}),e(a,{label:"ROI",formatter:t=>advertisingRatio(t.gross_revenue,t.cost)}),e(a,{label:"平均订单成本",formatter:t=>advertisingRatio(t.cost,t.orders)})',
}
for before, after in changes.items():
    assert text.count(before) == 1, 'Unexpected live asset; stop without writing'
    text = text.replace(before, after)
helper = (Path(__file__).parent / 'advertisingRatio.js').read_text(encoding='utf-8')
assert 'advertisingRatio' not in old.decode()
new = (helper.replace('export function', 'function') + '\n' + text).encode()
if '--apply' not in sys.argv:
    root.mkdir(exist_ok=False)
    (root / 'before.js').write_bytes(old)
    (root / 'after.js').write_bytes(new)
    print('Prepared only. Validate after.js before rerunning with --apply.')
    sys.exit(0)
assert (root / 'before.js').read_bytes() == old
assert (root / 'after.js').read_bytes() == new
assert read() == old, 'Concurrent frontend change; stop'
subprocess.run(['docker', 'cp', str(root / 'after.js'), container + ':' + asset + '.tmp'], check=True)
subprocess.run(['docker', 'exec', container, 'mv', asset + '.tmp', asset], check=True)
assert read() == new
(root / 'receipt.json').write_text(json.dumps({'asset': asset,
    'before_sha256': hashlib.sha256(old).hexdigest(),
    'after_sha256': hashlib.sha256(new).hexdigest(),
    'cache_note': 'Hard refresh required; no entry replacement or service restart.'}, indent=2))
print('Advertising asset patched and read back; hard refresh required.')
