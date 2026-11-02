from tests.test_supply_payment_request_evidence import (
    _confirm, _setup_request, _upload, write, world,
)
from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.costs import payment_summary
from apps.workflows.models import PaymentApprovalFlow
import pytest
from rest_framework.test import APIClient


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


@pytest.mark.django_db
def test_designated_reviewer_blocks_other_reviewers(world, monkeypatch):
    from django.core.exceptions import ValidationError
    from apps.workflows.models import ApprovalRequest
    from tests.test_supply_payment_request_evidence import _grant
    from tests.test_supply_chain_v2_foundation import internal_user
    buyer, api, shipment, account, row, approver, _reviewer_api = _setup_request(world, monkeypatch)
    alternate = internal_user(world, 'alternate-payment-reviewer', codes=('supply.v2.view',))
    _grant(alternate, 'workflow.approvals.review', 'workflow.approvals.view', 'finance.reconcile')
    reviewer_api = APIClient(); reviewer_api.force_authenticate(user=alternate)
    base = f'costs/shipment/{shipment.pk}/payment-requests/'
    created = write(api, base, {'amount': '1', 'payee_account_id': account['id'], 'reason': 'assigned review'}, 'assigned-review-create')
    request_row = created.data['data']
    submitted = write(api, base+f"{request_row['id']}/submit/", {'expected_version': request_row['version']}, 'assigned-review-submit')
    approval = ApprovalRequest.objects.get(pk=submitted.data['data']['approval_id'])
    assert approval.designated_reviewer_id == approver.pk
    assert approval.workflow_snapshot['version'] == 1
    from apps.workflows.serializers import ApprovalRequestSerializer
    from types import SimpleNamespace
    approval_view = ApprovalRequestSerializer(approval, context={'request': SimpleNamespace(user=buyer)}).data
    assert approval_view['business_type_label'] == '供应商货款申请'
    assert approval_view['business_reference'] == shipment.number
    assert approval_view['payment_display']['nature'] == '对公'
    assert approval_view['payment_display']['payment_object'] == '供应商'
    assert approval_view['payment_display']['account_tail'] == '1111'
    assert approval_view['payment_display']['reason'] == 'assigned review'
    assert approval_view['requested_by_name'] == (buyer.full_name or '姓名未维护')
    assert approval_view['designated_reviewer_name'] == (approver.full_name or '姓名未维护')
    assert approval_view['audit_events'][0]['action'] == '提交'
    assert approval_view['created_at'].endswith('+08:00')
    assert approval_view['audit_events'][0]['created_at'].endswith('+08:00')
    approval.designated_reviewer = approver
    approval.save(update_fields=['designated_reviewer'])

    denied = reviewer_api.post(f'/api/internal/workflow/approvals/{approval.pk}/reject/', {'note': 'wrong reviewer'}, format='json')
    assert denied.status_code == 403, denied.data
    approval.refresh_from_db()
    assert approval.status == ApprovalRequest.Status.PENDING
    flow = PaymentApprovalFlow.objects.get(pk=approval.workflow_snapshot['rule_id'])
    flow.minimum_amount = '0.5000'
    with pytest.raises(ValidationError):
        flow.save()


@pytest.mark.django_db
def test_ambiguous_payment_flow_match_rejects_submission(world, monkeypatch):
    buyer, api, shipment, account, _row, approver, _reviewer_api = _setup_request(world, monkeypatch)
    from apps.accounts.models import InternalUserProfile
    department_id = InternalUserProfile.objects.filter(user=buyer).values_list('department_id', flat=True).first()
    matching = PaymentApprovalFlow.objects.filter(tenant=buyer.tenant, payment_kind='shipment', nature='corporate',
        department_key=str(department_id or ''), published=True, active=True)
    matching.update(active=False)
    base = f'costs/shipment/{shipment.pk}/payment-requests/'
    missing = write(api, base, {'amount': '1', 'payee_account_id': account['id'], 'reason': 'missing flow'}, 'missing-flow-create')
    no_match = write(api, base+f"{missing.data['data']['id']}/submit/", {'expected_version': missing.data['data']['version']}, 'missing-flow-submit')
    assert no_match.status_code == 400, no_match.data
    PaymentApprovalFlow.objects.filter(tenant=buyer.tenant, payment_kind='shipment', nature='corporate',
        department_key=str(department_id or ''), published=True).update(active=True)
    PaymentApprovalFlow.objects.create(tenant=buyer.tenant, flow_key='duplicate-shipment-rule', version=1,
        payment_kind='shipment', nature='corporate', department_key=str(department_id or ''),
        minimum_amount='0', maximum_amount=None, reviewer=approver, published=True)
    created = write(api, base, {'amount': '1', 'payee_account_id': account['id'], 'reason': 'ambiguous flow'}, 'ambiguous-flow-create')
    result = write(api, base+f"{created.data['data']['id']}/submit/", {'expected_version': created.data['data']['version']}, 'ambiguous-flow-submit')
    assert result.status_code == 400, result.data


@pytest.mark.django_db
def test_flow_with_unqualified_reviewer_rejects_submission(world, monkeypatch):
    from tests.test_supply_chain_v2_foundation import internal_user
    buyer, api, shipment, account, _row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    unqualified = internal_user(world, 'unqualified-payment-reviewer')
    from apps.accounts.models import InternalUserProfile
    from apps.workflows.models import PaymentApprovalFlow
    department_id = InternalUserProfile.objects.filter(user=buyer).values_list('department_id', flat=True).first()
    PaymentApprovalFlow.objects.filter(tenant=buyer.tenant, payment_kind='shipment', nature='corporate').update(active=False)
    PaymentApprovalFlow.objects.create(tenant=buyer.tenant, flow_key='unqualified-reviewer', version=1,
        payment_kind='shipment', nature='corporate', department_key=str(department_id or ''),
        minimum_amount='0', maximum_amount=None, reviewer=unqualified, published=True)
    base = f'costs/shipment/{shipment.pk}/payment-requests/'
    created = write(api, base, {'amount': '1', 'payee_account_id': account['id'], 'reason': 'unqualified reviewer'}, 'unqualified-create')
    result = write(api, base+f"{created.data['data']['id']}/submit/", {'expected_version': created.data['data']['version']}, 'unqualified-submit')
    assert result.status_code == 400, result.data
    from apps.supply_chain.payment_request_models import SupplyPaymentRequest
    draft = SupplyPaymentRequest.objects.get(pk=created.data['data']['id'])
    assert draft.status == 'draft' and draft.approval_id is None


@pytest.mark.django_db
def test_payment_flow_api_creates_and_publishes_a_version(world, monkeypatch):
    from apps.tenants.models import Department
    from tests.test_supply_payment_request_evidence import _grant
    from apps.workflows.models import PaymentApprovalFlow
    buyer, api, _shipment, _account, _row, approver, _reviewer_api = _setup_request(world, monkeypatch)
    _grant(buyer, 'workflow.approvals.manage')
    dept = Department.objects.create(tenant=buyer.tenant, name='流程测试部门')
    options = api.get('/api/internal/workflow/payment-flow-departments/')
    assert options.status_code == 200
    assert {'id': dept.pk, 'name': dept.name} in options.data['data']
    created = api.post('/api/internal/workflow/payment-flows/', {
        'flow_key': 'api-created-payment-flow', 'payment_kind': 'shipment', 'nature': 'corporate',
        'department_key': str(dept.pk), 'minimum_amount': '0',
        'maximum_amount': '0', 'reviewer_id': approver.pk,
    }, format='json')
    assert created.status_code == 201, created.data
    flow_id = created.data['data']['id']
    draft = PaymentApprovalFlow.objects.get(pk=flow_id)
    assert draft.version == 1 and not draft.published and draft.maximum_amount == 0
    published = api.post(f'/api/internal/workflow/payment-flows/{flow_id}/publish/', {}, format='json')
    assert published.status_code == 200 and published.data['data']['active']
    draft.refresh_from_db()
    assert draft.published and draft.active
    second = api.post('/api/internal/workflow/payment-flows/', {
        'flow_key': 'api-created-payment-flow', 'payment_kind': 'shipment', 'nature': 'corporate',
        'department_key': str(dept.pk), 'minimum_amount': '0',
        'maximum_amount': None, 'reviewer_id': approver.pk,
    }, format='json')
    assert second.status_code == 201 and second.data['data']['version'] == 2
    second_id = second.data['data']['id']
    published_second = api.post(f'/api/internal/workflow/payment-flows/{second_id}/publish/', {}, format='json')
    assert published_second.status_code == 200
    draft.refresh_from_db()
    assert draft.published and not draft.active


@pytest.mark.django_db
def test_blank_department_flow_is_global(world, monkeypatch):
    from apps.tenants.models import Department
    from apps.accounts.models import InternalUserProfile
    buyer, api, shipment, account, _row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    dept = Department.objects.create(tenant=buyer.tenant, name='部门专属员工')
    profile, _ = InternalUserProfile.objects.get_or_create(user=buyer, defaults={'tenant': buyer.tenant})
    profile.department = dept
    profile.save(update_fields=['department'])
    base = f'costs/shipment/{shipment.pk}/payment-requests/'
    created = write(api, base, {'amount': '1', 'payee_account_id': account['id'], 'reason': 'global department rule'}, 'global-department-create')
    submitted = write(api, base+f"{created.data['data']['id']}/submit/", {'expected_version': created.data['data']['version']}, 'global-department-submit')
    assert submitted.status_code == 200, submitted.data
