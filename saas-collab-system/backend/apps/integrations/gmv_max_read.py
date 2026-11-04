"""Read verified stored GMV Max snapshots; never invoke a provider or custody."""
from django.db.models import Q
from datetime import timedelta
from .models import IntegrationAuditLog, SharedAdvertisingRawPayload
from .gmv_max_sync import REPORT_PATH, summarize


class GMVMaxSnapshotOverflow(Exception):
    """Stored GMV Max history exceeded the bounded report read."""


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
        raise GMVMaxSnapshotOverflow('Too many GMV Max snapshots; select a narrower range/store.')
    # RAW rows are content-addressed and may be reused (A -> B -> A). Their
    # immutable created_at then describes first storage, not latest observation.
    # Successful sync audits provide the observation order and raw row link.
    # Legacy rows without such audits retain created_at ordering.
    audit_order = {}
    if snapshots:
        audits = IntegrationAuditLog.objects.filter(tenant_id=user.tenant_id,
            action='ads_gmv_max_day', result='success',
            masked_detail__raw_payload_id__in=[s.pk for s in snapshots]).only('masked_detail', 'created_at', 'id').order_by('-created_at','-pk')
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
        evidence = p.get('store_evidence') or {}
        exclusive = evidence.get('exclusive_authorized_advertiser_info') if isinstance(evidence, dict) else None
        relationship_verified = (isinstance(evidence, dict) and isinstance(exclusive, dict)
            and str(evidence.get('store_id')) == p['platform_store_id']
            and str(exclusive.get('advertiser_id')) == p['advertiser_id']
            and evidence.get('is_gmv_max_available') is True
            and p.get('report_scope') == 'GMV_MAX_CAMPAIGN')
        rows.append({'snapshot_id':item.pk,'store_code':m.store.code,
            'advertiser_id':m.advertiser_id,'advertiser_name':names.get(m.pk,''),
            'platform_store_id':p['platform_store_id'],'date':p['date'],
            'currency':p['currency'],'timezone':p['timezone'],
            'relationship_verified': relationship_verified,
            'fetched_at':audit_order.get(item.pk, (item.created_at, item.pk))[0].isoformat(),
            **summarize(p['pages'])})
    return sorted(rows,key=lambda r:(r['date'],r['advertiser_id']),reverse=True)


def collection_days(user, mappings, names, rows, start, end):
    """Only verified empty responses are no_data; absence stays unknown."""
    if rows is None:
        return None
    by_mapping = {m.pk: m for m in mappings}
    failures = IntegrationAuditLog.objects.filter(
        tenant_id=user.tenant_id, action='ads_gmv_max_day', result='failed',
        masked_detail__mapping_id__in=list(by_mapping),
        masked_detail__date__gte=start.isoformat(), masked_detail__date__lte=end.isoformat(),
    ).order_by('-created_at', '-pk')
    latest = {}
    attempts = list(failures[:10001])
    if len(attempts) > 10000:
        raise GMVMaxSnapshotOverflow('Too many collection attempts; narrow the range/store.')
    for audit in attempts:
        d = audit.masked_detail
        m = by_mapping.get(d.get('mapping_id'))
        if not m or audit.integration_config_id != m.integration_config_id:
            continue
        if any(d.get(k) != v for k, v in {
            'store_id': m.store_id, 'advertiser_id': m.advertiser_id,
            'currency': m.currency, 'timezone': m.timezone}.items()):
            continue
        latest.setdefault((m.pk, d['date']), audit)
    result = []
    for m in mappings:
        for offset in range((end - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            saved = [r for r in rows if r['store_code'] == m.store.code
                     and r['advertiser_id'] == m.advertiser_id and r['date'] == day
                     and r['currency'] == m.currency and r['timezone'] == m.timezone]
            failure = latest.get((m.pk, day))
            status = ('no_data' if all(r.get('collection_status') == 'no_data' for r in saved)
                      else 'success') if saved else ('failed' if failure else 'not_collected')
            result.append({'mapping_id': m.pk, 'store_code': m.store.code,
                'advertiser_id': m.advertiser_id, 'advertiser_name': names.get(m.pk, ''),
                'currency': m.currency, 'timezone': m.timezone, 'date': day,
                'status': status, 'error_code': failure.masked_detail.get('error_code')
                if failure and not saved else None})
    return result
