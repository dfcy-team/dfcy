"""Bounded tenant-1 business-entry ingestion; invoked by manage.py shell."""
import datetime
import json
import os
import time
from collections import Counter
from copy import deepcopy
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from apps.integrations.models import SyncJob, SyncRun
from apps.integrations.sync_services import run_sync_job, validate_manual_sync_job
from apps.integrations.views import _write_audit_log
from apps.integrations.affiliate_sync import TikTokAffiliateOrderAdapter
from apps.influencers.models import InfluencerProfile, TikTokCreatorProfileSnapshot
from apps.influencers.tiktok_creator_lookup import available_tiktok_lookup_stores, lookup_tiktok_creator
from apps.influencers.tasks import refresh_affiliate_order_attributions_task
from apps.tenants.models import Tenant

actor = get_user_model().objects.get(pk=1, tenant_id=1, is_active=True)
counts = Counter()
deadline = time.monotonic() + 3 * 3600


def report(**values):
    print(json.dumps(values, default=str), flush=True)


def guard():
    if time.monotonic() > deadline or os.getloadavg()[0] > 3:
        raise RuntimeError('resource_or_runtime_guard')
    with connection.cursor() as cursor:
        cursor.execute('SET SESSION innodb_lock_wait_timeout=3')


def bd(run):
    run.refresh_from_db()
    for day, entry in (run.masked_log or {}).get('affiliate_refresh', {}).items():
        if not entry.get('pending'):
            continue
        for offset in range(0, len(entry['ids']), 20):
            guard()
            result = refresh_affiliate_order_attributions_task.run(
                tenant_id=1, order_ids=entry['ids'][offset:offset + 20])
            report(event='bd_chunk', run=run.pk, day=day, result=result)
            if result.get('status') != 'completed':
                raise RuntimeError('bd_not_completed')
            time.sleep(2)
        with transaction.atomic():
            current = SyncRun.objects.select_for_update().get(pk=run.pk, tenant_id=1)
            log = deepcopy(current.masked_log)
            live = log['affiliate_refresh'][day]
            if live.get('generation') != entry.get('generation') or live.get('ids') != entry.get('ids'):
                raise RuntimeError('bd_generation_changed')
            log['affiliate_refresh'][day]['pending'] = False
            log['affiliate_refresh_pending'] = any(v.get('pending') for v in log['affiliate_refresh'].values())
            current.masked_log = log
            current.save(update_fields=['masked_log'])


def affiliates():
    # Reuse jobs; do not enable revoked capabilities or create new jobs.
    ids = list(SyncJob.objects.filter(tenant_id=1, resource_type='affiliate_order',
               is_enabled=True, schedule_type='manual').order_by('id').values_list('id', flat=True))
    for jid in ids:
        job = SyncJob.objects.select_related('integration_config', 'store_authorization__store').get(pk=jid)
        store = job.store_authorization.store
        last = timezone.now().astimezone(ZoneInfo(store.timezone)).date() - datetime.timedelta(days=1)
        # Last three complete days: successful same-day business plans are skipped.
        for day in [last - datetime.timedelta(days=i) for i in (2, 1, 0)]:
            try:
                guard()
                if job.runs.filter(status__in=['queued', 'running']).exists():
                    report(event='busy_skipped', job=jid)
                    break
                old_success = job.runs.filter(status='success',
                    masked_log__affiliate_refresh__has_key=str(day)).order_by('-finished_at').first()
                if old_success:
                    bd(old_success)
                    counts['already_successful'] += 1
                    continue
                key = f'affiliate-nightly-tenant1:{job.store_authorization_id}:{day}'
                existing = job.runs.filter(idempotency_key=key).first()
                if existing:
                    if existing.status == 'success':
                        bd(existing)
                    report(event='existing_run_not_repeated', run=existing.pk, status=existing.status)
                    continue
                with transaction.atomic():
                    Tenant.objects.select_for_update().get(pk=1)
                    job = SyncJob.objects.select_for_update().select_related(
                        'integration_config', 'store_authorization__store').get(pk=jid, tenant_id=1)
                    if job.lock_token or not job.is_enabled or job.schedule_type != 'manual':
                        raise RuntimeError('job_changed_or_busy')
                    if job.runs.filter(status__in=['queued', 'running']).exists():
                        raise RuntimeError('job_busy')
                    before = deepcopy(job.sync_scope)
                    job.sync_scope = {**before, 'affiliate': {
                        **before.get('affiliate', {}), 'trial_days': [str(day)]}}
                    TikTokAffiliateOrderAdapter(job.integration_config).validate_configuration(job)
                    job.save(update_fields=['sync_scope', 'updated_at'])
                    _write_audit_log(job.integration_config, actor, 'affiliate_nightly_day',
                                    detail={'sync_job_id': jid, 'day': str(day),
                                            'previous_affiliate': before.get('affiliate')})
                validate_manual_sync_job(job, live_only=True)
                run, _ = run_sync_job(job, idempotency_key=key)
                run.refresh_from_db()
                if run.status == 'success':
                    bd(run)
                counts[run.status] += 1
                report(event='affiliate_day', job=jid, store=store.code, day=day,
                       run=run.pk, status=run.status, created=run.created_count,
                       updated=run.updated_count, error=run.error_code)
                if run.status != 'success':
                    break
                time.sleep(10)
            except Exception as exc:
                counts['blocked'] += 1
                report(event='blocked', job=jid, day=day, error=type(exc).__name__)
                time.sleep(10)
                break


def creators():
    markets = {'PH': 'PH', 'TH': 'TH', 'MY': 'MY',
               '\u83f2\u5f8b\u5bbe': 'PH', '\u6cf0\u56fd': 'TH', '\u9a6c\u6765\u897f\u4e9a': 'MY'}
    stores = {}
    for item in available_tiktok_lookup_stores(actor):
        stores.setdefault(item['region'], item['id'])
    candidates = InfluencerProfile.objects.filter(
        tenant_id=1, influencer__platform='tiktok', influencer__is_deleted=False,
        market__in=markets).exclude(external_influencer_id='').exclude(
        influencer_id__in=TikTokCreatorProfileSnapshot.objects.filter(
            tenant_id=1).values('influencer_id')).order_by('pk')
    failures = 0
    for row in candidates.values('influencer_id', 'market', 'external_influencer_id')[:100]:
        guard()
        iid = row['influencer_id']
        if not str(row['external_influencer_id']).isascii() or not str(row['external_influencer_id']).isdigit():
            counts['untrusted_id_skipped'] += 1
            continue
        if TikTokCreatorProfileSnapshot.objects.filter(tenant_id=1, influencer_id=iid).exists():
            counts['already_saved'] += 1
            continue
        sid = stores.get(markets[row['market']])
        if sid is None:
            counts['no_store'] += 1
            continue
        try:
            result = lookup_tiktok_creator(actor=actor, influencer_id=iid, store_id=sid)
            counts[result['status']] += 1
            identity = (result.get('snapshot') or {}).get('identity_status')
            if identity:
                counts[identity] += 1
            report(event='creator', influencer=iid, status=result['status'], identity=identity)
            failures = 0
        except Exception as exc:
            counts['failed'] += 1
            failures += 1
            report(event='creator_failed', influencer=iid, error=type(exc).__name__)
            if failures >= 3:
                break
        time.sleep(5)


guard()
mode = os.environ['NIGHTLY_MODE']
if mode == 'affiliate':
    affiliates()
elif mode == 'creator':
    creators()
else:
    raise RuntimeError('unsupported_mode')
report(event='finished', mode=mode, counts=dict(counts))
if counts['blocked'] or counts['failed']:
    raise SystemExit('Partial run; inspect per-item results before retrying')
