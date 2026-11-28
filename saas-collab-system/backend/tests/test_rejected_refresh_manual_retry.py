from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations import automatic_refresh as automatic, marketplace_oauth_service as oauth
from apps.integrations import refresh_commit_recovery as recovery
from apps.integrations.models import AutomaticRefreshAttempt
from tests.test_refresh_commit_recovery import case
from tests.test_flash_sales import shop


def rejected_journal(case):
    return {'schema': 1, 'phase': 'exchange_in_flight', 'scope': recovery._scope(case.auth),
            'source_reference': recovery._digest(case.auth.token_id),
            'source_version': case.auth.credential_reference_version,
            'operation_id': 'synthetic-rejected-operation',
            'lease_until': (timezone.now()-timedelta(minutes=1)).isoformat()}


@pytest.mark.django_db(transaction=True)
def test_manual_retry_after_expired_definitive_rejection(case):
    attempt = AutomaticRefreshAttempt.objects.create(request_key=automatic._attempt_key(case.auth),
        tenant=case.auth.tenant, status='failed', failure_category='authorization_rejected',
        finished_at=timezone.now()-timedelta(minutes=2), commit_recovery=rejected_journal(case))
    original = attempt.commit_recovery.copy()
    result = oauth.refresh_marketplace_authorization(case.auth, actor=case.actor)
    assert result.token_id == case.result['token_id']
    case.provider.refresh_authorization.assert_called_once()
    attempt.refresh_from_db()
    assert attempt.status == 'failed' and attempt.commit_recovery == original


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('changed', ['running', 'unfinished', 'uncertain', 'candidate', 'live_lease',
    'no_lease', 'commit_pending', 'legacy_schema', 'foreign_scope', 'changed_generation',
    'recover_only', 'resuming_exchange'])
def test_manual_retry_keeps_uncertain_or_live_recovery_fenced(case, changed):
    data = rejected_journal(case)
    status, category, finished = 'failed', 'authorization_rejected', timezone.now()-timedelta(minutes=2)
    if changed == 'running': status = 'running'
    elif changed == 'unfinished': finished = None
    elif changed == 'uncertain': category = 'rotation_uncertain'
    elif changed == 'candidate': data['candidate'] = {'token_id': 'SYNTHETIC_SAVED_REFERENCE'}
    elif changed == 'live_lease': data['lease_until'] = (timezone.now()+timedelta(minutes=1)).isoformat()
    elif changed == 'no_lease': data.pop('lease_until')
    elif changed == 'commit_pending': data['phase'] = 'commit_pending'
    elif changed == 'legacy_schema': data.pop('schema')
    elif changed == 'foreign_scope': data['scope'] = 'different-application'
    elif changed == 'changed_generation': data['source_version'] += 1
    elif changed == 'recover_only': data['recover_only'] = True
    elif changed == 'resuming_exchange': data['resuming_exchange'] = True
    AutomaticRefreshAttempt.objects.create(request_key=automatic._attempt_key(case.auth), tenant=case.auth.tenant,
        status=status, failure_category=category, finished_at=finished, commit_recovery=data)
    with pytest.raises(ValidationError, match='自动恢复'):
        oauth.refresh_marketplace_authorization(case.auth, actor=case.actor)
    case.provider.refresh_authorization.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('balance', ['12.50', 'NaN', None])
def test_advertising_validation_uses_ads_balance_and_never_shop_identity(case, monkeypatch, balance):
    from unittest.mock import Mock
    from apps.integrations import shopee_advertising
    config = case.auth.integration_config
    config.platform_config = {**config.platform_config, 'api_type': 'advertising'}
    config.save(update_fields=['platform_config'])
    case.auth.integration_config = config
    from apps.integrations import readonly_clients
    monkeypatch.setattr(readonly_clients, 'get_custody_backend', lambda: case.custody)
    clients = []
    original = shopee_advertising.ShopeeAdvertisingReadonlyClient
    class CheckedClient(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            clients.append(self)
    request = Mock(return_value={'data_timestamp': 1700000000, 'total_balance': balance})
    monkeypatch.setattr(CheckedClient, '_ads_request', request)
    monkeypatch.setattr(shopee_advertising, 'ShopeeAdvertisingReadonlyClient', CheckedClient)
    if balance == '12.50':
        result = automatic.validate_refreshed_authorization(case.auth)
        assert result['records'][0]['kind'] == 'balance'
    else:
        with pytest.raises(ValidationError):
            automatic.validate_refreshed_authorization(case.auth)
    request.assert_called_once_with('get_total_balance', {})
    assert clients[0].resource_type == 'advertising_report'
    assert clients[0].http.max_retries == 0
    case.provider.fetch_authorized_stores.assert_not_called()
    case.provider.refresh_authorization.assert_not_called()
