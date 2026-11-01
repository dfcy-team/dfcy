from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.permissions.models import Permission, UserRole, DataScope
from apps.supply_chain.payment_request_models import SupplyPaymentRequest, SupplyPaymentRequestVoucher
from apps.supply_chain.payment_voucher_models import PaymentVoucher
from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.models import PaymentApplication
from apps.supply_chain.models import PayeeAccount, domain_write
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import BASE, write

pytestmark = pytest.mark.django_db


def _grant(user, *codes):
    binding = UserRole.objects.filter(user=user).select_related('role').first()
    role = binding.role
    for code in codes:
        permission, _ = Permission.objects.get_or_create(code=code, defaults={
            'name': code, 'module': code.split('.')[0], 'action': code.rsplit('.', 1)[-1]})
        role.permissions.add(permission)
    return role


def _png():
    from PIL import Image
    data = BytesIO()
    Image.new('RGB', (2, 2), 'white').save(data, format='PNG')
    return SimpleUploadedFile('transfer.png', data.getvalue(), content_type='image/png')


def _setup_request(world, monkeypatch, *, requester_codes=('workflow.approvals.submit', 'finance.reconcile'), request_amount='1.0000'):
    from apps.integrations import feishu_delivery
    monkeypatch.setattr(feishu_delivery, 'notify_approval', lambda approval_id: {'status': 'queued', 'operation_ids': []})
    buyer, api, shipment = pilot(world)
    if request_amount is None:
        from apps.supply_chain import costs
        request_amount = costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']['remaining_amount']
    _grant(buyer, *requester_codes)
    account_result = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '测试收款户', 'account_holder': '供应商',
        'bank_name': '测试银行', 'account_number': '6222000000001111', 'active': True}, 'evidence-account')
    assert account_result.status_code == 201, account_result.data
    account = account_result.data['data']['account']
    path = f'costs/shipment/{shipment.pk}/payment-requests/'
    created = write(api, path, {'amount': request_amount, 'payee_account_id': account['id'], 'reason': '测试转账'}, 'evidence-create')
    assert created.status_code == 201, created.data
    row = created.data['data']
    submitted = write(api, f'costs/shipment/{shipment.pk}/payment-requests/{row["id"]}/submit/',
                      {'expected_version': row['version']}, 'evidence-submit')
    assert submitted.status_code == 200, submitted.data
    approver = internal_user(world, 'evidence-approver', codes=('supply.v2.view', 'supply.v2.manage'))
    _grant(approver, 'workflow.approvals.review', 'workflow.approvals.view', 'finance.reconcile')
    approval_id = submitted.data['data']['approval_id']
    reviewer_api = APIClient(); reviewer_api.force_authenticate(user=approver)
    approved = reviewer_api.post(f'/api/internal/workflow/approvals/{approval_id}/approve/', {'note': '通过'}, format='json')
    assert approved.status_code == 200, approved.data
    return buyer, api, shipment, account, submitted.data['data'], approver, reviewer_api


def _upload(api, shipment, request_row, key='evidence-voucher'):
    return api.post(f'{BASE}costs/shipment/{shipment.pk}/payment-requests/{request_row["id"]}/vouchers/',
                    {'file': _png()}, format='multipart', HTTP_IDEMPOTENCY_KEY=key)


def _confirm(api, shipment, request_row, *, reference='BANK-REF-1', key='evidence-confirm'):
    return api.post(f'{BASE}costs/shipment/{shipment.pk}/payment-requests/{request_row["id"]}/confirm/', {
        'expected_version': request_row['version'], 'date': '2026-10-14', 'reference_number': reference,
        'notes': '转账已完成'}, format='json', HTTP_IDEMPOTENCY_KEY=key)


def test_approval_does_not_post_payment_then_voucher_and_confirm_are_exactly_once(world, monkeypatch):
    buyer, api, shipment, _account, row, _approver, _reviewer_api = _setup_request(
        world, monkeypatch, request_amount=None)
    assert PaymentRecord.objects.count() == 0
    no_voucher = _confirm(api, shipment, row)
    assert no_voucher.status_code == 400, no_voucher.data  # no transfer evidence yet
    upload = _upload(api, shipment, row)
    assert upload.status_code == 201, upload.data
    row = upload.data['data']
    first = _confirm(api, shipment, row)
    assert first.status_code == 200, first.data
    payment_id = first.data['data']['payment_id']
    assert payment_id and PaymentRecord.objects.count() == 1
    assert PaymentVoucher.objects.filter(payment_id=payment_id).count() == 1
    assert SupplyPaymentRequestVoucher.objects.filter(request_id=row['id']).count() == 1
    replay = _confirm(api, shipment, row, key='confirm-retry')
    assert replay.status_code == 200 and replay.data['data']['payment_id'] == payment_id
    assert PaymentRecord.objects.count() == 1 and PaymentVoucher.objects.filter(payment_id=payment_id).count() == 1
    conflict = _confirm(api, shipment, row, reference='OTHER-REF', key='confirm-other-payload')
    assert conflict.status_code == 409


def test_direct_payment_respects_submitted_reservation_and_cancel_releases_it(world, monkeypatch):
    from apps.supply_chain import costs
    _buyer, api, shipment, account, row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    state = costs.payment_summary(_buyer, 'shipment', shipment.pk)
    amount = state['summary']['remaining_amount']
    url = f'{BASE}costs/shipment/{shipment.pk}/payments/'
    payload = {'amount': amount, 'payee_account_id': account['id'], 'date': '2026-10-14',
               'expected_version': state['version'], 'reference_number': 'DIRECT-RESERVED'}
    blocked = api.post(url, payload, format='json', HTTP_IDEMPOTENCY_KEY='direct-reserved')
    assert blocked.status_code == 422, blocked.data
    assert '申请' in str(blocked.data)
    assert PaymentRecord.objects.count() == 0
    cancelled = write(api, f'costs/shipment/{shipment.pk}/payment-requests/{row["id"]}/cancel/',
                      {'expected_version': row['version'], 'reason': '释放预占'}, 'release-reservation')
    assert cancelled.status_code == 200, cancelled.data
    state = costs.payment_summary(_buyer, 'shipment', shipment.pk)
    payload['expected_version'] = state['version']
    allowed = api.post(url, payload, format='json', HTTP_IDEMPOTENCY_KEY='direct-after-release')
    assert allowed.status_code == 201, allowed.data
    assert PaymentRecord.objects.count() == 1


def test_prepayment_application_respects_submitted_reservation_and_cancel_releases_it(world, monkeypatch):
    from apps.supply_chain import costs
    buyer, api, shipment, _account, row, _approver, _reviewer_api = _setup_request(
        world, monkeypatch, request_amount=None)
    order_account = write(api, f'costs/purchase/{shipment.order_id}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '定金账户', 'account_holder': '供应商',
        'bank_name': '测试银行', 'account_number': '6222000000002222', 'active': True}, 'deposit-account')
    assert order_account.status_code == 201, order_account.data
    deposit = write(api, f'costs/purchase/{shipment.order_id}/payments/', {
        'amount': '1.0000', 'payee_account_id': order_account.data['data']['account']['id'],
        'date': '2026-10-14', 'expected_version': 0}, 'deposit-payment')
    assert deposit.status_code == 201, deposit.data
    payment_id = deposit.data['data']['entries'][0]['id']
    apply_url = f'{BASE}costs/shipment/{shipment.pk}/prepayment-applications/'
    application = {'payment_id': payment_id, 'amount': '1.0000', 'date': '2026-10-14', 'expected_version': 0}
    blocked = api.post(apply_url, application, format='json', HTTP_IDEMPOTENCY_KEY='deposit-reserved')
    assert blocked.status_code == 422, blocked.data
    assert '申请' in str(blocked.data)
    assert PaymentRecord.objects.filter(shipment=shipment).count() == 0
    assert PaymentApplication.objects.filter(shipment=shipment).count() == 0
    before_release = costs.payment_summary(buyer, 'shipment', shipment.pk)
    assert before_release['available_prepayments'][0]['available_amount'] == '1.0000'
    cancelled = write(api, f'costs/shipment/{shipment.pk}/payment-requests/{row["id"]}/cancel/',
                      {'expected_version': row['version'], 'reason': '释放预占'}, 'deposit-release-reservation')
    assert cancelled.status_code == 200, cancelled.data
    state = costs.payment_summary(buyer, 'shipment', shipment.pk)
    application['expected_version'] = state['version']
    allowed = api.post(apply_url, application, format='json', HTTP_IDEMPOTENCY_KEY='deposit-after-release')
    assert allowed.status_code == 201, allowed.data
    assert PaymentRecord.objects.filter(shipment=shipment).count() == 0
    assert PaymentApplication.objects.filter(shipment=shipment).count() == 1
    assert allowed.data['data']['summary']['applied_amount'] == '1.0000'


def test_prepayment_application_can_use_balance_after_submitted_request_reservation(world, monkeypatch):
    from apps.supply_chain import costs
    buyer, api, shipment, _account, row, _approver, _reviewer_api = _setup_request(
        world, monkeypatch, request_amount='0.5000')
    apply_amount = Decimal(costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']['remaining_amount']) - Decimal('0.5000')
    order_account = write(api, f'costs/purchase/{shipment.order_id}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '剩余额度定金户', 'account_holder': '供应商',
        'bank_name': '测试银行', 'account_number': '6222000000004444', 'active': True,
    }, 'deposit-free-balance-account')
    assert order_account.status_code == 201, order_account.data
    deposit = write(api, f'costs/purchase/{shipment.order_id}/payments/', {
        'amount': str(apply_amount), 'payee_account_id': order_account.data['data']['account']['id'],
        'date': '2026-10-14', 'expected_version': 0,
    }, 'deposit-free-balance-payment')
    assert deposit.status_code == 201, deposit.data
    payment_id = deposit.data['data']['entries'][0]['id']
    before = costs.payment_summary(buyer, 'shipment', shipment.pk)
    assert before['available_prepayments'][0]['available_amount'] == str(apply_amount)

    applied = api.post(f'{BASE}costs/shipment/{shipment.pk}/prepayment-applications/', {
        'payment_id': payment_id, 'amount': str(apply_amount), 'date': '2026-10-14',
        'expected_version': before['version'],
    }, format='json', HTTP_IDEMPOTENCY_KEY='deposit-free-balance-apply')
    assert applied.status_code == 201, applied.data
    after = costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']
    assert Decimal(after['applied_amount']) == apply_amount
    assert PaymentApplication.objects.filter(shipment=shipment).count() == 1

    voucher = _upload(api, shipment, row, key='deposit-free-balance-request-voucher')
    assert voucher.status_code == 201, voucher.data
    confirmed = _confirm(api, shipment, voucher.data['data'], reference='DEPOSIT-AND-REQUEST',
                         key='deposit-free-balance-request-confirm')
    assert confirmed.status_code == 200, confirmed.data
    final = costs.payment_summary(buyer, 'shipment', shipment.pk)['summary']
    assert Decimal(final['paid_amount']) + Decimal(final['applied_amount']) == Decimal(final['due_amount'])


def test_confirm_requires_finance_permission_and_unchanged_account_snapshot(world, monkeypatch):
    buyer, api, shipment, account, row, _approver, _reviewer_api = _setup_request(
        world, monkeypatch, requester_codes=('workflow.approvals.submit',))
    upload = _upload(api, shipment, row)
    assert upload.status_code == 201, upload.data
    row = upload.data['data']
    denied = _confirm(api, shipment, row)
    assert denied.status_code == 403
    # Grant reconcile permission so snapshot validation is the rejecting guard.
    _grant(buyer, 'finance.reconcile')
    with domain_write():
        changed_account = PayeeAccount.objects.get(pk=account['id'])
        changed_account.account_number = '6222000000009999'
        changed_account.save(update_fields=['account_number'])
    changed = _confirm(api, shipment, row, key='snapshot-confirm')
    assert changed.status_code == 400, changed.data
    assert PaymentRecord.objects.count() == 0


def test_cancelled_approved_request_cannot_upload_or_confirm(world, monkeypatch):
    _buyer, api, shipment, _account, row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    cancelled = write(api, f'costs/shipment/{shipment.pk}/payment-requests/{row["id"]}/cancel/',
                      {'expected_version': row['version'], 'reason': '不再付款'}, 'cancel-approved')
    assert cancelled.status_code == 200, cancelled.data
    denied_upload = _upload(api, shipment, cancelled.data['data'])
    assert denied_upload.status_code == 400, denied_upload.data
    result = _confirm(api, shipment, cancelled.data['data'], key='cancelled-confirm')
    assert result.status_code == 400, result.data
    assert PaymentRecord.objects.count() == 0


def test_upload_requires_approved_request(world, monkeypatch):
    from apps.integrations import feishu_delivery
    monkeypatch.setattr(feishu_delivery, 'notify_approval', lambda approval_id: {'status': 'queued', 'operation_ids': []})
    buyer, api, shipment = pilot(world)
    _grant(buyer, 'workflow.approvals.submit', 'finance.reconcile')
    account = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '户', 'account_holder': '供应商', 'bank_name': '银行',
        'account_number': '6222000000001111', 'active': True}, 'pending-account').data['data']['account']
    created = write(api, f'costs/shipment/{shipment.pk}/payment-requests/', {
        'amount': '1.0000', 'payee_account_id': account['id'], 'reason': 'pending'}, 'pending-create').data['data']
    submitted = write(api, f'costs/shipment/{shipment.pk}/payment-requests/{created["id"]}/submit/',
                      {'expected_version': created['version']}, 'pending-submit').data['data']
    denied_upload = _upload(api, shipment, submitted)
    assert denied_upload.status_code == 400, denied_upload.data


def test_payment_approval_list_and_detail_require_source_scope(world, monkeypatch):
    _buyer, api, shipment, account, row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    # Advance request ids independently from the source id: approval.business_id stores request id.
    second = write(api, f'costs/shipment/{shipment.pk}/payment-requests/', {
        'amount': '1.0000', 'payee_account_id': account['id'], 'reason': '第二申请'}, 'scope-second').data['data']
    assert second['id'] != shipment.pk
    second_submitted = write(api, f'costs/shipment/{shipment.pk}/payment-requests/{second["id"]}/submit/',
                             {'expected_version': second['version']}, 'scope-second-submit')
    assert second_submitted.status_code == 200, second_submitted.data
    approval_id = second_submitted.data['data']['approval_id']

    allowed = internal_user(world, 'scope-allowed', scope=DataScope.ScopeType.CUSTOM,
                            config={'approval_types': ['finance'], 'supplier_ids': [world['supplier'].pk]},
                            codes=('supply.v2.view',))
    _grant(allowed, 'workflow.approvals.view')
    allowed_client = APIClient(); allowed_client.force_authenticate(user=allowed)
    listing = allowed_client.get('/api/internal/workflow/approvals/?page_size=100')
    assert listing.status_code == 200, listing.data
    assert approval_id in [x['id'] for x in listing.data['data']['results']]
    detail = allowed_client.get(f'/api/internal/workflow/approvals/{approval_id}/')
    assert detail.status_code == 200 and detail.data['data']['business_link'].endswith(
        f'kind=shipment&id={shipment.pk}&payment_request_id={second["id"]}')

    denied = internal_user(world, 'scope-denied', scope=DataScope.ScopeType.CUSTOM,
                           config={'approval_types': ['finance'], 'supplier_ids': [world['supplier_b'].pk]},
                           codes=('supply.v2.view',))
    _grant(denied, 'workflow.approvals.view')
    denied_client = APIClient(); denied_client.force_authenticate(user=denied)
    denied_list = denied_client.get('/api/internal/workflow/approvals/?page_size=100')
    assert denied_list.status_code == 200 and approval_id not in [x['id'] for x in denied_list.data['data']['results']]
    assert denied_client.get(f'/api/internal/workflow/approvals/{approval_id}/').status_code == 404


def test_only_request_creator_can_submit_request(world, monkeypatch):
    buyer, api, shipment, account, row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    draft = write(api, f'costs/shipment/{shipment.pk}/payment-requests/', {
        'amount': '1.0000', 'payee_account_id': account['id'], 'reason': '他人不得提交'}, 'creator-only-draft').data['data']
    other = internal_user(world, 'not-request-creator', codes=('supply.v2.view', 'supply.v2.manage'))
    _grant(other, 'workflow.approvals.submit')
    other_client = APIClient(); other_client.force_authenticate(user=other)
    response = other_client.post(f'{BASE}costs/shipment/{shipment.pk}/payment-requests/{draft["id"]}/submit/',
                                 {'expected_version': draft['version']}, format='json',
                                 HTTP_IDEMPOTENCY_KEY='non-creator-submit')
    assert response.status_code == 403
    assert SupplyPaymentRequest.objects.get(pk=draft['id']).approval_id is None


def test_feishu_reviewer_eligibility_tracks_source_view_scope(world, monkeypatch):
    from apps.integrations.feishu_delivery import reviewer_allowed
    _buyer, _api, _shipment, _account, row, approver, _reviewer_api = _setup_request(world, monkeypatch)
    from apps.workflows.models import ApprovalRequest
    approval = ApprovalRequest.objects.get(pk=row['approval_id'])
    scope = DataScope.objects.get(role__user_roles__user=approver)
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = {'approval_types': ['finance'], 'supplier_ids': [world['supplier_b'].pk]}
    scope.save(update_fields=['scope_type', 'config'])
    assert reviewer_allowed(approver, approval) is False
    scope.config = {'approval_types': ['finance'], 'supplier_ids': [world['supplier'].pk]}
    scope.save(update_fields=['config'])
    assert reviewer_allowed(approver, approval) is True
    scope.config = {'approval_types': ['finance'], 'supplier_ids': [world['supplier_b'].pk]}
    scope.save(update_fields=['config'])
    assert reviewer_allowed(approver, approval) is False
