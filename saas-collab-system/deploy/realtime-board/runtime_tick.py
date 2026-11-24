from pathlib import Path
import json,subprocess,sys,time
from datetime import datetime,time as local_time
from zoneinfo import ZoneInfo
O=Path(__file__).resolve().parent
result={'at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
r=subprocess.run([sys.executable,str(O/'resource_guard.py'),'--config',str(O/'resource-policy.json'),'--state',str(O/'resource-state.json')],capture_output=True,text=True,timeout=30)
result['resource_policy']={'exit_code':r.returncode,'summary':r.stdout.strip()[-200:]}
now=datetime.now(ZoneInfo('Asia/Shanghai')).time().replace(tzinfo=None)
if local_time(8,45)<=now<local_time(19):
 code="import signal;signal.alarm(25);import django;django.setup();from apps.sales_management.board_availability import prewarm_recent;print(prewarm_recent())"
 try:
  r=subprocess.run(['docker','exec','production-realtime-board-api-1','python','-c',code],capture_output=True,text=True,timeout=30)
  result['prewarm']={'exit_code':r.returncode,'scheduled':r.stdout.strip()[-30:]}
 except subprocess.TimeoutExpired:result['prewarm']={'exit_code':124}
(O/'last-tick.json').write_text(json.dumps(result,ensure_ascii=False))
log=O/'workhours-health.jsonl'
if log.exists() and log.stat().st_size>3*1024*1024:log.replace(O/'workhours-health.previous.jsonl')
with log.open('a') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
print(json.dumps(result,ensure_ascii=False))
