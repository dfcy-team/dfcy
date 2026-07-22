import hashlib
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.common.security import sanitize_sensitive_data
from apps.permissions.services import check_user_permission

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


def _demo_reference(prefix, tenant, platform, currency):
    digest = hashlib.sha256(f"{platform}:{currency}".encode("utf-8")).hexdigest()[:10]
    return f"DEMO-{prefix}-{tenant.id}-{digest}"


def _validate_demo_source(platform, currency):
    platform = str(platform or "").strip().lower()
    currency = str(currency or "").strip().upper()
    if not platform.startswith(("demo", "mock", "synthetic", "local")):
        raise BusinessRuleViolation("Only demo, mock, synthetic, or local platform identifiers are accepted.")
    if len(currency) != 3 or not currency.isalpha():
        raise BusinessRuleViolation("Currency must use a three-letter code.")
    return platform, currency


def import_demo_statement(tenant, *, platform="mock", currency="USD"):
    platform, currency = _validate_demo_source(platform, currency)
    statement, _ = PlatformStatement.objects.update_or_create(
        tenant=tenant,
        statement_no=_demo_reference("STMT", tenant, platform, currency),
        defaults={
            "platform": platform,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "currency": currency,
            "gross_amount": Decimal("1000.00"),
            "fee_amount": Decimal("25.00"),
            "net_amount": Decimal("975.00"),
            "source_type": PlatformStatement.SourceType.DEMO,
        },
    )
    return statement


def import_demo_withdrawal(tenant, *, platform="mock", currency="USD"):
    platform, currency = _validate_demo_source(platform, currency)
    now = timezone.now()
    withdrawal, _ = WithdrawalRecord.objects.update_or_create(
        tenant=tenant,
        withdrawal_no=_demo_reference("WD", tenant, platform, currency),
        defaults={
            "platform": platform,
            "currency": currency,
            "requested_amount": Decimal("975.00"),
            "expected_amount": Decimal("975.00"),
            "requested_at": now,
            "completed_at": now,
            "status": WithdrawalRecord.Status.COMPLETED,
        },
    )
    return withdrawal


def import_demo_bank_receipt(
    tenant,
    amount=Decimal("975.00"),
    account_hint="demo-account",
    *,
    platform="mock",
    currency="USD",
):
    platform, currency = _validate_demo_source(platform, currency)
    receipt, _ = BankReceiptImport.objects.update_or_create(
        tenant=tenant,
        reference_no=_demo_reference("REF", tenant, platform, currency),
        defaults={
            "import_batch_no": _demo_reference("BANK", tenant, platform, currency),
            "masked_account": mask_account(account_hint),
            "currency": currency,
            "receipt_amount": amount,
            "receipt_date": timezone.now().date(),
            "status": BankReceiptImport.Status.IMPORTED,
        },
    )
    return receipt


@transaction.atomic
def run_mock_reconciliation(tenant, *, platform="mock", currency="USD", idempotency_key=""):
    platform, currency = _validate_demo_source(platform, currency)
    statement = PlatformStatement.objects.filter(
        tenant=tenant, platform=platform, currency=currency
    ).order_by("-created_at", "-id").first()
    withdrawal = WithdrawalRecord.objects.filter(
        tenant=tenant, platform=platform, currency=currency
    ).order_by("-requested_at", "-id").first()
    receipt = BankReceiptImport.objects.filter(
        tenant=tenant, currency=currency
    ).order_by("-receipt_date", "-id").first()
    if not (statement and withdrawal and receipt):
        raise BusinessRuleViolation("Demo statement, withdrawal, and bank receipt are required.")

    raw_key = str(idempotency_key or f"auto:{statement.id}:{withdrawal.id}:{receipt.id}")
    normalized_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    existing = ReconciliationMatch.objects.filter(tenant=tenant, idempotency_key=normalized_key).first()
    if existing:
        return existing

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
        idempotency_key=normalized_key,
    )
    if difference != 0:
        ReconciliationException.objects.create(
            tenant=tenant,
            reconciliation_match=match,
            exception_type=ReconciliationException.ExceptionType.AMOUNT_DIFFERENCE,
            difference_amount=difference,
        )
    return match


@transaction.atomic
def confirm_match(match, user):
    if match.tenant_id != user.tenant_id:
        raise ValidationError("Match does not belong to current tenant.")
    if match.status != ReconciliationMatch.Status.SUGGESTED:
        raise StateConflict("Reconciliation match has already been handled.")
    match = ReconciliationMatch.objects.select_for_update().get(pk=match.pk, tenant=user.tenant)
    if match.status != ReconciliationMatch.Status.SUGGESTED:
        raise StateConflict("Reconciliation match has already been handled.")
    match.status = ReconciliationMatch.Status.CONFIRMED
    match.reviewed_by = user
    match.reviewed_at = timezone.now()
    match._review_service_write = True
    match.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    write_finance_audit_log(
        match.tenant,
        user,
        "confirm_reconciliation_match",
        match,
        detail={"status": match.status, "difference_amount": str(match.difference_amount)},
    )
    return match


@transaction.atomic
def reject_match(match, user, reason=""):
    if match.tenant_id != user.tenant_id:
        raise ValidationError("Match does not belong to current tenant.")
    if match.status != ReconciliationMatch.Status.SUGGESTED:
        raise StateConflict("Reconciliation match has already been handled.")
    match = ReconciliationMatch.objects.select_for_update().get(pk=match.pk, tenant=user.tenant)
    if match.status != ReconciliationMatch.Status.SUGGESTED:
        raise StateConflict("Reconciliation match has already been handled.")
    match.status = ReconciliationMatch.Status.REJECTED
    match.reviewed_by = user
    match.reviewed_at = timezone.now()
    match._review_service_write = True
    match.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    write_finance_audit_log(
        match.tenant,
        user,
        "reject_reconciliation_match",
        match,
        detail={"status": match.status, "reason": reason},
    )
    return match


@transaction.atomic
def resolve_exception(exception, user, *, resolution_note):
    if (
        exception.tenant_id != user.tenant_id
        or user.user_type != "internal"
        or not check_user_permission(user, "finance.exception.handle")
    ):
        raise ValidationError("An authorized finance exception handler is required.")
    exception = ReconciliationException.objects.select_for_update().get(pk=exception.pk, tenant=user.tenant)
    if exception.status != ReconciliationException.Status.OPEN:
        raise StateConflict("Reconciliation exception has already been handled.")
    note = str(resolution_note or "").strip()
    if not note:
        raise ValidationError("A resolution note is required.")
    exception.status = ReconciliationException.Status.RESOLVED
    exception.assigned_to = user
    exception.resolution_note = note
    exception.resolved_at = timezone.now()
    exception._resolution_service_write = True
    exception.save(update_fields=["status", "assigned_to", "resolution_note", "resolved_at"])
    write_finance_audit_log(
        exception.tenant,
        user,
        "resolve_reconciliation_exception",
        exception,
        detail={"status": exception.status, "resolution_note": note, "fund_action_performed": False},
    )
    return exception
