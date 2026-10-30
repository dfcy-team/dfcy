"""Synthetic-only Ads OAuth coverage; never contact real APIs or databases."""
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from django.core import signing

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.integrations import tiktok_ads_oauth as ads
from apps.integrations import tiktok_ads_direct as direct
from apps.integrations.models import AdsOAuthSession, PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, authorization_service_write
from apps.masterdata.models import StoreMaster
from apps.permissions.models import UserRole
from tests.test_lazada_store_authorization import lazada_context

pytestmark = pytest.mark.django_db
CALLBACK = 'https://saas.example.test/integrations/tiktok-ads/direct-callback'
VERIFIER = 'v' * 64
FLOW_CLAIMS = {}


@pytest.fixture
def context(lazada_context, monkeypatch, settings):
    FLOW_CLAIMS.clear()
    settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = CALLBACK
    client, store, config = lazada_context
    store.platform.platform_type = 'tiktok'
    store.platform.save()
    config.platform = 'tiktok'
    config.status = 'verified'
    config.platform_config = {'api_type': 'advertising', 'app_id': '123456789'}
    config.callback_url = CALLBACK
    config.network_enabled, config.sync_read_enabled = True, True
    config.credential_status = 'configured'
    config.credential_id = 'cre_' + 'b' * 32
    with authorization_service_write():
        config.save()
    actor = config.created_by
    monkeypatch.setattr(ads, 'require_live_mode', lambda *a: None)
    monkeypatch.setattr(ads, 'get_runtime_platform_config', lambda *a: {'contract_approved': True})
    monkeypatch.setattr(ads, 'get_runtime_setting', lambda *a, **k: [CALLBACK])
    monkeypatch.setattr(ads, 'integration_values_allowed', lambda *a, **k: True)
    backend = Mock()
    backend.retrieve_secret.return_value = 'SYNTHETIC_ADS_SECRET'
    backend.retrieve_access_token.return_value = 'SYNTHETIC_TOKEN'
    backend.store_secrets.return_value = {'credential_id': 'cre_' + 'c' * 32, 'token_id': 'tok_' + 'd' * 32}
    monkeypatch.setattr(ads, 'custody', lambda: backend)
    # Fail closed if any test forgets to stub its network interaction.
    monkeypatch.setattr(ads.PlatformHttpClient, 'request', Mock(side_effect=AssertionError('No live network in tests')))
    return client, actor, store, config, backend


def pending(context):
    _, actor, store, config, _ = context
    result = ads.start(actor, store.pk, config.pk, VERIFIER)
    claims = {'state': parse_qs(urlsplit(result['authorization_url']).query)['state'][0],
        'browser_token': result['direct_callback']['browser_token']}
    FLOW_CLAIMS[str(result['session_id'])] = claims
    return AdsOAuthSession.objects.get(pk=result['session_id']), claims


def complete(actor, session_id, receipt_id=None, *, callback_params=None, browser_token=None):
    claims = FLOW_CLAIMS[str(session_id)]
    token = browser_token or claims['browser_token']
    params = callback_params if callback_params is not None else {'state': claims['state'], 'auth_code': 'FAKE_CODE'}
    return direct.complete(actor, token, VERIFIER, params)


def transport(context, monkeypatch, *, discovery_error=False, exchange_error=False):
    session, claims = pending(context)
    calls = []
    def request(s, method, url, **kwargs):
        calls.append(url)
        if url.endswith('access_token/'):
            if exchange_error: raise TimeoutError
            return {'access_token': 'SYNTHETIC_TOKEN'}
        if 'advertiser/get/' in url:
            if discovery_error: raise TimeoutError
            return {'list': [{'advertiser_id': '111', 'advertiser_name': 'PHP account'}, {'advertiser_id': '222', 'advertiser_name': 'USD account'}]}
        if 'advertiser/info/' in url:
            identifier = '111' if '111' in url else '222'
            return {'list': [{'advertiser_id': identifier, 'currency': 'PHP' if identifier == '111' else 'USD', 'timezone': 'Asia/Manila'}]}
        raise AssertionError('Unexpected endpoint')
    monkeypatch.setattr(ads, 'request_json', request)
    return session, calls


def test_one_exchange_mixed_currencies_disabled_bind_no_sync(context, monkeypatch):
    _, actor, _, _, backend = context
    session, calls = transport(context, monkeypatch)
    result = complete(actor, session.pk, 'a' * 64)
    assert result['status'] == 'authorized'
    assert not any(word in str(result) for word in ['SYNTHETIC_TOKEN', 'FAKE_CODE', 'tok_'])
    with pytest.raises(ads.Conflict): complete(actor, session.pk, 'a' * 64)
    assert sum(url.endswith('access_token/') for url in calls) == 1
    for identifier in ('111', '222'): ads.verify(actor, session.pk, identifier)
    result = ads.bind(actor, session.pk, ['111', '222'], 'idempotency-test')
    assert result['status'] == 'bound' and result['report_data_ingested'] is False
    assert set(TikTokAdsAdvertiserMapping.objects.values_list('currency', flat=True)) == {'PHP', 'USD'}
    assert not TikTokAdsAdvertiserMapping.objects.filter(enabled=True).exists()
    assert ads.bind(actor, session.pk, ['222', '111'], 'idempotency-test') == result
    with pytest.raises(ads.Conflict): ads.bind(actor, session.pk, ['111'], 'another-key')
    assert not any('report/' in url or 'publish' in url for url in calls)
    assert backend.store_secrets.call_args.kwargs['credential_type'] == 'tiktok_ads'
    from apps.integrations.models import SyncJob, TikTokAdsDailySpend
    assert not SyncJob.objects.exists() and not TikTokAdsDailySpend.objects.exists()


def test_discovery_failure_retains_token_and_can_retry(context, monkeypatch):
    _, actor, _, _, _ = context
    session, _ = transport(context, monkeypatch, discovery_error=True)
    result = complete(actor, session.pk, 'a' * 64)
    session.refresh_from_db()
    assert result['discovery_failed'] and session.status == 'authorized' and session.token_id
    monkeypatch.setattr(ads, 'request_json', lambda *a, **k: {'list': [{'advertiser_id': '333'}]})
    assert ads.discover(actor, session.pk)['candidates'][0]['advertiser_id'] == '333'


def test_timeout_is_unknown_never_replayed(context, monkeypatch):
    _, actor, _, _, backend = context
    session, calls = transport(context, monkeypatch, exchange_error=True)
    with pytest.raises(ValidationError): complete(actor, session.pk, 'a' * 64)
    session.refresh_from_db()
    assert session.status == 'unknown'
    with pytest.raises(ads.Conflict): complete(actor, session.pk, 'a' * 64)
    assert sum(url.endswith('access_token/') for url in calls) == 1
    backend.store_secrets.assert_not_called()


@pytest.mark.parametrize('change', ['actor', 'tenant', 'config', 'permission', 'external', 'store', 'writes', 'deleted'])
def test_live_scope_and_drift_rejected(context, monkeypatch, change):
    _, actor, store, config, _ = context
    session, _ = pending(context)
    if change == 'actor':
        actor = CustomUser.objects.create_user(username='other', tenant=actor.tenant, user_type='internal', is_superuser=True)
    elif change == 'tenant':
        from apps.tenants.models import Tenant
        other = Tenant.objects.create(name='other', code='other')
        AdsOAuthSession.objects.filter(pk=session.pk).update(tenant=other)
    elif change == 'config':
        PlatformIntegrationConfig.objects.filter(pk=config.pk).update(config_version=2)
    elif change == 'permission':
        monkeypatch.setattr(ads, 'integration_values_allowed', lambda *a, **k: False)
    elif change == 'external':
        actor.user_type = 'external'; actor.save()
    elif change == 'store':
        StoreMaster.objects.filter(pk=store.pk).update(status='inactive')
    elif change == 'deleted':
        from django.utils import timezone
        PlatformIntegrationConfig.objects.filter(pk=config.pk).update(deleted_at=timezone.now())
    else:
        PlatformIntegrationConfig.objects.filter(pk=config.pk).update(sync_write_enabled=True)
    with pytest.raises((PermissionDenied, ValidationError, ads.Conflict)): ads.load(actor, session.pk)


def test_failed_verify_membership_and_other_store_conflict(context, monkeypatch):
    _, actor, store, config, _ = context
    session, _ = transport(context, monkeypatch)
    complete(actor, session.pk, 'a' * 64)
    monkeypatch.setattr(ads, 'request_json', Mock(side_effect=TimeoutError))
    assert ads.verify(actor, session.pk, '111')['candidates'][0]['verify_state'] == 'failed'
    for identifier in ['111', '999']:
        with pytest.raises(ValidationError): ads.bind(actor, session.pk, [identifier], 'test-request-key')
    with pytest.raises(ads.Conflict): ads.verify(actor, session.pk, '999')
    session.refresh_from_db()
    session.candidates[0].update(verify_state='verified', currency='PHP', timezone='Asia/Manila', verified_at='2026-10-16T00:00:00Z')
    session.save()
    other = StoreMaster.objects.create(tenant=actor.tenant, platform=store.platform, code='OTHER', name='other', country_code='PH', currency='PHP', timezone='Asia/Manila')
    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=actor.tenant, store=other, integration_config=config,
        advertiser_id='111', token_id=session.token_id, currency='PHP', timezone='Asia/Manila', enabled=False)
    with pytest.raises(ads.Conflict): ads.bind(actor, session.pk, ['111'], 'test-request-key')
    mapping.refresh_from_db()
    assert mapping.store_id == other.pk and not mapping.enabled


def test_api_strict_input_and_sanitized_session(context):
    client, _, store, config, _ = context
    base = '/api/internal/integrations/tiktok-ads/oauth/'
    assert client.post(base + 'start/', {'store_id': store.pk, 'integration_config_id': config.pk, 'tenant_id': 99}, format='json').status_code == 400
    session, _ = pending(context)
    result = client.get(base + f'sessions/{session.pk}/')
    assert result.status_code == 200
    assert set(result.data['data']) == {'session_id', 'store_id', 'status', 'expires_at', 'candidates', 'bindings', 'report_data_ingested'}


@pytest.mark.parametrize('status', ['bound', 'unknown'])
def test_detail_expired_session_ignores_live_config_but_keeps_permissions(context, monkeypatch, status):
    from datetime import timedelta
    from django.utils import timezone
    client, _, _, config, _ = context
    session, _ = pending(context)
    AdsOAuthSession.objects.filter(pk=session.pk).update(status=status, expires_at=timezone.now() - timedelta(days=1))
    PlatformIntegrationConfig.objects.filter(pk=config.pk).update(network_enabled=False, config_version=999)
    path = f'/api/internal/integrations/tiktok-ads/oauth/sessions/{session.pk}/'
    result = client.get(path)
    assert result.status_code == 200 and result.data['data']['status'] == status
    session.refresh_from_db()
    assert session.status == status
    monkeypatch.setattr(ads, 'integration_values_allowed', lambda *a, **k: False)
    assert client.get(path).status_code == 403


def test_denied_authorization_never_exchanges(context, monkeypatch):
    _, actor, _, _, backend = context
    session, claims = pending(context)
    request = Mock(side_effect=AssertionError('Denial must not call platform'))
    monkeypatch.setattr(ads, 'request_json', request)
    assert complete(actor, session.pk, callback_params={'error': 'authorization_denied', 'state': claims['state']})['status'] == 'failed'
    request.assert_not_called()
    backend.store_secrets.assert_not_called()


@pytest.mark.parametrize('tamper', ['state', 'session_id'])
def test_direct_binding_mismatch_never_exchanges(context, monkeypatch, tamper):
    _, actor, _, _, backend = context
    session, claims = pending(context)
    params = {'auth_code': 'FAKE_CODE', 'state': claims['state']}
    token = claims['browser_token']
    if tamper == 'state': params['state'] = 'wrong-state'
    else:
        data = signing.loads(token, salt=direct.SALT)
        data['session_id'] = '11111111-2222-4333-8444-555555555555'
        token = signing.dumps(data, salt=direct.SALT)
    request = Mock(side_effect=AssertionError('Invalid binding must not call platform'))
    monkeypatch.setattr(ads, 'request_json', request)
    with pytest.raises((ValidationError, PermissionDenied)):
        complete(actor, session.pk, callback_params=params, browser_token=token)
    request.assert_not_called()
    backend.store_secrets.assert_not_called()


def test_http_requests_are_bounded_and_never_retried(context, monkeypatch):
    session, _ = pending(context)
    request = Mock(return_value=Mock(json=lambda: {'code': 0, 'data': {}}))
    monkeypatch.setattr(ads.PlatformHttpClient, 'request', request)
    assert ads.request_json(session, 'POST', ads.HOST + 'oauth2/access_token/', body={'auth_code': 'FAKE_CODE'}) == {}
    assert request.call_args.kwargs['retry'] is False
    assert 0 < request.call_args.kwargs['connect_timeout'] <= 5
    assert 0 < request.call_args.kwargs['read_timeout'] <= 15


def test_same_store_reauthorization_rotates_mapping_but_disables_sync(context, monkeypatch):
    _, actor, store, config, _ = context
    session, _ = transport(context, monkeypatch)
    complete(actor, session.pk, 'a' * 64)
    ads.verify(actor, session.pk, '111')
    existing = TikTokAdsAdvertiserMapping.objects.create(tenant=actor.tenant, store=store, integration_config=config,
        advertiser_id='111', token_id='tok_' + 'e' * 32, currency='PHP', timezone='Asia/Manila', enabled=True)
    ads.bind(actor, session.pk, ['111'], 'reauthorization-key')
    existing.refresh_from_db()
    session.refresh_from_db()
    assert existing.token_id == session.token_id and existing.store_id == store.pk
    assert not existing.enabled and TikTokAdsAdvertiserMapping.objects.count() == 1


@pytest.mark.parametrize('stage', ['developer_secret', 'exchange', 'malformed_token', 'custody', 'session_save', 'authorized_audit'])
def test_failure_injection_never_retriggers_exchange(context, monkeypatch, stage):
    _, actor, _, _, backend = context
    session, calls = transport(context, monkeypatch)
    original_request = ads.request_json
    def request(record, method, url, **kwargs):
        if stage == 'exchange' and url.endswith('access_token/'):
            calls.append(url)
            raise TimeoutError('synthetic ambiguous exchange')
        result = original_request(record, method, url, **kwargs)
        if stage == 'malformed_token' and url.endswith('access_token/'):
            return {'access_token': None}
        return result
    monkeypatch.setattr(ads, 'request_json', request)
    if stage == 'developer_secret': backend.retrieve_secret.side_effect = TimeoutError
    if stage == 'custody': backend.store_secrets.side_effect = TimeoutError
    if stage == 'session_save':
        original_save = AdsOAuthSession.save
        def save(record, *args, **kwargs):
            if record.status == 'authorized': raise RuntimeError('synthetic database failure')
            return original_save(record, *args, **kwargs)
        monkeypatch.setattr(AdsOAuthSession, 'save', save)
    if stage == 'authorized_audit':
        original_audit = ads.audit
        def audit(record, user, event, result='success'):
            if event == 'authorized': raise RuntimeError('synthetic audit failure')
            return original_audit(record, user, event, result)
        monkeypatch.setattr(ads, 'audit', audit)
    with pytest.raises(ValidationError): complete(actor, session.pk, 'a' * 64)
    session.refresh_from_db()
    assert session.status == 'unknown' and session.consumed_at is not None
    before = list(calls)
    for receipt in ['a' * 64, 'b' * 64]:
        with pytest.raises(ads.Conflict): complete(actor, session.pk, receipt)
    assert calls == before
    assert sum(url.endswith('access_token/') for url in calls) == (0 if stage == 'developer_secret' else 1)
    assert not TikTokAdsAdvertiserMapping.objects.exists()


def test_process_crash_leaves_durable_claim_and_cannot_reexchange(context, monkeypatch):
    from datetime import timedelta
    from django.utils import timezone
    _, actor, _, _, _ = context
    session, calls = transport(context, monkeypatch)
    original = ads.request_json
    def crash(record, method, url, **kwargs):
        if url.endswith('access_token/'):
            calls.append(url)
            raise SystemExit('synthetic process death')
        return original(record, method, url, **kwargs)
    monkeypatch.setattr(ads, 'request_json', crash)
    with pytest.raises(SystemExit): complete(actor, session.pk, 'a' * 64)
    session.refresh_from_db()
    assert session.status == 'exchanging' and session.consumed_at
    with pytest.raises(ads.Conflict): complete(actor, session.pk, 'a' * 64)
    AdsOAuthSession.objects.filter(pk=session.pk).update(consumed_at=timezone.now() - timedelta(seconds=121))
    assert ads.load(actor, session.pk).status == 'unknown'
    with pytest.raises(ads.Conflict): complete(actor, session.pk, 'b' * 64)
    assert sum(url.endswith('access_token/') for url in calls) == 1


@pytest.mark.parametrize('operation', ['complete', 'discover', 'verify'])
def test_permission_removed_during_network_blocks_persisted_results(context, monkeypatch, operation):
    _, actor, _, _, backend = context
    session, _ = transport(context, monkeypatch)
    if operation != 'complete': complete(actor, session.pk, 'a' * 64)
    original_request = ads.request_json
    def request(record, method, url, **kwargs):
        result = original_request(record, method, url, **kwargs)
        target = {'complete': 'access_token/', 'discover': 'advertiser/get/', 'verify': 'advertiser/info/'}[operation]
        if target in url:
            monkeypatch.setattr(ads, 'integration_values_allowed', lambda *a, **k: False)
        return result
    monkeypatch.setattr(ads, 'request_json', request)
    with pytest.raises(ValidationError if operation == 'complete' else PermissionDenied):
        if operation == 'complete': complete(actor, session.pk, 'a' * 64)
        elif operation == 'discover': ads.discover(actor, session.pk)
        else: ads.verify(actor, session.pk, '111')
    session.refresh_from_db()
    if operation == 'complete':
        assert session.status == 'unknown' and not session.token_id
        backend.store_secrets.assert_called_once()
    else:
        assert session.status == 'authorized'
        assert all(candidate['verify_state'] == 'unverified' for candidate in session.candidates)
    assert not TikTokAdsAdvertiserMapping.objects.exists()


@pytest.mark.parametrize('endpoint', ['start', 'detail', 'complete', 'discover', 'verify', 'bind'])
def test_real_declared_scope_denies_every_endpoint_before_network(context, monkeypatch, endpoint):
    from apps.permissions.ui_p6_scopes import integration_values_allowed
    from tests.test_oauth_callback_target_security import restricted_actor
    client, _, store, config, _ = context
    session, claims = pending(context)
    actor, declared_scope = restricted_actor(store, config)
    # restricted_actor grants the integration_admin API-admin identity. Revoke
    # that binding so this case exercises the declared-scope denial for an
    # ordinary actor, independent of the custom scope payload.
    UserRole.objects.filter(user=actor, tenant=store.tenant).delete()
    AdsOAuthSession.objects.filter(pk=session.pk).update(actor=actor)
    session.actor = actor
    token = signing.dumps(direct.claims_for(session), salt=direct.SALT)
    declared_scope.config = {'store_ids': [store.pk + 100000], 'integration_config_ids': [config.pk]}
    declared_scope.save()
    monkeypatch.setattr(ads, 'integration_values_allowed', integration_values_allowed)
    client.force_authenticate(actor)
    base = '/api/internal/integrations/tiktok-ads/oauth/'
    target = base + f'sessions/{session.pk}/'
    routes = {
        'start': (base + 'start/', {'store_id': store.pk, 'integration_config_id': config.pk, 'tiktok_browser_verifier': VERIFIER}),
        'complete': (base + 'direct-callback/', {'browser_token': token, 'browser_verifier': VERIFIER,
            'callback_params': {'state': claims['state'], 'auth_code': 'FAKE_CODE'}}),
        'discover': (target + 'discover/', {}), 'verify': (target + 'advertisers/111/verify/', {}),
        'bind': (target + 'bind/', {'advertiser_ids': ['111'], 'idempotency_key': 'denied-scope-key'}),
    }
    if endpoint == 'detail': response = client.get(target)
    else:
        path, body = routes[endpoint]
        response = client.post(path, body, format='json')
    assert response.status_code == 403, response.data
    session.refresh_from_db()
    assert session.status == 'pending' and session.consumed_at is None
    ads.PlatformHttpClient.request.assert_not_called()


def test_discovery_passes_token_in_header_argument_not_query(context, monkeypatch):
    _, actor, _, _, _ = context
    session, _ = transport(context, monkeypatch)
    complete(actor, session.pk, 'a' * 64)
    request = Mock(return_value={'list': []})
    monkeypatch.setattr(ads, 'request_json', request)
    ads.discover(actor, session.pk)
    query = parse_qs(urlsplit(request.call_args.args[2]).query)
    assert set(query) == {'app_id', 'secret'}
    assert request.call_args.kwargs['token'] == 'SYNTHETIC_TOKEN'
    assert 'SYNTHETIC_TOKEN' not in request.call_args.args[2]


@pytest.mark.parametrize('timezone,display,expected', [
    (8, 'Asia/Manila', 'Asia/Manila'), ('8', 'America/New_York', 'America/New_York'),
    ('Asia/Manila', '', 'Asia/Manila'), ('8', '', None), (8, 'UTC+08:00', None),
])
def test_account_timezone_never_guesses_numeric_offset(timezone, display, expected):
    account = {'timezone': timezone, 'display_timezone': display}
    if expected is None:
        with pytest.raises(ValueError): ads.account_timezone(account)
    else: assert ads.account_timezone(account) == expected
