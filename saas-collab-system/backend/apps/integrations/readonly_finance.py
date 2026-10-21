"""Explicit, tenant-scoped read projections for finance facts and summaries."""
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Max, Min, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.finance.models import (
    BankReceiptImport,
    FinanceAuditLog,
    PlatformFinanceTransaction,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)


CONTRACTS = {
    "finance_imports": (FinanceAuditLog, ("id", "kind", "rows", "created", "skipped", "updated_at")),
    "finance_analytics": (PlatformStatement, (
        "id", "period_start", "period_end", "platform", "currency", "statement_amount",
        "matched_amount", "exception_count", "exception_amount", "updated_at",
    )),
    "platform_statements": (PlatformStatement, (
        "id", "platform", "statement_no", "period_start", "period_end", "currency",
        "gross_amount", "fee_amount", "net_amount", "source_type", "status", "created_at",
    )),
    "finance_transactions": (PlatformFinanceTransaction, (
        "id", "platform", "store_id", "external_order_id", "external_order_item_id",
        "sales_order_id", "sales_order_item_id", "seller_sku", "platform_variant_id",
        "fee_code", "fee_category", "raw_amount", "signed_amount", "currency",
        "business_date", "occurred_at_utc", "match_status", "external_transaction_id", "raw_fee_name", "created_at", "updated_at",
    )),
    "withdrawal_records": (WithdrawalRecord, (
        "id", "platform", "withdrawal_no", "currency", "requested_amount", "expected_amount",
        "requested_at", "completed_at", "status",
    )),
    "bank_receipts": (BankReceiptImport, (
        "id", "import_batch_no", "masked_account", "currency", "receipt_amount", "receipt_date",
        "reference_no", "status",
    )),
    "reconciliation_exceptions": (ReconciliationException, (
        "id", "reconciliation_match_id", "platform", "currency", "exception_type",
        "difference_amount", "status", "created_at", "resolved_at",
    )),
    "reconciliation_matches": (ReconciliationMatch, (
        "id", "statement_id", "withdrawal_id", "bank_receipt_id", "platform", "currency",
        "matched_amount", "difference_amount", "confidence", "match_type", "status",
    )),
}

_DIMENSIONS = ("period_start", "period_end", "platform", "currency")


def _valid_matches(tenant_id):
    """Reject any malformed or cross-tenant link in the reconciliation chain."""
    return ReconciliationMatch.objects.filter(
        tenant_id=tenant_id,
        statement__tenant_id=tenant_id,
        withdrawal__tenant_id=tenant_id,
        bank_receipt__tenant_id=tenant_id,
        withdrawal__platform=F("statement__platform"),
        withdrawal__currency=F("statement__currency"),
        bank_receipt__currency=F("statement__currency"),
    )


def _analytics(tenant_id):
    statements = PlatformStatement.objects.filter(tenant_id=tenant_id)
    confirmed = _valid_matches(tenant_id).filter(
        status=ReconciliationMatch.Status.CONFIRMED,
        statement__period_start=OuterRef("period_start"),
        statement__period_end=OuterRef("period_end"),
        statement__platform=OuterRef("platform"),
        statement__currency=OuterRef("currency"),
    )
    exceptions = ReconciliationException.objects.filter(
        tenant_id=tenant_id,
        reconciliation_match__in=_valid_matches(tenant_id),
        status=ReconciliationException.Status.OPEN,
        reconciliation_match__statement__period_start=OuterRef("period_start"),
        reconciliation_match__statement__period_end=OuterRef("period_end"),
        reconciliation_match__statement__platform=OuterRef("platform"),
        reconciliation_match__statement__currency=OuterRef("currency"),
    )
    matched_amount = confirmed.order_by().values("statement__period_start").annotate(
        total=Sum("matched_amount"),
    ).values("total")[:1]
    exception_count = exceptions.order_by().values("reconciliation_match__statement__period_start").annotate(
        total=Count("pk"),
    ).values("total")[:1]
    exception_amount = exceptions.order_by().values("reconciliation_match__statement__period_start").annotate(
        total=Sum("difference_amount"),
    ).values("total")[:1]
    # Group first, then attach related totals by the full grouping key. The
    # stable minimum statement ID is the pagination key for each whole group.
    return statements.order_by().values(*_DIMENSIONS).annotate(
        id=Min("pk"), statement_amount=Sum("gross_amount"), updated_at=Max("created_at"),
    ).annotate(
        matched_amount=Coalesce(
            Subquery(matched_amount), Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        exception_count=Coalesce(Subquery(exception_count), Value(0)),
        exception_amount=Coalesce(
            Subquery(exception_amount), Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
    )


def query(resource, tenant_id):
    """Return values-ready rows for a published finance resource."""
    if resource not in CONTRACTS:
        raise KeyError(resource)
    model, _ = CONTRACTS[resource]
    if resource == "finance_imports":
        # The manual CSV import writes one audit row per batch. Demo actions are
        # excluded; their statements remain visible through platform_statements.
        return FinanceAuditLog.objects.filter(
            tenant_id=tenant_id, action="import_finance_csv", object_type="FinanceImportBatch",
        ).annotate(
            kind=F("masked_detail__kind"), rows=F("masked_detail__rows"),
            created=F("masked_detail__created"), skipped=F("masked_detail__skipped"),
            updated_at=F("created_at"),
        ).values(*CONTRACTS[resource][1])
    if resource == "finance_analytics":
        return _analytics(tenant_id)
    if resource == "platform_statements":
        return PlatformStatement.objects.filter(tenant_id=tenant_id).values(*CONTRACTS[resource][1])
    if resource == "finance_transactions":
        return PlatformFinanceTransaction.objects.filter(
            tenant_id=tenant_id,
            store__tenant_id=tenant_id,
            authorization__tenant_id=tenant_id,
            source_run__tenant_id=tenant_id,
        ).filter(
            Q(sales_order__isnull=True) | Q(sales_order__tenant_id=tenant_id),
            Q(sales_order_item__isnull=True) | Q(sales_order_item__sales_order__tenant_id=tenant_id),
        ).values(*CONTRACTS[resource][1])
    if resource == "withdrawal_records":
        return WithdrawalRecord.objects.filter(tenant_id=tenant_id).values(*CONTRACTS[resource][1])
    if resource == "bank_receipts":
        return BankReceiptImport.objects.filter(tenant_id=tenant_id).values(*CONTRACTS[resource][1])
    if resource == "reconciliation_matches":
        return _valid_matches(tenant_id).annotate(
            platform=F("statement__platform"), currency=F("statement__currency"),
        ).values(*CONTRACTS[resource][1])
    if resource == "reconciliation_exceptions":
        return ReconciliationException.objects.filter(
            tenant_id=tenant_id,
            reconciliation_match__tenant_id=tenant_id,
            reconciliation_match__statement__tenant_id=tenant_id,
            reconciliation_match__withdrawal__tenant_id=tenant_id,
            reconciliation_match__bank_receipt__tenant_id=tenant_id,
            reconciliation_match__withdrawal__platform=F("reconciliation_match__statement__platform"),
            reconciliation_match__withdrawal__currency=F("reconciliation_match__statement__currency"),
            reconciliation_match__bank_receipt__currency=F("reconciliation_match__statement__currency"),
        ).annotate(
            platform=F("reconciliation_match__statement__platform"),
            currency=F("reconciliation_match__statement__currency"),
        ).values(*CONTRACTS[resource][1])
    raise AssertionError(f"Unhandled finance resource: {resource}")

