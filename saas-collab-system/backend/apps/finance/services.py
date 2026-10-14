from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.security import sanitize_sensitive_data

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
        masked_detail=sanitize_sensitive_data(detail or {}),
    )


def mask_account(account_hint="demo-account"):
    suffix = str(account_hint)[-4:] if account_hint else "0000"
    return f"****{suffix}"


def import_demo_statement(tenant):
    statement, _ = PlatformStatement.objects.update_or_create(
        tenant=tenant,
        statement_no=f"DEMO-STMT-{tenant.id}",
        defaults={
            "platform": "mock",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "currency": "USD",
            "gross_amount": Decimal("1000.00"),
            "fee_amount": Decimal("25.00"),
            "net_amount": Decimal("975.00"),
            "source_type": PlatformStatement.SourceType.DEMO,
        },
    )
    return statement


def import_demo_withdrawal(tenant):
    now = timezone.now()
    withdrawal, _ = WithdrawalRecord.objects.update_or_create(
        tenant=tenant,
        withdrawal_no=f"DEMO-WD-{tenant.id}",
        defaults={
            "platform": "mock",
            "currency": "USD",
            "requested_amount": Decimal("975.00"),
            "expected_amount": Decimal("975.00"),
            "requested_at": now,
            "completed_at": now,
            "status": WithdrawalRecord.Status.COMPLETED,
        },
    )
    return withdrawal


def import_demo_bank_receipt(tenant, amount=Decimal("975.00"), account_hint="demo-account"):
    receipt, _ = BankReceiptImport.objects.update_or_create(
        tenant=tenant,
        reference_no=f"DEMO-REF-{tenant.id}",
        defaults={
            "import_batch_no": f"DEMO-BANK-{tenant.id}",
            "masked_account": mask_account(account_hint),
            "currency": "USD",
            "receipt_amount": amount,
            "receipt_date": timezone.now().date(),
            "status": BankReceiptImport.Status.IMPORTED,
        },
    )
    return receipt


def run_mock_reconciliation(tenant):
    statement = PlatformStatement.objects.filter(
        tenant=tenant, platform="mock", source_type=PlatformStatement.SourceType.DEMO,
        statement_no=f"DEMO-STMT-{tenant.id}",
    ).first()
    withdrawal = WithdrawalRecord.objects.filter(
        tenant=tenant, platform="mock", withdrawal_no=f"DEMO-WD-{tenant.id}",
        status=WithdrawalRecord.Status.COMPLETED,
    ).first()
    receipt = BankReceiptImport.objects.filter(
        tenant=tenant, import_batch_no=f"DEMO-BANK-{tenant.id}",
        reference_no=f"DEMO-REF-{tenant.id}",
    ).first()
    if not (statement and withdrawal and receipt):
        raise ValidationError("Demo statement, withdrawal, and bank receipt are required.")
    if statement.currency != withdrawal.currency or withdrawal.currency != receipt.currency:
        raise ValidationError("Demo reconciliation entities must use the same currency.")

    with transaction.atomic():
        statement = PlatformStatement.objects.select_for_update().get(pk=statement.pk)
        withdrawal = WithdrawalRecord.objects.select_for_update().get(pk=withdrawal.pk)
        receipt = BankReceiptImport.objects.select_for_update().get(pk=receipt.pk)
        _ensure_unoccupied(tenant, withdrawal.pk, receipt.pk)
        return _create_match(tenant, statement, withdrawal, receipt, ReconciliationMatch.MatchType.AUTO_SUGGESTED)


def confirm_match(match, user):
    with transaction.atomic():
        match = ReconciliationMatch.objects.select_for_update().select_related(
            "statement", "withdrawal", "bank_receipt", "tenant"
        ).get(pk=match.pk)
        _validate_reviewer_scope(match, user)
        if not _scope_allows(user, match.statement.platform, match.statement.currency):
            raise ValidationError("Match exceeds finance.reconcile data scope.")
        if not _scope_allows(user, "", match.bank_receipt.currency):
            raise ValidationError("Bank receipt exceeds finance.reconcile data scope.")
        if match.status != ReconciliationMatch.Status.SUGGESTED:
            raise ValidationError("Reconciliation match has already been handled.")
        if match.difference_amount != 0:
            raise ValidationError("A match with a non-zero difference cannot be confirmed.")
        if match.statement.platform != match.withdrawal.platform or len({match.statement.currency, match.withdrawal.currency, match.bank_receipt.currency}) != 1:
            raise ValidationError("Reconciliation source platforms and currencies no longer agree.")
        if match.withdrawal.status != WithdrawalRecord.Status.COMPLETED or min(match.withdrawal.expected_amount, match.bank_receipt.receipt_amount) <= 0:
            raise ValidationError("Only positive receipts and completed withdrawals can be confirmed.")
        if not _scope_allows(user, match.withdrawal.platform, match.withdrawal.currency):
            raise ValidationError("Withdrawal exceeds finance.reconcile data scope.")
        if match.bank_receipt.receipt_amount != match.withdrawal.expected_amount or match.matched_amount != match.withdrawal.expected_amount:
            raise ValidationError("Stored matching amounts no longer agree with source facts.")
        other_active = ReconciliationMatch.objects.filter(
            tenant=match.tenant, status__in=(ReconciliationMatch.Status.SUGGESTED, ReconciliationMatch.Status.CONFIRMED),
        ).exclude(pk=match.pk)
        if other_active.filter(withdrawal_id=match.withdrawal_id).exists() or other_active.filter(bank_receipt_id=match.bank_receipt_id).exists():
            raise ValidationError("The withdrawal or bank receipt is used by another active match.")
        active_total = ReconciliationMatch.objects.filter(
            statement=match.statement, status__in=(ReconciliationMatch.Status.SUGGESTED, ReconciliationMatch.Status.CONFIRMED),
        ).aggregate(total=Sum("withdrawal__expected_amount"))["total"] or Decimal("0.00")
        if active_total > match.statement.net_amount:
            raise ValidationError("Active withdrawals exceed the statement net amount.")
        match.status = ReconciliationMatch.Status.CONFIRMED
        match.reviewed_by = user
        match.reviewed_at = timezone.now()
        match.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        statement = PlatformStatement.objects.select_for_update().get(pk=match.statement_id)
        confirmed_total = ReconciliationMatch.objects.filter(
            statement=statement, status=ReconciliationMatch.Status.CONFIRMED
        ).aggregate(total=Sum("matched_amount"))["total"] or Decimal("0.00")
        statement.status = (
            PlatformStatement.Status.MATCHED
            if confirmed_total == statement.net_amount
            else PlatformStatement.Status.MATCHING
        )
        statement.save(update_fields=["status"])
        match.bank_receipt.status = BankReceiptImport.Status.MATCHED
        match.bank_receipt.save(update_fields=["status"])
        write_finance_audit_log(
            match.tenant, user, "confirm_reconciliation_match", match,
            detail={"status": match.status, "difference_amount": str(match.difference_amount)},
        )
        return match


def reject_match(match, user, reason=""):
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError({"reason": "A non-empty rejection reason is required."})
    with transaction.atomic():
        match = ReconciliationMatch.objects.select_for_update().select_related(
            "statement", "withdrawal", "bank_receipt", "tenant"
        ).get(pk=match.pk)
        _validate_reviewer_scope(match, user)
        if not _scope_allows(user, match.statement.platform, match.statement.currency):
            raise ValidationError("Match exceeds finance.reconcile data scope.")
        if not _scope_allows(user, "", match.bank_receipt.currency):
            raise ValidationError("Bank receipt exceeds finance.reconcile data scope.")
        if match.status != ReconciliationMatch.Status.SUGGESTED:
            raise ValidationError("Reconciliation match has already been handled.")
        match.status = ReconciliationMatch.Status.REJECTED
        match.reviewed_by = user
        match.reviewed_at = timezone.now()
        match.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        write_finance_audit_log(
            match.tenant, user, "reject_reconciliation_match", match,
            detail={"status": match.status, "reason": reason.strip()},
        )
        return match


def _validate_reviewer_scope(match, user):
    if match.tenant_id != user.tenant_id or any(
        entity.tenant_id != user.tenant_id
        for entity in (match.statement, match.withdrawal, match.bank_receipt)
    ):
        raise ValidationError("Match does not belong to current tenant.")


def _ensure_unoccupied(tenant, withdrawal_id, receipt_id):
    occupied = ReconciliationMatch.objects.filter(
        tenant=tenant,
        status__in=(ReconciliationMatch.Status.SUGGESTED, ReconciliationMatch.Status.CONFIRMED),
    ).filter(withdrawal_id=withdrawal_id).exists() or ReconciliationMatch.objects.filter(
        tenant=tenant,
        status__in=(ReconciliationMatch.Status.SUGGESTED, ReconciliationMatch.Status.CONFIRMED),
        bank_receipt_id=receipt_id,
    ).exists()
    if occupied:
        raise ValidationError("The withdrawal or bank receipt is already in an active match.")


def _create_match(tenant, statement, withdrawal, receipt, match_type):
    if any(entity.tenant_id != tenant.id for entity in (statement, withdrawal, receipt)):
        raise ValidationError("All reconciliation entities must belong to current tenant.")
    if statement.platform != withdrawal.platform:
        raise ValidationError("Statement and withdrawal platforms must match.")
    if statement.currency != withdrawal.currency or withdrawal.currency != receipt.currency:
        raise ValidationError("All reconciliation entities must use the same currency.")
    if withdrawal.status != WithdrawalRecord.Status.COMPLETED:
        raise ValidationError("Only completed withdrawals can be reconciled.")
    if min(withdrawal.expected_amount, receipt.receipt_amount) <= 0 or receipt.status != BankReceiptImport.Status.IMPORTED:
        raise ValidationError("Only positive, unconfirmed receipts can be reconciled.")
    _ensure_unoccupied(tenant, withdrawal.pk, receipt.pk)
    active_expected = ReconciliationMatch.objects.filter(
        statement=statement,
        status__in=(ReconciliationMatch.Status.SUGGESTED, ReconciliationMatch.Status.CONFIRMED),
    ).aggregate(total=Sum("withdrawal__expected_amount"))["total"] or Decimal("0.00")
    if active_expected + withdrawal.expected_amount > statement.net_amount:
        raise ValidationError("Active withdrawals cannot exceed the statement net amount.")
    difference = receipt.receipt_amount - withdrawal.expected_amount
    match = ReconciliationMatch.objects.create(
        tenant=tenant, statement=statement, withdrawal=withdrawal, bank_receipt=receipt,
        match_type=match_type,
        matched_amount=min(receipt.receipt_amount, withdrawal.expected_amount),
        difference_amount=difference,
        confidence=Decimal("1.0000") if match_type == ReconciliationMatch.MatchType.MANUAL else (
            Decimal("0.9500") if difference == 0 else Decimal("0.6500")
        ),
        status=ReconciliationMatch.Status.SUGGESTED,
    )
    if difference != 0:
        ReconciliationException.objects.create(
            tenant=tenant, reconciliation_match=match,
            exception_type=ReconciliationException.ExceptionType.AMOUNT_DIFFERENCE,
            difference_amount=difference,
        )
    return match


def create_manual_match(tenant, user, statement_id, withdrawal_id, receipt_id):
    with transaction.atomic():
        # Lock in a fixed entity-type order so concurrent manual matches cannot
        # claim the same withdrawal or receipt between validation and insert.
        statement = PlatformStatement.objects.select_for_update().filter(
            tenant=tenant, pk=statement_id
        ).first()
        withdrawal = WithdrawalRecord.objects.select_for_update().filter(
            tenant=tenant, pk=withdrawal_id
        ).first()
        receipt = BankReceiptImport.objects.select_for_update().filter(
            tenant=tenant, pk=receipt_id
        ).first()
        if not (statement and withdrawal and receipt):
            raise ValidationError("All reconciliation entities must belong to current tenant.")
        if not _scope_allows(user, statement.platform, statement.currency):
            raise ValidationError("Reconciliation entities exceed finance.reconcile data scope.")
        if not _scope_allows(user, withdrawal.platform, withdrawal.currency) or not _scope_allows(
            user, "", receipt.currency
        ):
            raise ValidationError("Reconciliation entities exceed finance.reconcile data scope.")
        match = _create_match(tenant, statement, withdrawal, receipt, ReconciliationMatch.MatchType.MANUAL)
        write_finance_audit_log(
            tenant, user, "create_manual_reconciliation_match", match,
            detail={"status": match.status, "difference_amount": str(match.difference_amount)},
        )
        return match


def _scope_allows(user, platform, currency, permission_code="finance.reconcile"):
    from apps.permissions.ui_p6_scopes import finance_values_allowed

    return finance_values_allowed(user, permission_code, platform=platform, currency=currency)


def resolve_exception(exception, user, reason):
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError({"reason": "A non-empty resolution reason is required."})
    with transaction.atomic():
        exception = ReconciliationException.objects.select_for_update().select_related(
            "reconciliation_match__statement", "reconciliation_match__withdrawal",
            "reconciliation_match__bank_receipt", "tenant",
        ).get(pk=exception.pk)
        match = exception.reconciliation_match
        _validate_reviewer_scope(match, user)
        if exception.tenant_id != user.tenant_id:
            raise ValidationError("Exception does not belong to current tenant.")
        if not _scope_allows(user, match.statement.platform, match.statement.currency, permission_code="finance.exception.handle"):
            raise ValidationError("Exception exceeds finance.exception.handle data scope.")
        if not _scope_allows(user, "", match.bank_receipt.currency, permission_code="finance.exception.handle"):
            raise ValidationError("Bank receipt exceeds finance.exception.handle data scope.")
        if not _scope_allows(user, match.withdrawal.platform, match.withdrawal.currency, permission_code="finance.exception.handle"):
            raise ValidationError("Withdrawal exceeds finance.exception.handle data scope.")
        if match.statement.platform != match.withdrawal.platform or len({match.statement.currency, match.withdrawal.currency, match.bank_receipt.currency}) != 1:
            raise ValidationError("Exception source platforms and currencies do not agree.")
        if exception.status != ReconciliationException.Status.OPEN:
            raise ValidationError("Exception has already been resolved.")
        if match.status != ReconciliationMatch.Status.REJECTED:
            raise ValidationError("Only exceptions for rejected matches can be resolved.")
        exception.status = ReconciliationException.Status.RESOLVED
        exception.assigned_to = user
        exception.resolution_note = reason.strip()
        exception.resolved_at = timezone.now()
        exception.save(update_fields=["status", "assigned_to", "resolution_note", "resolved_at"])
        write_finance_audit_log(
            exception.tenant, user, "resolve_reconciliation_exception", exception,
            detail={"reason": reason.strip(), "status": exception.status},
        )
        return exception
