from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class PlatformStatement(models.Model):
    class SourceType(models.TextChoices):
        DEMO = "demo", "Demo"
        MANUAL_IMPORT = "manual_import", "Manual import"
        FIXTURE = "fixture", "Fixture"

    class Status(models.TextChoices):
        IMPORTED = "imported", "Imported"
        MATCHING = "matching", "Matching"
        MATCHED = "matched", "Matched"
        EXCEPTION = "exception", "Exception"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="platform_statements")
    platform = models.CharField(max_length=40)
    statement_no = models.CharField(max_length=80)
    period_start = models.DateField()
    period_end = models.DateField()
    currency = models.CharField(max_length=10, default="USD")
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    source_type = models.CharField(max_length=30, choices=SourceType.choices, default=SourceType.DEMO)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.IMPORTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "statement_no"], name="uniq_statement_no_per_tenant"),
        ]


class PlatformFinanceTransaction(models.Model):
    class FeeCategory(models.TextChoices):
        INCOME = "income", "Income"
        PLATFORM_FEE = "platform_fee", "Platform fee"
        LOGISTICS_FEE = "logistics_fee", "Logistics fee"
        DISCOUNT = "discount", "Discount"
        REFUND = "refund", "Refund"
        TAX = "tax", "Tax"
        ADJUSTMENT = "adjustment", "Adjustment"
        OTHER = "other", "Other"

    class MatchStatus(models.TextChoices):
        MATCHED = "matched", "Matched"
        ORDER_ONLY = "order_only", "Order only"
        UNMATCHED = "unmatched", "Unmatched"
        CONFLICT = "conflict", "Conflict"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="platform_finance_transactions")
    platform = models.CharField(max_length=30, default="lazada")
    store = models.ForeignKey(
        "masterdata.StoreMaster",
        on_delete=models.PROTECT,
        related_name="platform_finance_transactions",
    )
    authorization = models.ForeignKey(
        "integrations.MarketplaceStoreAuthorization",
        on_delete=models.PROTECT,
        related_name="finance_transactions",
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun",
        on_delete=models.PROTECT,
        related_name="finance_transactions",
    )
    raw_envelope = models.ForeignKey(
        "integrations.SyncRawEnvelope",
        on_delete=models.PROTECT,
        related_name="finance_transactions",
        null=True,
        blank=True,
    )
    source_key = models.CharField(max_length=191)
    external_transaction_id = models.CharField(max_length=191, blank=True)
    external_order_id = models.CharField(max_length=191, blank=True)
    external_order_item_id = models.CharField(max_length=191, blank=True)
    sales_order = models.ForeignKey(
        "commerce.SalesOrder",
        on_delete=models.PROTECT,
        related_name="finance_transactions",
        null=True,
        blank=True,
    )
    sales_order_item = models.ForeignKey(
        "commerce.SalesOrderItem",
        on_delete=models.PROTECT,
        related_name="finance_transactions",
        null=True,
        blank=True,
    )
    seller_sku = models.CharField(max_length=191, blank=True)
    platform_variant_id = models.CharField(max_length=191, blank=True)
    raw_fee_name = models.CharField(max_length=191)
    fee_code = models.CharField(max_length=40)
    fee_category = models.CharField(max_length=30, choices=FeeCategory.choices)
    raw_amount = models.DecimalField(max_digits=20, decimal_places=4)
    signed_amount = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.CharField(max_length=8)
    occurred_at_utc = models.DateTimeField()
    business_date = models.DateField()
    match_status = models.CharField(max_length=20, choices=MatchStatus.choices)
    normalization_version = models.CharField(max_length=40)
    payload_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "store_id", "-occurred_at_utc", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "store", "source_key"],
                name="uniq_fin_tx_store_source",
            ),
            models.CheckConstraint(
                condition=models.Q(platform__in=("lazada", "shopee", "tiktok")),
                name="chk_fin_tx_marketplace",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "business_date"], name="idx_fin_tx_store_date"),
            models.Index(fields=["tenant", "external_order_id"], name="idx_fin_tx_order"),
            models.Index(fields=["tenant", "fee_code", "business_date"], name="idx_fin_tx_fee_date"),
            models.Index(fields=["source_run"], name="idx_fin_tx_run"),
            models.Index(fields=["match_status"], name="idx_fin_tx_match"),
        ]


class LazadaFinanceWide(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="lazada_finance_wide_rows")
    store = models.ForeignKey(
        "masterdata.StoreMaster", on_delete=models.PROTECT, related_name="lazada_finance_wide_rows"
    )
    authorization = models.ForeignKey(
        "integrations.MarketplaceStoreAuthorization",
        on_delete=models.PROTECT,
        related_name="finance_wide_rows",
    )
    source_run = models.ForeignKey(
        "integrations.SyncRun", on_delete=models.PROTECT, related_name="finance_wide_rows"
    )
    income_key = models.CharField(max_length=64)
    site = models.CharField(max_length=20)
    transaction_date = models.DateField()
    transaction_month = models.CharField(max_length=7)
    currency = models.CharField(max_length=8)
    external_order_id = models.CharField(max_length=191, blank=True)
    external_order_item_id = models.CharField(max_length=191)
    seller_sku = models.CharField(max_length=191, blank=True)
    lazada_sku = models.CharField(max_length=191, blank=True)
    order_item_status = models.CharField(max_length=80, blank=True)
    item_name = models.CharField(max_length=240, blank=True)

    item_price_credit = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_item_price = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    commission = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    payment_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    payment_fee_credit = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_commission = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    free_shipping_max_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_free_shipping_max_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    shipping_fee_refund_to_customer = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    shipping_fee_voucher_refund_to_laz = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    sponsored_affiliates = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    promotional_charges_vouchers = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_promotional_charges_vouchers = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    promotional_charges_flexi_combo = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_promotional_charges_flexi_combo = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    lazcoins_discount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_lazcoins_discount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    lazcoins_discount_promotion_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_lazcoins_discount_promotion_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    order_processing_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_order_processing_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    spa_program_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    reversal_spa_program_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    wrong_shipping_fee_adjustment = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    withholding_tax = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    other_fee = models.DecimalField(max_digits=20, decimal_places=4, default=0)

    sales_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    platform_fee_total = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    net_income = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    source_row_count = models.PositiveIntegerField(default=0)
    allocation_methods = models.JSONField(default=list)
    unknown_fee_names = models.JSONField(default=list)
    fee_details = models.JSONField(default=list)
    source_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "lazada_finance_wide"
        ordering = ["-transaction_date", "store_id", "external_order_item_id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "income_key"], name="uniq_lazada_income_key"),
        ]
        indexes = [
            models.Index(fields=["tenant", "store", "transaction_date"], name="idx_lz_wide_store_date"),
            models.Index(fields=["tenant", "external_order_id"], name="idx_lz_wide_order"),
            models.Index(fields=["tenant", "seller_sku"], name="idx_lz_wide_sku"),
        ]


class WithdrawalRecord(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="withdrawal_records")
    platform = models.CharField(max_length=40)
    withdrawal_no = models.CharField(max_length=80)
    currency = models.CharField(max_length=10, default="USD")
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    requested_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.REQUESTED)

    class Meta:
        ordering = ["tenant_id", "-requested_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "withdrawal_no"], name="uniq_withdrawal_no_per_tenant"),
        ]


class BankReceiptImport(models.Model):
    class Status(models.TextChoices):
        IMPORTED = "imported", "Imported"
        MATCHED = "matched", "Matched"
        EXCEPTION = "exception", "Exception"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="bank_receipt_imports")
    import_batch_no = models.CharField(max_length=80)
    masked_account = models.CharField(max_length=80)
    currency = models.CharField(max_length=10, default="USD")
    receipt_amount = models.DecimalField(max_digits=12, decimal_places=2)
    receipt_date = models.DateField()
    reference_no = models.CharField(max_length=120)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.IMPORTED)

    class Meta:
        ordering = ["tenant_id", "-receipt_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference_no"], name="uniq_receipt_reference_per_tenant"),
        ]


class ReconciliationMatch(models.Model):
    class MatchType(models.TextChoices):
        AUTO_SUGGESTED = "auto_suggested", "Auto suggested"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="reconciliation_matches")
    statement = models.ForeignKey(PlatformStatement, on_delete=models.PROTECT, related_name="reconciliation_matches")
    withdrawal = models.ForeignKey(WithdrawalRecord, on_delete=models.PROTECT, related_name="reconciliation_matches")
    bank_receipt = models.ForeignKey(BankReceiptImport, on_delete=models.PROTECT, related_name="reconciliation_matches")
    match_type = models.CharField(max_length=30, choices=MatchType.choices, default=MatchType.AUTO_SUGGESTED)
    matched_amount = models.DecimalField(max_digits=12, decimal_places=2)
    difference_amount = models.DecimalField(max_digits=12, decimal_places=2)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.SUGGESTED)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_reconciliation_matches",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_id", "-id"]


class ReconciliationException(models.Model):
    class ExceptionType(models.TextChoices):
        AMOUNT_DIFFERENCE = "amount_difference", "Amount difference"
        CURRENCY_MISMATCH = "currency_mismatch", "Currency mismatch"
        MISSING_RECEIPT = "missing_receipt", "Missing receipt"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="reconciliation_exceptions")
    reconciliation_match = models.ForeignKey(
        ReconciliationMatch,
        on_delete=models.CASCADE,
        related_name="exceptions",
    )
    exception_type = models.CharField(max_length=40, choices=ExceptionType.choices)
    difference_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_reconciliation_exceptions",
        null=True,
        blank=True,
    )
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]


class FinanceAuditLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="finance_audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="finance_audit_logs")
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80)
    masked_detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "-created_at"]
