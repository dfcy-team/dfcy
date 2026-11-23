"""Read-only platform ID relationship verification; never infer ownership from timezones."""
from datetime import timedelta, datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.permissions.services import user_has_integration_permission

from . import tiktok_ads_pilot as pilot
from .ads_subject import mapping_allowed
from .ads_sync import validate_mapping, snapshot, lock_runtime_approval
from .models import IntegrationAuditLog, TikTokAdsAdvertiserMapping, TikTokAdsSyncLease
from .oauth_state_service import configuration_digest

STORE_PATH = '/open_api/v1.3/gmv_max/store/list/'
EXCLUSIVE_PATH = '/open_api/v1.3/gmv_max/exclusive_authorization/get/'
ACTION = 'ads_gmv_store_relation'


def verify_pair(get, advertiser_id, platform_store_id):
    stores = get(STORE_PATH, {'advertiser_id': advertiser_id}).get('store_list')
    if not isinstance(stores, list):
        raise ValidationError('GMV Max store list is invalid.')
    matches = [s for s in stores if isinstance(s, dict) and str(s.get('store_id')) == platform_store_id]
    if len(matches) != 1:
        raise ValidationError('GMV Max store identity is not uniquely verified.')
    store = matches[0]
    bc = store.get('store_authorized_bc_id')
    primary = str((store.get('exclusive_authorized_advertiser_info') or {}).get('advertiser_id') or '')
    if not isinstance(bc, str) or not bc.isdigit() or not primary.isdigit():
        raise ValidationError('GMV Max relationship requires explicit platform Store, BC and advertiser IDs.')
    exclusive = get(EXCLUSIVE_PATH, {'advertiser_id': advertiser_id,
        'store_id': platform_store_id, 'store_authorized_bc_id': bc})
    if (str(exclusive.get('advertiser_id')) != advertiser_id
            or str(exclusive.get('store_id')) != platform_store_id):
        raise ValidationError('GMV Max exclusive authorization identity mismatch.')
    status = exclusive.get('authorization_status')
    if (primary == advertiser_id and status == 'EFFECTIVE'
            and store.get('is_gmv_max_available') is True):
        relation = 'current_verified'
    elif primary != advertiser_id and status == 'UNAUTHORIZED':
        relation = 'not_current'
    else:
        raise ValidationError('GMV Max relationship responses conflict or have an unknown status.')
    return {'relationship_status': relation, 'platform_store_id': platform_store_id,
        'advertiser_id': advertiser_id, 'exclusive_advertiser_id': primary,
        'store_authorized_bc_id': bc, 'authorization_status': status,
        'store_evidence': store}


def probe_relationship(*, actor, mapping_id, commit=False):
    from .gmv_max_sync import shop_authorization
    def load(lock=False):
        query = TikTokAdsAdvertiserMapping.objects
        if lock:
            query = query.select_for_update()
        m = query.select_related('store__platform', 'integration_config', 'tenant').get(
            pk=mapping_id, tenant_id=actor.tenant_id)
        if (not user_has_integration_permission(actor, 'integrations.store.authorize')
                or not mapping_allowed(actor, m, 'integrations.store.authorize')):
            raise PermissionDenied('Relationship is outside actor scope.')
        return m
    actor.refresh_from_db()
    mapping = load()
    frozen = snapshot(mapping, validate_mapping(mapping))
    auth = shop_authorization(mapping)
    auth_frozen = (auth.pk, auth.platform_store_id, auth.updated_at)
    lease = pilot._claim_lease(mapping.tenant_id)
    try:
        token = pilot.get_custody_backend().retrieve_access_token(mapping.token_id)
        http = pilot.PlatformHttpClient()
        def guard(lock=False):
            actor.refresh_from_db()
            current = load(lock)
            if snapshot(current, validate_mapping(current, lock=lock)) != frozen:
                raise ValidationError('Relationship approval changed.')
            a = shop_authorization(current, lock=lock)
            if (a.pk, a.platform_store_id, a.updated_at) != auth_frozen:
                raise ValidationError('Relationship Shop identity changed.')
            pilot._renew_lease(mapping.tenant_id, *lease)
        def get(path, params):
            guard()
            response = http.request('GET', pilot.HOST + path + '?' + urlencode(params),
                headers={'Access-Token': token}, retry=False, connect_timeout=5,
                read_timeout=15, diagnostic_platform='tiktok_ads')
            payload = response.json()
            if (response.status_code != 200 or payload.get('code') not in (0, '0')
                    or not isinstance(payload.get('data'), dict)):
                raise ValidationError('GMV Max relationship official read rejected.')
            return payload['data']
        evidence = verify_pair(get, mapping.advertiser_id, auth.platform_store_id)
        observed = timezone.now()
        detail = {k: v for k, v in evidence.items() if k != 'store_evidence'}
        detail.update(schema='gmv-store-relation-v1', mapping_id=mapping.pk,
            store_id=mapping.store_id, observed_at=observed.isoformat(),
            mapping_updated_at=mapping.updated_at.isoformat(),
            configuration_fingerprint=configuration_digest(mapping.integration_config),
            currency=mapping.currency, timezone=mapping.timezone)
        # No access token, names, raw URLs or provider response bodies enter audit.
        result = {**detail, 'committed': False}
        if commit:
            guard()
            with transaction.atomic():
                locked = TikTokAdsSyncLease.objects.select_for_update().get(tenant_id=mapping.tenant_id)
                if ((locked.owner_token, locked.generation) != lease
                        or locked.lease_expires_at <= timezone.now()):
                    raise ValidationError('Relationship lease lost before commit.')
                lock_runtime_approval()
                guard(lock=True)
                audit = IntegrationAuditLog.objects.create(tenant_id=mapping.tenant_id,
                    actor=actor, integration_config_id=mapping.integration_config_id,
                    action=ACTION, result='success', masked_detail=detail)
                result.update(committed=True, audit_id=audit.pk)
        return result
    finally:
        pilot._release_lease(mapping.tenant_id, *lease)


def stored_relationships(user, mappings):
    """Current observations are not historical effective-from dates."""
    by_id = {m.pk: m for m in mappings}
    if not by_id:
        return []
    from .models import MarketplaceStoreAuthorization
    active_shop_ids = {}
    for auth in MarketplaceStoreAuthorization.objects.filter(tenant_id=user.tenant_id,
            store_id__in={m.store_id for m in mappings}, platform='tiktok', status='active', revoked_at__isnull=True):
        if auth.expires_at is None or auth.expires_at > timezone.now():
            active_shop_ids.setdefault(auth.store_id, []).append(auth.platform_store_id)
    query = IntegrationAuditLog.objects.filter(tenant_id=user.tenant_id,
        action=ACTION, result='success', masked_detail__mapping_id__in=list(by_id)).only(
            'id', 'integration_config_id', 'created_at', 'masked_detail').order_by('-created_at', '-pk')
    audits = list(query[:10001])
    if len(audits) > 10000:
        from .gmv_max_read import GMVMaxSnapshotOverflow
        raise GMVMaxSnapshotOverflow('Relationship evidence exceeds read bound.')
    latest = {}
    for audit in audits:
        d = audit.masked_detail
        m = by_id.get(d.get('mapping_id'))
        if (not m or m.pk in latest or audit.integration_config_id != m.integration_config_id
                or d.get('store_id') != m.store_id or d.get('advertiser_id') != m.advertiser_id):
            continue
        fresh = (audit.created_at >= timezone.now() - timedelta(hours=24)
                 and d.get('mapping_updated_at') == m.updated_at.isoformat()
                 and d.get('configuration_fingerprint') == configuration_digest(m.integration_config)
                 and active_shop_ids.get(m.store_id) == [d.get('platform_store_id')])
        latest[m.pk] = {**d, 'store_code': m.store.code, 'observed_at': audit.created_at.isoformat(),
                       'audit_id': audit.pk, 'fresh': fresh}
    return list(latest.values())


def attach_relationship_coverage(groups, rows, subjects, observations, start, end, *, account_mode=False):
    """Amounts remain untouched; dated Store-ID evidence determines coverage."""
    if groups is None:
        return None
    by_mapping = {s['mapping_id']: s for s in subjects}
    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    result = [dict(g) for g in groups]
    for observation in observations:
        subject = by_mapping.get(observation.get('mapping_id'))
        if (not subject or not observation.get('fresh')
                or observation.get('relationship_status') != 'current_verified'):
            continue
        observed_day = datetime.fromisoformat(observation['observed_at']).astimezone(
            ZoneInfo(subject['mapping_timezone'])).date().isoformat()
        if observed_day not in days:
            continue
        identity = dict(store_code=subject['store_code'], platform_store_id=observation['platform_store_id'],
                        currency=subject['currency'], timezone=subject['mapping_timezone'])
        if account_mode:
            identity.update(advertiser_id=subject['advertiser_id'], advertiser_name=subject.get('advertiser_name', ''))
        if not any(all(g.get(k) == v for k, v in identity.items() if k != 'advertiser_name') for g in result):
            result.append({**identity, 'advertiser_count': 1, 'stored_days': 0, 'expected_days': 1,
                'complete': False, 'conflict': False, 'cost': None, 'gross_revenue': None,
                'orders': None, 'roi': None, 'cost_per_order': None, 'data_days': 0, 'no_data_days': 0})
    for group in result:
        selected = [s for s in subjects if s['store_code'] == group['store_code']
                    and s['currency'] == group['currency']
                    and s['mapping_timezone'] == group['timezone']
                    and (not group.get('advertiser_id') or s['advertiser_id'] == group['advertiser_id'])]
        allowed = {s['advertiser_id'] for s in selected}
        data = [r for r in rows if r['store_code'] == group['store_code']
                and r['platform_store_id'] == group['platform_store_id']
                and r['advertiser_id'] in allowed and r['currency'] == group['currency']
                and r['timezone'] == group['timezone'] and r['date'] in days]
        proven = [r for r in data if r.get('relationship_verified') is True]
        accounts = {r['advertiser_id'] for r in proven}
        report_accounts = set(accounts)
        owners = {}
        for row in proven:
            owners.setdefault(row['date'], set()).add(row['advertiser_id'])
        # An observation can establish today's relation, never yesterday's owner.
        for observation in observations:
            subject = by_mapping.get(observation.get('mapping_id'))
            if (not subject or subject['store_code'] != group['store_code']
                    or observation.get('platform_store_id') != group['platform_store_id']
                    or observation.get('relationship_status') != 'current_verified'
                    or not observation.get('fresh') or subject['advertiser_id'] not in allowed
                    or subject['currency'] != group['currency']
                    or subject['mapping_timezone'] != group['timezone']):
                continue
            observed_day = datetime.fromisoformat(observation['observed_at']).astimezone(
                ZoneInfo(group['timezone'])).date().isoformat()
            if observed_day in days:
                owners.setdefault(observed_day, set()).add(subject['advertiser_id'])
                accounts.add(subject['advertiser_id'])
        expected = {(a, day) for day in days for a in owners.get(day, report_accounts)}
        covered = {(r['advertiser_id'], r['date']) for r in proven} & expected
        unverified = {(r['advertiser_id'], r['date']) for r in data if not r.get('relationship_verified')}
        group['api_coverage'] = {'account_count': len(accounts), 'stored_days': len(covered),
            'expected_days': len(expected), 'complete': bool(expected) and covered == expected
                and not unverified and not group.get('conflict'),
            'unverified_report_days': len(unverified),
            'basis': 'platform_store_advertiser_and_dated_report_evidence',
            'missing_days': len(expected - covered)}
    return result
