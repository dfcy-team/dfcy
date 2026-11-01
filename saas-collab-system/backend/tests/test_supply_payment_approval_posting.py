from datetime import timedelta

import pytest
from rest_framework.exceptions import ValidationError

from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.payment_voucher_models import PaymentVoucher
from apps.supply_chain.payment_request_models import SupplyPaymentRequest, SupplyPaymentBatch
from apps.supply_chain.models import PayeeAccount, domain_write
from apps.workflows.models import ApprovalRequest, WorkflowAuditEvent
from tests.test_supply_payment_request_evidence import _setup_request, _upload, _grant, _png
from tests.test_supply_payment_batch import _second_shipment
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import write, BASE
from apps.supply_chain.dates import business_date

pytestmark = pytest.mark.django_db


def pending(world, monkeypatch):
    values = _setup_request(world, monkeypatch)
    ApprovalRequest.objects.filter(pk=values[4]['approval_id']).update(status='pending', reviewed_by=None)
    return values


def approve(client, row, **changes):
    payment = dict(date=str(business_date()), expected_version=row['version'], reference_number='AUTO-REF', notes='paid')
    payment.update(changes)
    return client.post(f"/api/internal/workflow/approvals/{row['approval_id']}/approve/", {'note': 'ok', 'payment': payment}, format='json')


def assert_pending(row):
    assert ApprovalRequest.objects.get(pk=row['approval_id']).status == 'pending'
    assert PaymentRecord.objects.count() == 0
    assert PaymentVoucher.objects.count() == 0
    assert not WorkflowAuditEvent.objects.filter(resource_type='approval', resource_id=str(row['approval_id']), action='approve').exists()


def test_single_approval_posts_and_replay_keeps_one_payment(world, monkeypatch):
    buyer, api, shipment, account, row, actor, client = pending(world, monkeypatch)
    context = client.get(f"/api/internal/workflow/approvals/{row['approval_id']}/").data['data']['payment_context']
    assert context['request_id'] == row['id'] and context['can_upload']
    upload = _upload(client, shipment, row)
    assert upload.status_code == 201, upload.data
    row = upload.data['data']
    response = approve(client, row)
    assert response.status_code == 200, response.data
    assert response.data['data']['payment_context']['status'] == 'paid'
    assert PaymentRecord.objects.count() == PaymentVoucher.objects.count() == 1
    assert SupplyPaymentRequest.objects.get(pk=row['id']).status == 'paid'
    assert approve(client, row).status_code == 200
    assert PaymentRecord.objects.count() == 1
    assert _upload(client, shipment, row, key='after-paid').status_code == 400


@pytest.mark.parametrize('guard', ['voucher', 'date', 'version', 'account', 'finance', 'balance'])
def test_single_failure_rolls_back_approval_and_posting(world, monkeypatch, guard):
    buyer, api, shipment, account, row, actor, client = pending(world, monkeypatch)
    if guard != 'voucher':
        row = _upload(client, shipment, row).data['data']
    changes = {}
    if guard == 'date': changes['date'] = str(business_date() + timedelta(days=1))
    if guard == 'version': changes['expected_version'] = row['version'] - 1
    if guard == 'account':
        with domain_write():
            obj = PayeeAccount.objects.get(pk=account['id']); obj.bank_name = 'changed'; obj.save(update_fields=['bank_name'])
    if guard == 'finance':
        from apps.permissions.models import UserRole
        for binding in UserRole.objects.filter(user=actor): binding.role.permissions.remove(*binding.role.permissions.filter(code='finance.reconcile'))
    if guard == 'balance':
        from apps.supply_chain import costs
        original = costs.payment_summary
        def changed(*args, **kwargs):
            state = original(*args, **kwargs); state['summary']['remaining_amount'] = '0.0000'; return state
        monkeypatch.setattr(costs, 'payment_summary', changed)
    response = approve(client, row, **changes)
    assert response.status_code >= 400, response.data
    assert_pending(row)


@pytest.mark.parametrize('fail_second', [False, True])
def test_batch_approval_is_atomic(world, monkeypatch, fail_second):
    buyer, api, shipment, account, oldrow, actor, client = pending(world, monkeypatch)
    # Remove the unrelated fixture reservation before building the group.
    with domain_write():
        r = SupplyPaymentRequest.objects.get(pk=oldrow['id']); r.status='cancelled'; r.save(update_fields=['status'])
    shipment2 = _second_shipment(world, buyer, 'auto-batch')
    created = write(api, 'payment-batches/', {'payee_account_id': account['id'], 'reason': 'group', 'lines': [
        {'kind':'shipment', 'source_id':shipment.pk, 'amount':'0.25'},
        {'kind':'shipment', 'source_id':shipment2.pk, 'amount':'0.25'}]}, 'auto-batch').data['data']
    row = write(api, f"payment-batches/{created['id']}/submit/", {'expected_version':created['version']}, 'auto-submit').data['data']
    uploaded = client.post(f"{BASE}payment-batches/{row['id']}/vouchers/", {'expected_version': row['version'], 'file': _png()}, format='multipart', HTTP_IDEMPOTENCY_KEY='auto-upload')
    assert uploaded.status_code == 201, uploaded.data
    row = uploaded.data['data']
    if fail_second:
        from apps.supply_chain import costs
        original = costs.create_payment
        count = [0]
        def fail(*args, **kwargs):
            count[0] += 1
            if count[0] == 2: raise ValidationError('injected second line')
            return original(*args, **kwargs)
        monkeypatch.setattr(costs, 'create_payment', fail)
    response = approve(client, row)
    if fail_second:
        assert response.status_code == 400, response.data
        assert_pending(row)
        assert SupplyPaymentBatch.objects.get(pk=row['id']).status == 'submitted'
    else:
        assert response.status_code == 200, response.data
        assert PaymentRecord.objects.count() == PaymentVoucher.objects.count() == 2
        assert SupplyPaymentBatch.objects.get(pk=row['id']).status == 'paid'
        assert approve(client, row).status_code == 200
        assert PaymentRecord.objects.count() == 2


def test_reviewer_without_manage_cannot_approve_or_post(world, monkeypatch):
    buyer, api, shipment, account, row, actor, client = pending(world, monkeypatch)
    row = _upload(client, shipment, row).data['data']
    from apps.permissions.models import UserRole
    for binding in UserRole.objects.filter(user=actor):
        binding.role.permissions.remove(*binding.role.permissions.filter(code='supply.v2.manage'))
    response = approve(client, row)
    assert response.status_code == 403, response.data
    assert_pending(row)
    payment_request = SupplyPaymentRequest.objects.get(pk=row['id'])
    assert payment_request.status == 'submitted' and payment_request.payment_id is None
    assert payment_request.version == row['version']
