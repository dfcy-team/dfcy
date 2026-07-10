from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    BankReceiptImport,
    FinanceAuditLog,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)


def write_finance_audit_log(tenant, actor, action, obj, detail=None):
    return FinanceAuditLog.objects.create(
        tenant=tenant,
        actor=actor,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(obj.id),
        masked_detail=detail or {},
    )


def mask_account(account_hint="demo-account"):
    suffix = str(account_hint)[-4:] if account_hint else "0000"
    return f"****{suffix}"


def import_demo_statement(tenant):
    return PlatformStatement.objects.create(
        tenant=tenant,
        platform="mock",
        statement_no=f"DEMO-STMT-{tenant.id}",
        period_start="2026-01-01",
        period_end="2026-01-31",
        currency="USD",
        gross_amount=Decimal("1000.00"),
        fee_amount=Decimal("25.00"),
        net_amount=Decimal("975.00"),
        source_type=PlatformStatement.SourceType.DEMO,
    )


def import_demo_withdrawal(tenant):
    now = timezone.now()
    return WithdrawalRecord.objects.create(
        tenant=tenant,
        platform="mock",
        withdrawal_no=f"DEMO-WD-{tenant.id}",
        currency="USD",
        requested_amount=Decimal("975.00"),
        expected_amount=Decimal("975.00"),
        requested_at=now,
        completed_at=now,
        status=WithdrawalRecord.Status.COMPLETED,
    )


def import_demo_bank_receipt(tenant, amount=Decimal("975.00"), account_hint="demo-account"):
    return BankReceiptImport.objects.create(
        tenant=tenant,
        import_batch_no=f"DEMO-BANK-{tenant.id}",
        masked_account=mask_account(account_hint),
        currency="USD",
        receipt_amount=amount,
        receipt_date=timezone.now().date(),
        reference_no=f"DEMO-REF-{tenant.id}",
        status=BankReceiptImport.Status.IMPORTED,
    )


def run_mock_reconciliation(tenant):
    statement = PlatformStatement.objects.filter(tenant=tenant).order_by("-created_at", "-id").first()
    withdrawal = WithdrawalRecord.objects.filter(tenant=tenant).order_by("-requested_at", "-id").first()
    receipt = BankReceiptImport.objects.filter(tenant=tenant).order_by("-receipt_date", "-id").first()
    if not (statement and withdrawal and receipt):
        raise ValidationError("Demo statement, withdrawal, and bank receipt are required.")

    difference = receipt.receipt_amount - withdrawal.expected_amount
    match = ReconciliationMatch.objects.create(
        tenant=tenant,
        statement=statement,
        withdrawal=withdrawal,
        bank_receipt=receipt,
        match_type=ReconciliationMatch.MatchType.AUTO_SUGGESTED,
        matched_amount=min(receipt.receipt_amount, withdrawal.expected_amount),
        difference_amount=difference,
        confidence=Decimal("0.9500") if difference == 0 else Decimal("0.6500"),
        status=ReconciliationMatch.Status.SUGGESTED,
    )
    if difference != 0:
        ReconciliationException.objects.create(
            tenant=tenant,
            reconciliation_match=match,
            exception_type=ReconciliationException.ExceptionType.AMOUNT_DIFFERENCE,
            difference_amount=difference,
        )
    return match


def confirm_match(match, user):
    if match.tenant_id != user.tenant_id:
        raise ValidationError("Match does not belong to current tenant.")
    if match.status != ReconciliationMatch.Status.SUGGESTED:
        raise ValidationError("Reconciliation match has already been handled.")
    match.status = ReconciliationMatch.Status.CONFIRMED
    match.reviewed_by = user
    match.reviewed_at = timezone.now()
    match.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    write_finance_audit_log(
        match.tenant,
        user,
        "confirm_reconciliation_match",
        match,
        detail={"status": match.status, "difference_amount": str(match.difference_amount)},
    )
    return match


def reject_match(match, user, reason=""):
    if match.tenant_id != user.tenant_id:
        raise ValidationError("Match does not belong to current tenant.")
    if match.status != ReconciliationMatch.Status.SUGGESTED:
        raise ValidationError("Reconciliation match has already been handled.")
    match.status = ReconciliationMatch.Status.REJECTED
    match.reviewed_by = user
    match.reviewed_at = timezone.now()
    match.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    write_finance_audit_log(
        match.tenant,
        user,
        "reject_reconciliation_match",
        match,
        detail={"status": match.status, "reason": reason},
    )
    return match
