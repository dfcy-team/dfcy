from django.contrib import admin

from .models import (
    BankReceiptImport,
    FinanceAuditLog,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)


@admin.register(PlatformStatement)
class PlatformStatementAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "statement_no", "currency", "net_amount", "status", "created_at")
    list_filter = ("platform", "currency", "status", "tenant")
    search_fields = ("statement_no", "tenant__code")


@admin.register(WithdrawalRecord)
class WithdrawalRecordAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "withdrawal_no", "currency", "expected_amount", "status")
    list_filter = ("platform", "currency", "status", "tenant")
    search_fields = ("withdrawal_no", "tenant__code")


@admin.register(BankReceiptImport)
class BankReceiptImportAdmin(admin.ModelAdmin):
    list_display = ("tenant", "import_batch_no", "masked_account", "currency", "receipt_amount", "status")
    list_filter = ("currency", "status", "tenant")
    search_fields = ("import_batch_no", "reference_no", "masked_account", "tenant__code")


@admin.register(ReconciliationMatch)
class ReconciliationMatchAdmin(admin.ModelAdmin):
    list_display = ("tenant", "statement", "withdrawal", "bank_receipt", "status", "difference_amount", "confidence")
    list_filter = ("match_type", "status", "tenant")
    search_fields = ("statement__statement_no", "withdrawal__withdrawal_no", "bank_receipt__reference_no")


@admin.register(ReconciliationException)
class ReconciliationExceptionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "reconciliation_match", "exception_type", "difference_amount", "status")
    list_filter = ("exception_type", "status", "tenant")
    search_fields = ("resolution_note",)


@admin.register(FinanceAuditLog)
class FinanceAuditLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "actor", "action", "object_type", "object_id", "created_at")
    list_filter = ("action", "object_type", "tenant")
    search_fields = ("actor__username", "object_id", "tenant__code")
