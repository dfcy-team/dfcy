import pytest

from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.supply_chain.cost_models import PaymentRecord
from apps.supply_chain.cost_models import PaymentCurrencyConfirmation
from apps.supply_chain.payment_request_models import SupplyPaymentBatch, SupplyPaymentRequest
from apps.supply_chain.models import domain_write
from rest_framework.test import APIClient
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_v2_foundation import world, internal_user
from tests.test_supply_chain_v2_logistics import BASE, write
from tests.test_supply_monthly_nature_balances import split
from tests.test_supply_payment_batch import _second_shipment, _legacy_approve
from tests.test_supply_payment_request_evidence import _png, _setup_request, _upload
from apps.workflows.models import ApprovalRequest

pytestmark = pytest.mark.django_db


def _finance_scope(user, currencies):
    role, _ = Role.objects.get_or_create(tenant=user.tenant, code=f'currency-scope-{user.pk}',
        defaults={'name': 'Currency scope'})
    permission, _ = Permission.objects.get_or_create(code='finance.reconcile', defaults={
        'name': 'Finance reconcile', 'module': 'finance', 'action': 'reconcile'})
    role.permissions.add(permission)
    UserRole.objects.get_or_create(tenant=user.tenant, user=user, role=role)
    scope, created = DataScope.objects.get_or_create(tenant=user.tenant, role=role,
        defaults={'scope_type': DataScope.ScopeType.ALL, 'config': {}})
    scope.scope_type = DataScope.ScopeType.ALL if currencies is None else DataScope.ScopeType.CUSTOM
    scope.config = {} if currencies is None else {'currencies': currencies}
    scope.save(update_fields=['scope_type', 'config'])


def _world_with_account(world, *, currency='USD'):
    actor, api, shipment = pilot(world)
    world['tenant'].payment_approval_required = False
    world['tenant'].save(update_fields=['payment_approval_required'])
    if currency:
        split(world, actor, shipment, currency=currency)
    account = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', {
        'nature': 'corporate', 'account_name': '测试账户', 'account_holder': '供应商',
        'bank_name': '测试银行', 'account_number': '6222000000001111', 'active': True},
        'currency-scope-account').data['data']['account']
    return actor, api, shipment, account


@pytest.mark.parametrize('payload', [
    {'amount': '1', 'date': '2026-10-01'},
    {'amount': '1', 'date': '2026-10-01', 'currency': 'USD'},
])
def test_direct_payment_usd_source_denied_by_cny_only_scope(world, payload):
    actor, api, shipment, account = _world_with_account(world)
    state = api.get(BASE + f'costs/shipment/{shipment.pk}/payments/').data['data']
    _finance_scope(actor, ['CNY'])
    result = write(api, f'costs/shipment/{shipment.pk}/payments/', {
        **payload, 'payee_account_id': account['id'], 'expected_version': state['version']},
        'direct-currency-scope-denied')
    assert result.status_code == 403, result.data
    assert PaymentRecord.objects.count() == 0


def test_direct_payment_usd_scope_positive_and_explicit_conflict_rejected(world):
    actor, api, shipment, account = _world_with_account(world)
    _finance_scope(actor, ['USD'])
    state = api.get(BASE + f'costs/shipment/{shipment.pk}/payments/').data['data']
    result = write(api, f'costs/shipment/{shipment.pk}/payments/', {
        'amount': '1', 'date': '2026-10-01', 'payee_account_id': account['id'],
        'expected_version': state['version']}, 'direct-usd-scope-positive')
    assert result.status_code == 201, result.data
    assert PaymentRecord.objects.count() == 1
    conflicting = write(api, f'costs/shipment/{shipment.pk}/payments/', {
        'amount': '1', 'date': '2026-10-01', 'currency': 'CNY', 'payee_account_id': account['id'],
        'expected_version': result.data['data']['version']}, 'direct-usd-source-cny-conflict')
    assert conflicting.status_code in (400, 422)
    assert PaymentRecord.objects.count() == 1


def test_unknown_legacy_source_cannot_use_cny_scope_but_unrestricted_can(world):
    actor, api, shipment, account = _world_with_account(world, currency='')
    _finance_scope(actor, ['CNY'])
    state = api.get(BASE + f'costs/shipment/{shipment.pk}/payments/').data['data']
    body = {'amount': '1', 'date': '2026-10-01', 'currency': 'CNY', 'payee_account_id': account['id'],
            'expected_version': state['version']}
    denied = write(api, f'costs/shipment/{shipment.pk}/payments/', body, 'unknown-cny-scope-denied')
    assert denied.status_code == 403, denied.data
    assert PaymentRecord.objects.count() == 0
    _finance_scope(actor, None)
    allowed = write(api, f'costs/shipment/{shipment.pk}/payments/', body, 'unknown-unrestricted-positive')
    assert allowed.status_code == 201, allowed.data
    assert PaymentRecord.objects.count() == 1


def test_manual_batch_usd_source_denied_even_when_legacy_batch_currency_blank(world):
    actor, api, shipment, account = _world_with_account(world)
    _finance_scope(actor, None)
    second = _second_shipment(world, actor, 'currency-scope-second')
    split(world, actor, second, currency='USD')
    created = write(api, 'payment-batches/', {'payee_account_id': account['id'], 'reason': 'scope test',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': '0.25'},
                  {'kind': 'shipment', 'source_id': second.pk, 'amount': '0.25'}]},
        'batch-scope-create')
    assert created.status_code == 201, created.data
    batch = SupplyPaymentBatch.objects.get(pk=created.data['data']['id'])
    # Simulate a legacy draft persisted before currency inference was added.
    with domain_write():
        batch.currency = ''
        batch.save(update_fields=['currency'])
        for line in batch.lines.all():
            line.currency = ''
            line.save(update_fields=['currency'])
    uploaded = api.post(f'{BASE}payment-batches/{batch.pk}/vouchers/',
        {'expected_version': str(batch.version), 'file': _png()}, format='multipart',
        HTTP_IDEMPOTENCY_KEY='batch-scope-voucher')
    assert uploaded.status_code == 201, uploaded.data
    _finance_scope(actor, ['CNY'])
    denied = api.post(f'{BASE}payment-batches/{batch.pk}/manual_confirm/', {
        'expected_version': uploaded.data['data']['version'], 'date': '2026-10-01',
        'reference_number': 'BATCH-USD-DENIED', 'notes': ''}, format='json',
        HTTP_IDEMPOTENCY_KEY='batch-usd-scope-denied')
    assert denied.status_code == 403, denied.data
    assert PaymentRecord.objects.count() == 0
    batch.refresh_from_db()
    assert batch.currency == '' and not batch.lines.exclude(currency='').exists()
    _finance_scope(actor, ['USD'])
    actor = type(actor).objects.get(pk=actor.pk)
    api.force_authenticate(user=actor)
    allowed = api.post(f'{BASE}payment-batches/{batch.pk}/manual_confirm/', {
        'expected_version': uploaded.data['data']['version'], 'date': '2026-10-01',
        'reference_number': 'BATCH-USD-ALLOWED', 'notes': ''}, format='json',
        HTTP_IDEMPOTENCY_KEY='batch-usd-scope-allowed')
    assert allowed.status_code == 200, allowed.data
    batch.refresh_from_db()
    assert batch.currency == 'USD'
    assert not batch.lines.exclude(currency='USD').exists()
    assert PaymentRecord.objects.count() == 2
    assert all(p.account_snapshot.get('currency') == 'USD' for p in PaymentRecord.objects.all())


def test_approved_legacy_blank_currency_request_uses_current_source_for_authorization(world, monkeypatch):
    buyer, api, shipment, _account, row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    split(world, buyer, shipment, currency='USD')
    row_record = SupplyPaymentRequest.objects.get(pk=row['id'])
    with domain_write():
        row_record.currency = ''
        row_record.save(update_fields=['currency'])
    _legacy_approve(row['approval_id'])
    uploaded = _upload(api, shipment, row, key='legacy-blank-request-voucher')
    assert uploaded.status_code == 201, uploaded.data
    row = uploaded.data['data']

    actor = internal_user(world, 'legacy-blank-request-finance')
    _finance_scope(actor, ['CNY'])
    finance_api = APIClient(); finance_api.force_authenticate(user=actor)
    path = f'{BASE}costs/shipment/{shipment.pk}/payment-requests/{row["id"]}/confirm/'
    body = {'expected_version': row['version'], 'date': '2026-10-01',
            'reference_number': 'LEGACY-BLANK-CURRENCY', 'notes': ''}
    denied = finance_api.post(path, body, format='json', HTTP_IDEMPOTENCY_KEY='legacy-blank-confirm-cny')
    assert denied.status_code == 403, denied.data
    assert PaymentRecord.objects.count() == 0
    _finance_scope(actor, ['USD'])
    actor = type(actor).objects.get(pk=actor.pk)
    finance_api.force_authenticate(user=actor)
    allowed = finance_api.post(path, body, format='json', HTTP_IDEMPOTENCY_KEY='legacy-blank-confirm-usd')
    assert allowed.status_code == 200, allowed.data
    assert PaymentRecord.objects.count() == 1


def test_direct_omitted_currency_historical_idempotency_replay_keeps_request_hash(world):
    actor, api, shipment, account = _world_with_account(world)
    _finance_scope(actor, ['USD'])
    state = api.get(BASE + f'costs/shipment/{shipment.pk}/payments/').data['data']
    body = {'amount': '1', 'date': '2026-10-01', 'payee_account_id': account['id'],
            'expected_version': state['version']}
    first = write(api, f'costs/shipment/{shipment.pk}/payments/', body, 'legacy-omitted-currency-replay')
    assert first.status_code == 201, first.data
    replay = write(api, f'costs/shipment/{shipment.pk}/payments/', body, 'legacy-omitted-currency-replay')
    assert replay.status_code in (200, 201), replay.data
    assert PaymentRecord.objects.count() == 1


def test_legacy_blank_paid_batch_reverse_uses_persisted_payment_currency(world):
    actor, api, shipment, account = _world_with_account(world)
    _finance_scope(actor, None)
    second = _second_shipment(world, actor, 'legacy-blank-paid-batch')
    split(world, actor, second, currency='USD')
    created = write(api, 'payment-batches/', {'payee_account_id': account['id'], 'reason': 'reverse scope',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': '0.25'},
                  {'kind': 'shipment', 'source_id': second.pk, 'amount': '0.25'}]},
        'legacy-blank-paid-batch-create')
    assert created.status_code == 201, created.data
    batch = SupplyPaymentBatch.objects.get(pk=created.data['data']['id'])
    uploaded = api.post(f'{BASE}payment-batches/{batch.pk}/vouchers/',
        {'expected_version': str(batch.version), 'file': _png()}, format='multipart',
        HTTP_IDEMPOTENCY_KEY='legacy-blank-paid-batch-voucher')
    assert uploaded.status_code == 201, uploaded.data
    paid = api.post(f'{BASE}payment-batches/{batch.pk}/manual_confirm/', {
        'expected_version': uploaded.data['data']['version'], 'date': '2026-10-01',
        'reference_number': 'LEGACY-BATCH-PAID', 'notes': ''}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-blank-paid-batch-confirm')
    assert paid.status_code == 200, paid.data
    assert PaymentRecord.objects.count() == 2
    assert all(p.account_snapshot.get('currency') == 'USD' for p in PaymentRecord.objects.all())
    with domain_write():
        batch.currency = ''
        batch.save(update_fields=['currency'])

    _finance_scope(actor, ['CNY'])
    denied = api.post(f'{BASE}payment-batches/{batch.pk}/reverse/', {
        'expected_version': paid.data['data']['version'], 'reason': 'currency scope'}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-blank-batch-reverse-denied')
    assert denied.status_code == 403, denied.data
    assert PaymentRecord.objects.filter(reversal__isnull=False).count() == 0
    _finance_scope(actor, ['USD'])
    allowed = api.post(f'{BASE}payment-batches/{batch.pk}/reverse/', {
        'expected_version': paid.data['data']['version'], 'reason': 'currency scope'}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-blank-batch-reverse-usd')
    assert allowed.status_code == 200, allowed.data
    assert PaymentRecord.objects.filter(reversal__isnull=False).count() == 2


def test_explicit_currency_mixed_known_and_unknown_batch_rejected_without_writes(world):
    actor, api, shipment, account = _world_with_account(world)
    second = _second_shipment(world, actor, 'known-unknown-explicit-batch')
    # First shipment has a confirmed USD payable; second remains unclassified.
    created = write(api, 'payment-batches/', {'currency': 'USD', 'payee_account_id': account['id'],
        'reason': 'known plus unknown',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': '0.25'},
                  {'kind': 'shipment', 'source_id': second.pk, 'amount': '0.25'}]},
        'known-unknown-explicit-batch')
    assert created.status_code in (400, 422), created.data
    assert SupplyPaymentBatch.objects.count() == 0
    assert SupplyPaymentRequest.objects.count() == 0
    assert ApprovalRequest.objects.count() == 0
    assert PaymentRecord.objects.count() == 0


def test_legacy_mixed_currency_draft_rejected_before_approval_reservation_or_notify(world, monkeypatch):
    buyer, api, shipment, account, row, _approver, _reviewer_api = _setup_request(world, monkeypatch)
    cancelled = write(api, f'costs/shipment/{shipment.pk}/payment-requests/{row["id"]}/cancel/',
        {'expected_version': row['version'], 'reason': 'free source for legacy batch'}, 'legacy-mixed-cancel')
    assert cancelled.status_code == 200, cancelled.data
    second = _second_shipment(world, buyer, 'legacy-mixed-unknown')
    created = write(api, 'payment-batches/', {'payee_account_id': account['id'], 'reason': 'legacy mixed draft',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': '0.25'},
                  {'kind': 'shipment', 'source_id': second.pk, 'amount': '0.25'}]},
        'legacy-mixed-draft-create')
    assert created.status_code == 201, created.data
    batch = SupplyPaymentBatch.objects.get(pk=created.data['data']['id'])
    split(world, buyer, shipment, currency='USD')
    notifications = []
    from apps.integrations import feishu_delivery
    monkeypatch.setattr(feishu_delivery, 'notify_approval',
        lambda approval_id: notifications.append(approval_id) or {'status': 'queued', 'operation_ids': []})
    approvals_before = ApprovalRequest.objects.count()
    rejected = write(api, f'payment-batches/{batch.pk}/submit/',
        {'expected_version': batch.version}, 'legacy-mixed-draft-submit')
    assert rejected.status_code in (400, 422), rejected.data
    batch.refresh_from_db()
    assert batch.status == 'draft' and batch.approval_id is None
    assert not batch.lines.exclude(status='draft').exists()
    assert not SupplyPaymentRequest.objects.filter(batch=batch, status='submitted').exists()
    assert ApprovalRequest.objects.count() == approvals_before
    assert notifications == []
    assert PaymentRecord.objects.count() == 0


def test_legacy_paid_blank_snapshot_confirmation_cannot_expand_reverse_scope(world):
    actor, api, shipment, account = _world_with_account(world, currency='')
    _finance_scope(actor, None)
    second = _second_shipment(world, actor, 'legacy-confirmed-currency-batch')
    created = write(api, 'payment-batches/', {'payee_account_id': account['id'], 'reason': 'confirmed currency fallback',
        'lines': [{'kind': 'shipment', 'source_id': shipment.pk, 'amount': '0.25'},
                  {'kind': 'shipment', 'source_id': second.pk, 'amount': '0.25'}]},
        'legacy-confirmed-currency-batch-create')
    assert created.status_code == 201, created.data
    batch = SupplyPaymentBatch.objects.get(pk=created.data['data']['id'])
    uploaded = api.post(f'{BASE}payment-batches/{batch.pk}/vouchers/',
        {'expected_version': str(batch.version), 'file': _png()}, format='multipart',
        HTTP_IDEMPOTENCY_KEY='legacy-confirmed-currency-batch-voucher')
    assert uploaded.status_code == 201, uploaded.data
    paid = api.post(f'{BASE}payment-batches/{batch.pk}/manual_confirm/', {
        'expected_version': uploaded.data['data']['version'], 'date': '2026-10-01',
        'reference_number': 'LEGACY-CONFIRMED-BATCH', 'notes': ''}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-confirmed-currency-batch-confirm')
    assert paid.status_code == 200, paid.data
    payments = list(PaymentRecord.objects.order_by('pk'))
    assert len(payments) == 2 and all(not p.account_snapshot.get('currency') for p in payments)
    with domain_write():
        for payment in payments:
            PaymentCurrencyConfirmation.objects.create(tenant=world['tenant'], created_by=actor,
                payment=payment, currency='USD', reason='legacy source confirmation')
        batch.currency = ''
        batch.save(update_fields=['currency'])

    _finance_scope(actor, ['CNY'])
    denied = api.post(f'{BASE}payment-batches/{batch.pk}/reverse/', {
        'expected_version': paid.data['data']['version'], 'reason': 'confirmation scope'}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-confirmed-batch-reverse-cny')
    assert denied.status_code == 403, denied.data
    assert PaymentRecord.objects.filter(reversal__isnull=False).count() == 0
    with domain_write():
        for confirmation in PaymentCurrencyConfirmation.objects.filter(payment__in=payments):
            confirmation.currency = 'CNY'
            confirmation.save(update_fields=['currency'])
    # Even a tenant-owned confirmation cannot authorize a restricted scope.
    denied_after_confirmation_edit = api.post(f'{BASE}payment-batches/{batch.pk}/reverse/', {
        'expected_version': paid.data['data']['version'], 'reason': 'confirmation scope'}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-confirmed-batch-reverse-cny-after-edit')
    assert denied_after_confirmation_edit.status_code == 403, denied_after_confirmation_edit.data
    assert PaymentRecord.objects.filter(reversal__isnull=False).count() == 0
    _finance_scope(actor, ['USD'])
    actor = type(actor).objects.get(pk=actor.pk)
    api.force_authenticate(user=actor)
    denied_usd = api.post(f'{BASE}payment-batches/{batch.pk}/reverse/', {
        'expected_version': paid.data['data']['version'], 'reason': 'confirmation scope'}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-confirmed-batch-reverse-usd')
    assert denied_usd.status_code == 403, denied_usd.data
    assert PaymentRecord.objects.filter(reversal__isnull=False).count() == 0
    _finance_scope(actor, None)
    actor = type(actor).objects.get(pk=actor.pk)
    api.force_authenticate(user=actor)
    allowed = api.post(f'{BASE}payment-batches/{batch.pk}/reverse/', {
        'expected_version': paid.data['data']['version'], 'reason': 'confirmation scope'}, format='json',
        HTTP_IDEMPOTENCY_KEY='legacy-confirmed-batch-reverse-all')
    assert allowed.status_code == 200, allowed.data
    assert PaymentRecord.objects.filter(reversal__isnull=False).count() == 2
