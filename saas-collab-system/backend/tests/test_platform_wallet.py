"""Synthetic API fixtures only. No production network, tokens, or business writes."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo
import uuid

import pytest
from django.utils import timezone
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.finance.platform_wallet_collectors import collect_tiktok, collect_lazada, money, TIKTOK_PATH, LAZADA_PATH
from apps.finance.platform_wallet_models import PlatformApiWithdrawal, PlatformWalletCursor, PlatformWalletSync
from apps.finance.platform_wallet_service import persist, sync_store
from apps.finance.tasks import run_platform_wallet_sync, dispatch_platform_wallet_sync
from tests.test_lazada_native_api import context

START = datetime(2026, 10, 31, 0, 0, tzinfo=UTC)
END = START + timedelta(hours=12)


def tiktok_row(identifier='SYNTHETIC-1', **changes):
    return dict(id=identifier, type='WITHDRAW', amount='-10.120000', currency='PHP',
                status='PROCESSING', create_time=int(START.timestamp()) + 3600, **changes)


def tiktok_client(pages):
    return SimpleNamespace(authorization=SimpleNamespace(shop_cipher='SYNTHETIC_SHOP'),
                           _request=Mock(side_effect=pages))


def page(rows, total=None, token=''):
    return {'code': 0, 'data': {'withdrawals': rows, 'total_count': len(rows) if total is None else total, 'next_page_token': token}}


def test_tiktok_collects_only_returned_fields_and_preserves_sign():
    source = tiktok_row()
    source['private_bank_account'] = 'SYNTHETIC-PRIVATE-DO-NOT-SAVE'
    client = tiktok_client([page([source])])
    rows, _ = collect_tiktok(client, START, END)
    assert rows[0]['signed_amount'] == Decimal('-10.120000')
    assert rows[0]['raw_status'] == 'PROCESSING'
    assert rows[0]['api_fields'] == {}
    assert 'SYNTHETIC-PRIVATE' not in str(rows)
    path = client._request.call_args.args[0]
    query = client._request.call_args.kwargs['query']
    assert path == TIKTOK_PATH and query['types'] == 'WITHDRAW,REVERSE'
    assert query['create_time_ge'] == int(START.timestamp())


def test_tiktok_paginates_and_distinguishes_reversal():
    reverse = {**tiktok_row('SYNTHETIC-2'), 'type': 'REVERSE'}
    client = tiktok_client([page([tiktok_row()], 2, 'next'), page([reverse], 2)])
    rows, _ = collect_tiktok(client, START, END)
    assert [row['transaction_type'] for row in rows] == ['WITHDRAW', 'REVERSE']
    assert client._request.call_args_list[1].kwargs['query']['page_token'] == 'next'


@pytest.mark.parametrize('payload', [{}, {'code': 5, 'data': {}}, page([], 1), page([{**tiktok_row(), 'type': 'SETTLE'}]), page([{**tiktok_row(), 'currency': None}])])
def test_invalid_financial_pages_never_become_empty_success(payload):
    with pytest.raises(ValidationError):
        collect_tiktok(tiktok_client([payload]), START, END)


def test_duplicate_transaction_or_cursor_rejected():
    client = tiktok_client([page([tiktok_row()], 2, 'same'), page([tiktok_row()], 2, 'same')])
    with pytest.raises(ValidationError):
        collect_tiktok(client, START, END)


@pytest.mark.parametrize('value', [None, True, float('nan'), 'NaN', '1e9', '1.000000001', 'bad', '10,00'])
def test_money_does_not_guess_or_round(value):
    with pytest.raises(ValidationError):
        money(value)


def test_lazada_requires_confirmed_timezone_before_network():
    client = SimpleNamespace(_request=Mock())
    with pytest.raises(ValidationError, match='时区'):
        collect_lazada(client, START, END)
    client._request.assert_not_called()


def test_lazada_actual_count_can_differ_and_is_not_a_completed_bank_receipt():
    client = SimpleNamespace(wallet_transaction_timezone=UTC, _request=Mock(return_value={
        'success': True, 'data': {'page_info': {'page_num': 1, 'page_size': 100, 'total_count': 2},
        'transactions': [{'transaction_number': 'SYNTHETIC-LZ', 'transaction_time': '31 Oct 2026 01:00:00',
                          'type': 'Withdrawal', 'sub_type': 'Auto Withdrawal', 'amount': '-1,234.560000', 'currency': 'PHP',
                          'payee_account': 'SYNTHETIC-PRIVATE'}]}}))
    rows, info = collect_lazada(client, START, END)
    assert len(rows) == 1 and info['reported_count_difference'] == 1
    assert rows[0]['raw_status'] is None and rows[0]['signed_amount'] == Decimal('-1234.560000')
    assert rows[0]['source_endpoint'] == LAZADA_PATH
    assert 'payee_account' not in str(rows)


def client_for(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def normalized_row():
    return {'external_id': 'SYNTHETIC-LZ', 'source_endpoint': LAZADA_PATH, 'transaction_type': 'Auto Withdrawal',
            'currency': 'PHP', 'original_amount': '-10.000000', 'signed_amount': Decimal('-10'),
            'occurred_at_utc': START, 'raw_status': None, 'api_fields': {}}


@pytest.mark.django_db
def test_api_only_page_does_not_create_sync_or_show_imported_records(context):
    from apps.finance.services import import_demo_withdrawal
    actor, auth = context
    import_demo_withdrawal(actor.tenant)
    client = client_for(actor)
    data = client.get('/api/finance/platform-wallet/overview/').json()['data']
    assert len(data['stores']) == 1
    assert data['stores'][0]['balance'] is None and data['stores'][0]['currency'] is None
    assert PlatformWalletSync.objects.count() == 0
    assert client.get('/api/finance/platform-wallet/withdrawals/').json()['data']['items'] == []


@pytest.mark.django_db
def test_idempotent_api_projection_does_not_write_old_finance_models(context):
    from apps.finance.models import WithdrawalRecord, BankReceiptImport, PlatformFinanceTransaction
    actor, auth = context
    from django.db import transaction
    with transaction.atomic():
        persist(actor, auth, [normalized_row()], END)
        persist(actor, auth, [normalized_row()], END)
    assert PlatformApiWithdrawal.objects.count() == 1
    assert WithdrawalRecord.objects.count() == BankReceiptImport.objects.count() == PlatformFinanceTransaction.objects.count() == 0
    row = client_for(actor).get('/api/finance/platform-wallet/withdrawals/').json()['data']['items'][0]
    assert row['status'] is None and row['completed_at'] is None and row['received_amount'] is None


@pytest.mark.django_db
def test_tenant_and_store_currency_scopes_remain_conjunctive(context):
    from tests.test_finance_remediation import user_with_scopes
    from apps.masterdata.models import StoreMaster
    from apps.permissions.models import DataScope
    from tests.test_sales_management import grant
    actor, auth = context
    other = StoreMaster.objects.create(tenant=actor.tenant, platform=auth.store.platform, code='OTHER', name='Other', country_code='PH', currency='PHP')
    viewer, client = user_with_scopes(actor.tenant, 'wallet-viewer', {'finance.view': {'store_ids': [auth.store_id], 'currencies': ['USD']}})
    grant(viewer, 'finance.view', DataScope.ScopeType.CUSTOM, {'store_ids': [other.pk], 'currencies': ['PHP']})
    with transaction.atomic():
        persist(actor, auth, [normalized_row()], END)
    assert len(client.get('/api/finance/platform-wallet/overview/').json()['data']['stores']) == 2
    assert client.get('/api/finance/platform-wallet/withdrawals/').json()['data']['items'] == []
    assert client.post('/api/finance/platform-wallet/sync/', {}, format='json').status_code == 403


@pytest.mark.django_db
def test_manual_request_is_durable_and_deduplicated_if_broker_down(context, monkeypatch):
    actor, auth = context
    send = Mock(side_effect=RuntimeError('SYNTHETIC-PRIVATE-ERROR'))
    monkeypatch.setattr(run_platform_wallet_sync, 'apply_async', send)
    client = client_for(actor)
    first = client.post('/api/finance/platform-wallet/sync/', {}, format='json')
    second = client.post('/api/finance/platform-wallet/sync/', {}, format='json')
    assert first.status_code == second.status_code == 202
    assert first.json()['data']['dispatched'] is False and send.call_count == 1
    assert PlatformWalletSync.objects.get().last_error_code == 'BROKER_UNAVAILABLE'
    assert 'SYNTHETIC-PRIVATE' not in str(first.json())


@pytest.mark.django_db
def test_scheduled_disabled_and_duplicate_delivery_do_not_execute(context, monkeypatch):
    actor, _ = context
    row = PlatformWalletSync.objects.create(actor=actor, tenant=actor.tenant, state='idle')
    collect = Mock()
    monkeypatch.setattr('apps.finance.tasks.sync_store', collect)
    assert run_platform_wallet_sync(row.pk, scheduled=True)['status'] == 'not_due'
    assert run_platform_wallet_sync(row.pk)['status'] == 'not_requested'
    collect.assert_not_called()


@pytest.mark.django_db
def test_expired_manual_lease_is_requeued(context, monkeypatch):
    actor, _ = context
    row = PlatformWalletSync.objects.create(actor=actor, tenant=actor.tenant, state='running',
        lease=uuid.uuid4(), running_until=timezone.now()-timedelta(minutes=1))
    send = Mock()
    monkeypatch.setattr(run_platform_wallet_sync, 'apply_async', send)
    dispatch_platform_wallet_sync()
    row.refresh_from_db()
    assert row.state == 'queued' and send.call_count == 1


@pytest.mark.django_db
def test_sync_failure_does_not_advance_watermark_or_leak_error(context, monkeypatch):
    actor, auth = context
    row = PlatformWalletSync.objects.create(actor=actor, tenant=actor.tenant, state='queued')
    monkeypatch.setattr('apps.finance.tasks.sync_store', Mock(side_effect=RuntimeError('SYNTHETIC-SIGNED-URL')))
    assert run_platform_wallet_sync(row.pk)['status'] == 'partial'
    row.refresh_from_db()
    assert 'SYNTHETIC' not in str(row.summary)
    assert PlatformWalletCursor.objects.get().watermark is None


@pytest.mark.django_db
def test_forward_only_scope_starts_at_activation_and_does_not_refresh_token(context, monkeypatch):
    actor, auth = context
    auth.integration_config.platform_config['wallet_transaction_time_policies'] = {
        str(auth.store_id): {'timezone': 'Asia/Shanghai', 'source': 'user_specified'}}
    auth.integration_config.save()
    lease = uuid.uuid4()
    activation = timezone.now()-timedelta(hours=1)
    row = PlatformWalletSync.objects.create(actor=actor, tenant=actor.tenant, activated_at=activation,
        lease=lease, running_until=timezone.now()+timedelta(minutes=10))
    client = SimpleNamespace(preflight=Mock())
    monkeypatch.setattr('apps.finance.platform_wallet_service.LazadaReadonlyClient', Mock(return_value=client))
    collect = Mock(return_value=([], {}))
    monkeypatch.setattr('apps.finance.platform_wallet_service.collect_lazada', collect)
    result = sync_store(row, auth.store, end=timezone.now(), lease=lease)
    assert result['status'] == 'succeeded'
    assert collect.call_args.args[1] == activation
    assert client.wallet_transaction_timezone.key == 'Asia/Shanghai'
    assert client.wallet_transaction_time_source == 'user_specified'
    assert PlatformWalletCursor.objects.get().watermark is not None


@pytest.mark.django_db
def test_lazada_user_time_policy_does_not_change_store_timezone_or_cover_other_stores(context):
    from apps.finance.platform_wallet_service import lazada_wallet_time_policy
    actor, auth = context
    archive_timezone = auth.store.timezone
    auth.integration_config.platform_config['wallet_transaction_time_policies'] = {
        str(auth.store_id): {'timezone': 'Asia/Shanghai', 'source': 'user_specified'}}
    zone, source = lazada_wallet_time_policy(auth)
    assert zone.key == 'Asia/Shanghai' and source == 'user_specified'
    auth.store.refresh_from_db()
    assert auth.store.timezone == archive_timezone
    auth.integration_config.platform_config['wallet_transaction_time_policies'] = {
        str(auth.store_id + 1): {'timezone': 'Asia/Shanghai', 'source': 'user_specified'}}
    with pytest.raises(ValidationError):
        lazada_wallet_time_policy(auth)


def test_lazada_china_time_preserves_provenance_and_activation_boundary():
    transactions = [dict(transaction_number=str(i), transaction_time=time, type='Withdrawal',
        sub_type='Auto Withdrawal', amount='-1.00', currency='PHP')
        for i, time in enumerate(['31 Oct 2026 07:59:59', '31 Oct 2026 08:00:00'])]
    client = SimpleNamespace(wallet_transaction_timezone=ZoneInfo('Asia/Shanghai'),
        wallet_transaction_time_source='user_specified', _request=Mock(return_value={
            'success': True, 'data': {'page_info': {'page_num': 1, 'page_size': 100, 'total_count': 2},
                                    'transactions': transactions}}))
    rows, _ = collect_lazada(client, START, START + timedelta(minutes=1))
    assert len(rows) == 1 and rows[0]['occurred_at_utc'] == START
    assert rows[0]['api_fields']['transaction_time'] == '31 Oct 2026 08:00:00'
    assert rows[0]['api_fields']['time_interpretation'] == {
        'timezone': 'Asia/Shanghai', 'source': 'user_specified'}
    assert client._request.call_args.args[1]['start_time'] == '20261031'


@pytest.mark.django_db
def test_schedule_activation_is_opt_in_and_cannot_be_backdated(context):
    actor, _ = context
    client = client_for(actor)
    response = client.post('/api/finance/platform-wallet/schedule/',
                           {'enabled': False, 'interval_minutes': 60}, format='json')
    assert response.status_code == 200
    row = PlatformWalletSync.objects.get()
    assert row.activated_at is None and row.next_run_at is None
    assert client.post('/api/finance/platform-wallet/schedule/',
        {'enabled': True, 'interval_minutes': 60, 'activated_at': START.isoformat()}, format='json').status_code == 400
    before = timezone.now()
    assert client.post('/api/finance/platform-wallet/schedule/',
        {'enabled': True, 'interval_minutes': 60}, format='json').status_code == 200
    row.refresh_from_db()
    assert before <= row.activated_at <= timezone.now()
    assert row.next_run_at > row.activated_at


@pytest.mark.django_db
def test_revoked_actor_cannot_execute_queued_sync(context, monkeypatch):
    actor, _ = context
    row = PlatformWalletSync.objects.create(actor=actor, tenant=actor.tenant, state='queued')
    actor.is_active = False
    actor.save(update_fields=['is_active'])
    collect = Mock()
    monkeypatch.setattr('apps.finance.tasks.sync_store', collect)
    assert run_platform_wallet_sync(row.pk)['status'] == 'blocked'
    collect.assert_not_called()
    row.refresh_from_db()
    assert not row.enabled and row.last_error_code == 'PERMISSION_CHANGED'
