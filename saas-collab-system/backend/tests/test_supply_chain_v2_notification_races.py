from datetime import timedelta
from unittest.mock import Mock, patch
import pytest
import requests
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.supply_chain import notifications as notify, notification_config as cfg
from apps.supply_chain.models import NotificationChannel, NotificationAttempt, domain_write
from apps.supply_chain.worktool import WorkTool, TransportError
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_notifications import custody, _ready, _attempt, FakeWorkTool


def prepared(world, custody, settings):
    settings.SUPPLY_NOTIFICATION_DELIVERY_ENABLED = True
    actor, channel, binding, order, box = _ready(world, custody)
    box = notify.prepare(actor, box.pk, {'expected_version': box.version}, 'prepare')
    with domain_write():
        channel.connectivity, channel.last_checked_at = 'online', timezone.now()
        channel.save()
    return actor, channel, binding, order, box


@pytest.mark.parametrize('first_success', [True, False])
def test_conflicting_execution_receipts_never_allow_direct_retry(world, custody, settings, first_success):
    actor, channel, _, _, box = prepared(world, custody, settings)
    part = box.parts.get(kind='summary')
    _attempt(world, actor, channel, part, box, message_id='conflict')
    success = {'messageId': 'conflict', 'type': 203, 'errorCode': 0, 'successList': ['SupplierA'], 'failList': []}
    failure = {**success, 'errorCode': 201102, 'successList': [], 'failList': ['SupplierA']}
    for payload in ([success, failure] if first_success else [failure, success]):
        notify.record_result(channel, payload)
    part.refresh_from_db()
    assert part.status == 'unknown'
    with pytest.raises(ValidationError):
        notify.retry(actor, box.pk, part.pk, {'expected_version': part.version, 'reason': 'retry'}, 'bad-retry')
    # Another failure must not erase the earlier successful execution evidence.
    notify.record_result(channel, {**failure, 'errorCode': 201104})
    part.refresh_from_db()
    assert part.status == 'unknown'


def test_retarget_between_dispatch_precheck_and_claim_uses_claimed_robot(world, custody, settings):
    actor, old_channel, binding, _, box = prepared(world, custody, settings)
    with domain_write():
        new_channel = NotificationChannel.objects.create(tenant=actor.tenant, created_by=actor,
            name='second-channel', sender_name='Buyer B', device_name='B', credential_id='fake-B',
            credential_digest='b'*64, enabled=True, enabled_by=actor, connectivity='online', last_checked_at=timezone.now())
        new_channel.qualified_digest = cfg.channel_digest(new_channel); new_channel.save()
    original_claim = notify._claim

    def switch_then_claim(pk):
        with domain_write():
            binding.channel = new_channel
            binding.target_title = 'SupplierB'
            binding.verified_digest = cfg.binding_digest(binding)
            binding.version += 1; binding.save()
        box.refresh_from_db()
        notify.retarget(actor, box.pk, {'expected_version': box.version, 'reason': 'before any send'}, 'retarget')
        return original_claim(pk)

    adapter = FakeWorkTool()
    adapter.send = Mock(return_value='new-robot-message')
    with patch.object(notify, '_claim', side_effect=switch_then_claim):
        assert notify.dispatch_one(box.pk, adapter=adapter) == 'accepted'
    sent_channel, sent_title = adapter.send.call_args.args
    assert sent_channel.pk == new_channel.pk and sent_channel.pk != old_channel.pk
    assert sent_title == 'SupplierB'
    assert NotificationAttempt.objects.get(provider_message_id='new-robot-message').channel_id == new_channel.pk


def test_late_success_after_observed_failure_and_retry_quarantines_pending_part(world, custody, settings):
    actor, channel, _, _, box = prepared(world, custody, settings)
    part = box.parts.get(kind='summary')
    _attempt(world, actor, channel, part, box, message_id='late-success')
    failure = {'messageId': 'late-success', 'type': 203, 'errorCode': 201102,
        'successList': [], 'failList': ['SupplierA']}
    notify.record_result(channel, failure)
    part.refresh_from_db()
    notify.verify(actor, box.pk, part.pk, {'expected_version': part.version, 'result': 'not_delivered',
        'evidence': 'stopped and checked group', 'execution_stopped': True}, 'manual-failure')
    part.refresh_from_db()
    notify.retry(actor, box.pk, part.pk, {'expected_version': part.version, 'reason': 'safe retry'}, 'retry-late')
    notify.record_result(channel, {**failure, 'errorCode': 0, 'successList': ['SupplierA'], 'failList': []})
    part.refresh_from_db(); assert part.status == 'unknown'
    adapter = FakeWorkTool()
    notify.dispatch_one(box.pk, adapter=adapter)
    assert adapter.sent == []


def test_new_notification_is_not_starved_by_older_blocked_records(world, custody, settings):
    from apps.supply_chain.models import NotificationOutbox
    from tests.test_supply_chain_v2_foundation import confirmed_order, po_payload
    actor, _, _, _, old = prepared(world, custody, settings)
    with domain_write():
        old.next_attempt_at = timezone.now() - timedelta(minutes=1); old.save()
    order = confirmed_order(world, actor, key='new-after-blocked', payload=po_payload(world, number='PO-NEW'))
    new = NotificationOutbox.objects.get(order=order)
    with patch.object(notify, 'dispatch_one', return_value='blocked') as dispatch:
        notify.dispatch_due(limit=1)
    dispatch.assert_called_once_with(new.pk, adapter=None)


@pytest.mark.parametrize('observation', ['delivered', 'not_delivered'])
def test_reconciliation_skips_observed_or_superseded_old_attempt(world, custody, settings, observation):
    actor, channel, _, _, box = prepared(world, custody, settings)
    part = box.parts.get(kind='summary')
    _attempt(world, actor, channel, part, box, message_id='old-unknown', outcome='unknown')
    with domain_write():
        part.status = 'unknown'; part.save()
    notify.verify(actor, box.pk, part.pk, {'expected_version': part.version, 'result': observation,
        'evidence': 'synthetic observation', 'execution_stopped': True}, 'observed')
    if observation == 'not_delivered':
        part.refresh_from_db()
        notify.retry(actor, box.pk, part.pk, {'expected_version': part.version, 'reason': 'stopped'}, 'retry')
        number = 2
    else:
        part = box.parts.get(kind='link'); number = 1
    _attempt(world, actor, channel, part, box, message_id='current', number=number)
    with domain_write():
        part.status = 'accepted'; part.save()
    box.refresh_from_db()
    adapter = FakeWorkTool(result={'messageId': 'current', 'type': 203, 'errorCode': 0,
        'successList': ['SupplierA'], 'failList': []})
    notify.reconcile(actor, box.pk, {'expected_version': box.version}, 'reconcile', adapter=adapter)
    assert adapter.result_calls == ['current']
    part.refresh_from_db(); assert part.status == 'executed'


def test_worktool_text_and_file_contracts_do_not_use_mass_send_or_chat_id(world):
    channel = object()
    response = Mock(status_code=200, content=b'{}')
    response.json.return_value = {'code': 200, 'data': 'command-1'}
    with patch('apps.supply_chain.worktool.resolve_robot', return_value='synthetic-id'), \
            patch('apps.supply_chain.worktool.reserve_request'), patch('apps.supply_chain.worktool.requests.request', return_value=response) as http:
        assert WorkTool().send(channel, 'SupplierA', text='test') == 'command-1'
        assert http.call_args.args == ('POST', 'https://api.worktool.ymdyes.cn/wework/sendRawMessage')
        assert http.call_args.kwargs['json'] == {'socketType': 2, 'list': [{'titleList': ['SupplierA'], 'type': 203, 'receivedContent': 'test'}]}
        WorkTool().send(channel, 'SupplierA', file_url='https://example.test/private-file', object_name='PO.xlsx')
        command = http.call_args.kwargs['json']['list'][0]
        assert command == {'titleList': ['SupplierA'], 'type': 218, 'fileUrl': 'https://example.test/private-file', 'objectName': 'PO.xlsx', 'fileType': 'file'}
        assert http.call_args.kwargs['allow_redirects'] is False


@pytest.mark.parametrize('mode,ambiguous', [('connect', False), ('read', True), ('server', True), ('missing_id', True)])
def test_transport_ambiguity_is_not_treated_as_safe_to_resend(world, mode, ambiguous):
    response = Mock(status_code=500 if mode == 'server' else 200, content=b'{}')
    response.json.return_value = {'code': 200, 'data': None}
    exception = requests.ConnectTimeout('robotId=secret') if mode == 'connect' else requests.ReadTimeout('robotId=secret') if mode == 'read' else None
    with patch('apps.supply_chain.worktool.resolve_robot', return_value='synthetic-id'), \
            patch('apps.supply_chain.worktool.reserve_request'), patch('apps.supply_chain.worktool.requests.request', return_value=response, side_effect=exception):
        with pytest.raises(TransportError) as error:
            WorkTool().send(object(), 'SupplierA', text='test')
    assert error.value.ambiguous is ambiguous
    assert 'secret' not in str(error.value)
