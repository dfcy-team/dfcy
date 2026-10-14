from decimal import Decimal
from unittest.mock import patch

import pytest
from apps.finance.models import FinanceAuditLog, PlatformStatement, ReconciliationException, ReconciliationMatch, WithdrawalRecord, BankReceiptImport
from apps.finance.services import confirm_match, reject_match, resolve_exception
from apps.tenants.models import Tenant
from tests.test_finance_remediation import finance_rows, user_with_scopes, all_scopes

pytestmark=pytest.mark.django_db


def setup_match(status='suggested'):
    tenant=Tenant.objects.create(name='Review invariants',code='review-invariants')
    user,client=user_with_scopes(tenant,'review-invariants',all_scopes())
    statement,withdrawal,receipt=finance_rows(tenant)
    match=ReconciliationMatch.objects.create(tenant=tenant,statement=statement,withdrawal=withdrawal,bank_receipt=receipt,matched_amount='975',difference_amount='0',status=status)
    return user,client,match


@pytest.mark.parametrize('change',['matched_amount','receipt_amount','capacity','withdrawal_status'])
def test_confirmation_revalidates_legacy_source_amounts_and_capacity(change):
    user,client,match=setup_match()
    if change=='matched_amount':match.matched_amount=Decimal('1000');match.save()
    if change=='receipt_amount':match.bank_receipt.receipt_amount=Decimal('1000');match.bank_receipt.save()
    if change=='capacity':match.statement.net_amount=Decimal('500');match.statement.save()
    if change=='withdrawal_status':match.withdrawal.status='cancelled';match.withdrawal.save()
    response=client.post(f'/api/finance/reconciliation/matches/{match.pk}/confirm/',{},format='json')
    assert response.status_code==400
    match.refresh_from_db();match.statement.refresh_from_db();match.bank_receipt.refresh_from_db()
    assert match.status=='suggested' and match.statement.status=='imported' and match.bank_receipt.status=='imported'
    assert FinanceAuditLog.objects.count()==0


def test_confirmation_refuses_duplicate_legacy_source_claim():
    user,client,match=setup_match()
    ReconciliationMatch.objects.create(tenant=user.tenant,statement=match.statement,withdrawal=match.withdrawal,bank_receipt=match.bank_receipt,matched_amount='975',difference_amount='0')
    assert client.post(f'/api/finance/reconciliation/matches/{match.pk}/confirm/',{},format='json').status_code==400
    match.refresh_from_db();assert match.status=='suggested'


def test_exception_resolution_revalidates_withdrawal_currency():
    user,client,match=setup_match('rejected')
    match.withdrawal.currency='EUR';match.withdrawal.save()
    exception=ReconciliationException.objects.create(tenant=user.tenant,reconciliation_match=match,exception_type='amount_difference',difference_amount='5')
    response=client.post(f'/api/finance/reconciliation/exceptions/{exception.pk}/resolve/',{'reason':'corrected'},format='json')
    assert response.status_code==400
    exception.refresh_from_db();assert exception.status=='open' and not exception.resolution_note
    assert FinanceAuditLog.objects.count()==0


@pytest.mark.parametrize('action',['confirm','reject','resolve'])
def test_review_audit_failure_rolls_back_all_state_changes(action):
    user,client,match=setup_match('rejected' if action=='resolve' else 'suggested')
    exception=ReconciliationException.objects.create(tenant=user.tenant,reconciliation_match=match,exception_type='amount_difference',difference_amount='5')
    with patch('apps.finance.services.write_finance_audit_log',side_effect=RuntimeError('audit unavailable')):
        with pytest.raises(RuntimeError):
            if action=='confirm':confirm_match(match,user)
            elif action=='reject':reject_match(match,user,'wrong reference')
            else:resolve_exception(exception,user,'corrected')
    match.refresh_from_db();match.statement.refresh_from_db();match.bank_receipt.refresh_from_db();exception.refresh_from_db()
    assert match.status==('rejected' if action=='resolve' else 'suggested')
    assert match.statement.status=='imported' and match.bank_receipt.status=='imported'
    assert exception.status=='open' and FinanceAuditLog.objects.count()==0
