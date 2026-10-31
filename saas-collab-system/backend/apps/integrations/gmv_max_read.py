"""Read verified stored GMV Max snapshots; never invoke a provider or custody."""
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from .models import IntegrationAuditLog, SharedAdvertisingRawPayload
from .gmv_max_sync import REPORT_PATH, summarize


def stored_days(user, mappings, names, start, end):
    if not mappings:
        return []
    scope = Q(pk__in=[])
    by_subject = {}
    for m in mappings:
        scope |= Q(store_id=m.store_id, payload__advertiser_id=m.advertiser_id)
        by_subject[(m.store_id, m.advertiser_id)] = m
    query = SharedAdvertisingRawPayload.objects.filter(scope, tenant_id=user.tenant_id,
        platform='tiktok', endpoint=REPORT_PATH, payload__schema='gmv-max-day-v1',
        payload__date__gte=start.isoformat(),payload__date__lte=end.isoformat()).order_by('-created_at','-pk')
    snapshots = list(query[:1001])
    if len(snapshots) > 1000:
        raise ValidationError('Too many GMV Max snapshots; select a narrower range/store.')
    # RAW rows are content-addressed and may be reused (A -> B -> A). Their
    # immutable created_at then describes first storage, not latest observation.
    # Successful sync audits provide the observation order and raw row link.
    # Legacy rows without such audits retain created_at ordering.
    audit_order = {}
    if snapshots:
        audits = IntegrationAuditLog.objects.filter(tenant_id=user.tenant_id,
            action='ads_gmv_max_day', result='success',
            masked_detail__raw_payload_id__in=[s.pk for s in snapshots]).order_by('-created_at','-pk')
        for audit in audits.iterator():
            raw_id = audit.masked_detail.get('raw_payload_id')
            if raw_id is not None and raw_id not in audit_order:
                audit_order[raw_id] = (audit.created_at, audit.pk)
    seen, rows = set(), []
    for item in sorted(snapshots, key=lambda s: audit_order.get(s.pk, (s.created_at, s.pk)), reverse=True):
        p = item.payload
        m = by_subject[(item.store_id,p['advertiser_id'])]
        key = (m.pk,p['date'],p['platform_store_id'],p['currency'],p['timezone'])
        if key in seen:
            continue
        seen.add(key)
        rows.append({'snapshot_id':item.pk,'store_code':m.store.code,
            'advertiser_id':m.advertiser_id,'advertiser_name':names.get(m.pk,''),
            'platform_store_id':p['platform_store_id'],'date':p['date'],
            'currency':p['currency'],'timezone':p['timezone'],
            'fetched_at':audit_order.get(item.pk, (item.created_at, item.pk))[0].isoformat(),
            **summarize(p['pages'])})
    return sorted(rows,key=lambda r:(r['date'],r['advertiser_id']),reverse=True)
