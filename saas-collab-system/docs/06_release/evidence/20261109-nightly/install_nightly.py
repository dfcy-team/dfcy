"""Install two new serialized timers without changing existing SyncJob schedules."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
units = Path('/etc/systemd/system')
paths = [
    '/app/apps/influencers/tiktok_creator_lookup.py',
    '/app/apps/integrations/affiliate_sync.py',
    '/app/apps/integrations/sync_services.py',
    '/app/apps/influencers/tasks.py',
    '/app/apps/influencers/tiktok_shop_dataset.py',
]
manifest = {p: hashlib.sha256(subprocess.check_output(
    ['docker', 'exec', 'production-backend-1', 'cat', p])).hexdigest() for p in paths}
with (root / 'manifest.json').open('x') as f:
    json.dump(manifest, f, indent=2)
for mode, hour in [('affiliate', '23:00:00'), ('creator', '00:30:00')]:
    name = 'saas-nightly-' + mode
    if (units / (name + '.service')).exists() or (units / (name + '.timer')).exists():
        raise SystemExit('Existing unit preserved: ' + name)
    after = 'docker.service saas-tk-video-nightly.service'
    if mode == 'creator':
        after += ' saas-nightly-affiliate.service'
    service = f"""[Unit]
Description=Tenant1 bounded {mode} ingestion through existing business entrypoints
After={after}
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {root}/nightly_host.py {mode}
Nice=10
UMask=0077
TimeoutStartSec=infinity
Restart=no
StandardOutput=journal
StandardError=journal
"""
    timer = f"""[Unit]
Description=Tenant1 night-only {mode} ingestion
[Timer]
OnCalendar=*-*-* {hour} Asia/Shanghai
AccuracySec=60s
Persistent=true
[Install]
WantedBy=timers.target
"""
    (units / (name + '.service')).write_text(service)
    (units / (name + '.timer')).write_text(timer)
    subprocess.run(['systemd-analyze', 'verify', str(units / (name + '.service')),
                    str(units / (name + '.timer'))], check=True)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'saas-nightly-affiliate.timer',
                'saas-nightly-creator.timer'], check=True)
print('Installed and enabled two night timers; existing jobs untouched')
