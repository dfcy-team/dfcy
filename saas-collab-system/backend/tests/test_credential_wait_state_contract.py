"""Offline credential boundary and durable pre-request state regressions."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery.exceptions import WorkerShutdown
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations import credential_access as access
from apps.integrations.custody import CustodyError, CustodyReferenceNotFound, HttpCustodyBackend
from tests.test_flash_sales import configured, shop
from tests.test_shopee_readonly_runtime import configured as readonly_configured


@pytest.mark.parametrize('case,code', [
    ('invalid', 'RUNTIME_CONFIG_INVALID'),
    ('refuse', 'CUSTODY_NOT_CONFIGURED'),
    ('missing_ca', 'CUSTODY_NOT_CONFIGURED'),
    ('construction_error', 'CUSTODY_NOT_CONFIGURED'),
    ('non_http', 'CUSTODY_NOT_CONFIGURED'),
])
def test_checked_backend_rejects_invalid_local_readiness(settings, monkeypatch, case, code):
    settings.DEBUG = False
    snapshot = {'valid': case != 'invalid', 'config': {'custody': {
        'backend': 'refuse' if case == 'refuse' else 'http',
    }}}
    if case == 'missing_ca':
        snapshot['config']['custody']['ca_file_path'] = '/synthetic-missing-ca'
        monkeypatch.setattr(access, 'Path', lambda _: SimpleNamespace(is_file=lambda: False))
    monkeypatch.setattr(access, 'runtime_snapshot', lambda: snapshot)
    constructor = Mock(return_value=object())
    if case == 'construction_error':
        constructor.side_effect = CustodyError('synthetic private construction detail')
    monkeypatch.setattr(access, 'get_custody_backend', constructor)
    with pytest.raises(access.CredentialAccessError) as caught:
        access.checked_custody_backend()
    assert caught.value.code == code
    assert 'synthetic private' not in str(caught.value)
    if case in {'invalid', 'refuse', 'missing_ca'}:
        constructor.assert_not_called()


def test_checked_backend_accepts_valid_http_construction_without_remote_probe(settings, monkeypatch):
    settings.DEBUG = False
    backend = object.__new__(HttpCustodyBackend)
    monkeypatch.setattr(access, 'runtime_snapshot', lambda: {
        'valid': True, 'config': {'custody': {'backend': 'http'}},
    })
    monkeypatch.setattr(access, 'get_custody_backend', lambda: backend)
    assert access.checked_custody_backend() is backend


def test_deploy_and_worker_guards_fail_closed_with_safe_code(settings, monkeypatch, caplog):
    settings.DEBUG = False
    settings.FLASH_SALES_WORKERS_ENABLED = True
    close = Mock()
    monkeypatch.setattr(access.connections, 'close_all', close)
    def refuse():
        raise access.CredentialAccessError('CUSTODY_NOT_CONFIGURED')
    monkeypatch.setattr(access, 'checked_custody_backend', refuse)
    errors = access.check_integration_credentials()
    assert len(errors) == 1 and errors[0].id == 'integrations.E001'
    with pytest.raises(WorkerShutdown) as caught:
        access.check_worker_credentials()
    assert caught.value.args == (1,)
    close.assert_called_once_with()
    assert 'CUSTODY_NOT_CONFIGURED' in caplog.text


@pytest.mark.parametrize('delta', [None, -1])
def test_shopee_readonly_missing_or_expired_token_is_rejected_before_http(monkeypatch, delta):
    client, http = readonly_configured(monkeypatch, {
        'contract_approved': True, 'api_host': 'https://approved.example.test',
    })
    client.resource_type = 'sales_order'
    client.authorization.expires_at = None if delta is None else timezone.now() + timedelta(seconds=delta)
    with pytest.raises(ValidationError, match='SHOPEE_TOKEN_REFRESH_REQUIRED'):
        client._request('/api/v2/order/get_order_list', {})
    http.request.assert_not_called()
    client.custody.retrieve_secret.assert_not_called()


@pytest.mark.parametrize('failure,code', [
    (CustodyReferenceNotFound('synthetic private custody detail'), 'CREDENTIAL_REFERENCE_MISSING'),
    (CustodyError('synthetic private custody detail'), 'CUSTODY_UNAVAILABLE'),
])
def test_shopee_readonly_custody_error_is_sanitized_before_http(monkeypatch, failure, code):
    client, http = readonly_configured(monkeypatch, {
        'contract_approved': True, 'api_host': 'https://approved.example.test',
    })
    client.resource_type = 'sales_order'
    client.custody.retrieve_secret.side_effect = failure
    with pytest.raises(ValidationError) as caught:
        client._request('/api/v2/order/get_order_list', {})
    assert str(caught.value.detail[0]) == access.MESSAGES[code]
    assert 'synthetic private' not in str(caught.value)
    http.request.assert_not_called()
    client.custody.retrieve_access_token.assert_not_called()


@pytest.mark.django_db
def test_known_credential_deferral_restores_prepared_write_without_resubmission(shop):
    from apps.flash_sales import engine
    from apps.flash_sales.models import Intent, WriteOperation
    from apps.flash_sales.provider import CredentialWait
    from apps.flash_sales.services import submit
    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id='credential-prepared-write', store_ids=[store.pk]).tasks.get()
    task = engine.claim(task.pk)
    assert task is not None
    intent = Intent.objects.create(tenant=user.tenant, task=task, store=store, slot_id='synthetic-slot')
    adapter = SimpleNamespace(call=Mock(side_effect=CredentialWait(access.CredentialAccessError('TOKEN_REFRESH_REQUIRED'))))
    with pytest.raises(CredentialWait):
        engine.write_once(task, intent, 'create', 'create_shop_flash_sale', {'synthetic': True}, adapter)
    operation = WriteOperation.objects.get(intent=intent, key='create')
    assert operation.status == 'prepared' and operation.response == {}
    assert operation.submitted_at is not None
    adapter.call.assert_called_once_with('create_shop_flash_sale', body={'synthetic': True})
    task.refresh_from_db()
    assert task.retry_count == 0


@pytest.mark.django_db
def test_success_clears_credential_wait_marker(shop, monkeypatch):
    from apps.flash_sales import engine
    from apps.flash_sales.services import submit
    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id='credential-wait-cleared', store_ids=[store.pk]).tasks.get()
    task.state['credential_wait'] = 'TOKEN_REFRESH_REQUIRED'
    task.save(update_fields=['state'])
    monkeypatch.setattr(engine, 'step', lambda *_args, **_kwargs: ('succeeded', 'synthetic success'))
    assert engine.run_step(task.pk, adapter=object()) == 'succeeded'
    task.refresh_from_db()
    assert 'credential_wait' not in task.state
    assert task.retry_count == 0
