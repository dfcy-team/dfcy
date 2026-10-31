from tests.test_supply_payment_request_evidence import (
    _confirm, _setup_request, _upload, write, world,
)
from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.costs import payment_summary
import pytest


@pytest.mark.django_db
def test_approved_payment_request_reversal_keeps_link_and_displays_reversed(world, monkeypatch):
    _buyer, api, shipment, _account, row, approver, reviewer_api = _setup_request(world, monkeypatch)
    uploaded = _upload(api, shipment, row)
    assert uploaded.status_code == 201, uploaded.data
    confirmed = _confirm(api, shipment, uploaded.data['data'])
    assert confirmed.status_code == 200, confirmed.data
    payment_id = confirmed.data['data']['payment_id']
    payment = PaymentRecord.objects.get(pk=payment_id)

    reversed_result = api.post(
        f'/api/internal/supply-chain/v2/costs/shipment/{shipment.pk}/payments/{payment_id}/reverse/',
        {'reason': '测试冲销', 'expected_version': payment_summary(_buyer, 'shipment', shipment.pk)['version']}, format='json', HTTP_IDEMPOTENCY_KEY='request-flow-reverse',
    )
    assert reversed_result.status_code == 200, reversed_result.data

    listed = api.get(
        f'/api/internal/supply-chain/v2/costs/shipment/{shipment.pk}/payment-requests/?request_id={row["id"]}'
    )
    assert listed.status_code == 200, listed.data
    result = listed.data['data'][0]
    assert result['status'] == 'reversed'
    assert result['payment_id'] == payment_id
    assert result['can_confirm'] is False
    notified=write(api, f'costs/shipment/{shipment.pk}/payment-requests/{row["id"]}/notify/', {'expected_version':result['version']}, 'reversed-notify')
    assert notified.status_code==400, notified.data
    assert PaymentRecord.objects.filter(pk=payment_id).exists()
    assert payment.reversal.exists()


@pytest.mark.django_db
def test_requester_cannot_approve_own_payment_even_with_review_permission(world, monkeypatch):
    from tests.test_supply_payment_request_evidence import _grant
    buyer, api, shipment, account, row, approver, reviewer_api = _setup_request(world, monkeypatch)
    _grant(buyer, 'workflow.approvals.review', 'workflow.approvals.view')
    base = f'costs/shipment/{shipment.pk}/payment-requests/'
    created = write(api, base, {'amount': '1', 'payee_account_id': account['id'], 'reason': 'another'}, 'own-review-create')
    request_row = created.data['data']
    submitted = write(api, base+f"{request_row['id']}/submit/", {'expected_version': request_row['version']}, 'own-review-submit')
    approval_id = submitted.data['data']['approval_id']
    denied = api.post(f'/api/internal/workflow/approvals/{approval_id}/approve/', {'note': 'self'}, format='json')
    assert denied.status_code == 422, denied.data
    assert 'requester cannot review' in denied.data['message']
