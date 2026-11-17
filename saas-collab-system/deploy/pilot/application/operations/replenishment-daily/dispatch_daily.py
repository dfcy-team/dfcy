"""Native schedule dispatcher; successful daily keys are never recalculated."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
import fcntl, json, subprocess, sys, os
sys.stdout.reconfigure(line_buffering=True)
now = datetime.now(ZoneInfo('Asia/Shanghai'))
batch_day = date.fromisoformat(os.environ.get('SAAS_REPLENISHMENT_DAY') or now.date().isoformat())
if (now.date() - batch_day).days not in (0, 1):
    raise ValueError('Invalid daily business day')
if batch_day == now.date() and now.time() < time(10, 40):
    print(json.dumps({'status': 'before_daily_window'}))
    raise SystemExit(0)
locks = []
for path, mode in [('/var/lock/saas-replenishment-daily.lock', fcntl.LOCK_EX)]:
    stream = open(path, 'a')
    try:
        fcntl.flock(stream, mode | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({'status': 'busy_retry_next_tick'}))
        raise SystemExit(0)
    locks.append(stream)
GENERATION_SCOPE_PREAMBLE = """from apps.commerce import country_decisions as _daily_countries
from apps.supply_chain.models import ReplenishmentStrategy as _DailyStrategy
_daily_original_countries = _daily_countries.countries_for
def _daily_configured_countries(actor, *args, **kwargs):
    allowed = _daily_original_countries(actor, *args, **kwargs)
    configured = _DailyStrategy.objects.filter(tenant_id=actor.tenant_id, active=True).values('country_id')
    return allowed.filter(pk__in=configured)
_daily_countries.countries_for = _daily_configured_countries
"""
RECOVERY_PREAMBLE = "from datetime import timedelta as _daily_delta\nfrom django.db import transaction as _daily_tx\nfrom django.db.models import Q as _daily_Q\nfrom django.utils import timezone as _daily_tz\nfrom apps.supply_chain.models import ReplenishmentCalculationJob as _DailyJob\nfrom apps.supply_chain import replenishment_jobs as _daily_jobs\n_daily_now = _daily_tz.now()\n_daily_stale = _daily_now - _daily_delta(seconds=60)\n_daily_recover_ids = list(_DailyJob.objects.filter(config__daily__day=RECOVERY_BUSINESS_DAY, hard_deadline__gt=_daily_now, updated_at__lte=_daily_stale).filter(_daily_Q(status='queued') | _daily_Q(status='running') & (_daily_Q(lease_expires_at__isnull=True) | _daily_Q(lease_expires_at__lte=_daily_now))).order_by('created_at').values_list('pk',flat=True)[:20])\nfor _daily_pk in _daily_recover_ids:\n    with _daily_tx.atomic():\n        _daily_job = _DailyJob.objects.select_for_update().filter(pk=_daily_pk).first()\n        if not _daily_job or _daily_job.hard_deadline <= _daily_now or _daily_job.updated_at > _daily_stale:\n            continue\n        if not (_daily_job.status == 'queued' or (_daily_job.status == 'running' and (_daily_job.lease_expires_at is None or _daily_job.lease_expires_at <= _daily_now))):\n            continue\n        _DailyJob.objects.filter(pk=_daily_pk).update(updated_at=_daily_now)\n        _daily_tx.on_commit(lambda pk=_daily_pk: _daily_jobs._dispatch_followup(pk))\n"
source = "RECOVERY_BUSINESS_DAY=" + repr(batch_day.isoformat()) + "\n" + RECOVERY_PREAMBLE + GENERATION_SCOPE_PREAMBLE + "import json,signal;signal.alarm(540);from apps.supply_chain.daily_replenishment import generate_daily_replenishments;print('DAILY_RESULT='+json.dumps(generate_daily_replenishments(business_day=" + repr(batch_day.isoformat()) + "),default=str))"
# One scheduled update may submit its dimensions in waves while the existing
# worker capacity drains. Completed keys are reused, never recomputed.
import time as clock_time
end = clock_time.monotonic() + 6 * 3600
while clock_time.monotonic() < end:
    with open('/opt/saas-collab/release-control/unified/ci-control/locks/production-release.lock', 'a') as deployment_lock:
        try:
            fcntl.flock(deployment_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status':'waiting_for_deployment_or_backup'}),flush=True)
            clock_time.sleep(30)
            continue
        result = subprocess.run(['docker', 'exec', '-i', '-e', 'SAAS_DAILY_REPLENISHMENT_RUN=1', 'application-backend-1', 'python', '-B', 'manage.py', 'shell'], input=source.encode(), capture_output=True, timeout=600)
    summary = None
    for line in result.stdout.decode(errors='replace').splitlines():
        if line.startswith('DAILY_RESULT='):
            print(line, flush=True)
            summary = json.loads(line.split('=',1)[1])
    if result.returncode or summary is None:
        print(json.dumps({'status': 'dispatch_failed', 'returncode': result.returncode}), flush=True)
        raise SystemExit(1)
    if not summary.get('has_more') and not summary.get('pending') and not summary.get('queued'):
        if summary.get('failed_dimensions') or summary.get('errors'):
            print(json.dumps({'status':'daily_dimensions_incomplete'}),flush=True)
            raise SystemExit(1)
        raise SystemExit(0)
    clock_time.sleep(30)
print(json.dumps({'status':'daily_submission_window_exceeded'}),flush=True)
raise SystemExit(1)
