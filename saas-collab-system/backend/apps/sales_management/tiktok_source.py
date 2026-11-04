"""Choose one stored advertising source per account for the whole query window.

Callers must apply their analytics/integration scopes before passing mappings.
Verified empty GMV Max snapshots still select GMV Max; they never trigger an
auction fallback for an otherwise missing comparison day.
"""
from datetime import date

from apps.integrations.gmv_max_read import stored_days
from apps.integrations.models import TikTokAdsDailySpend


def preferred_tiktok_days(user, mappings, start, end, *, store_days=None, windows=None):
    mappings = list(mappings)
    by_subject = {(m.store.code, m.advertiser_id): m for m in mappings
                  if m.tenant_id == user.tenant_id and m.store.tenant_id == user.tenant_id}
    verified, selected = [], set()
    for row in stored_days(user, list(by_subject.values()), {}, start, end):
        mapping = by_subject.get((row['store_code'], row['advertiser_id']))
        if mapping is None or row.get('relationship_verified') is not True:
            continue
        if store_days and row['date'] != store_days[mapping.store_id].isoformat():
            continue
        if windows and not any(lo and lo <= date.fromisoformat(row['date']) <= hi for lo, hi in windows):
            continue
        selected.add(mapping.pk)
        verified.append({**row, 'mapping_id': mapping.pk, 'source': 'GMV Max'})
    fallback = {m.pk: m for m in by_subject.values() if m.pk not in selected}
    for fact in TikTokAdsDailySpend.objects.filter(
            tenant_id=user.tenant_id, mapping_id__in=fallback, date__range=(start, end)
    ).values('mapping_id', 'date', 'currency', 'spend'):
        mapping = fallback[fact['mapping_id']]
        if store_days and fact['date'] != store_days[mapping.store_id]:
            continue
        if windows and not any(lo and lo <= fact['date'] <= hi for lo, hi in windows):
            continue
        verified.append({'mapping_id': mapping.pk, 'store_code': mapping.store.code,
                         'advertiser_id': mapping.advertiser_id,
                         'date': fact['date'].isoformat(), 'currency': fact['currency'],
                         'timezone': mapping.timezone, 'platform_store_id': None,
                         'cost': fact['spend'], 'source': '普通竞价'})
    return verified
