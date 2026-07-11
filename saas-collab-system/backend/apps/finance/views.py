from django.shortcuts import get_object_or_404
from django.db.models import Count, Sum
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsFinanceImporter, IsFinanceReconciler, IsFinanceUser, IsFinanceViewer
from .models import BankReceiptImport, FinanceAuditLog, PlatformStatement, ReconciliationException, ReconciliationMatch, WithdrawalRecord
from .serializers import (
    BankReceiptImportSerializer,
    PlatformStatementSerializer,
    ReconciliationExceptionSerializer,
    ReconciliationMatchSerializer,
    WithdrawalRecordSerializer,
)
from .services import (
    confirm_match,
    import_demo_bank_receipt,
    import_demo_statement,
    import_demo_withdrawal,
    reject_match,
    run_mock_reconciliation,
    write_finance_audit_log,
)


@api_view(["GET"])
@permission_classes([IsFinanceUser])
def health(request):
    return success_response({"status": "ok", "service": "finance"})


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def statement_collection(request):
    queryset = PlatformStatement.objects.filter(tenant=request.user.tenant)
    return success_response(PlatformStatementSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsFinanceImporter])
def import_demo_statement_view(request):
    statement = import_demo_statement(request.user.tenant)
    write_finance_audit_log(request.user.tenant, request.user, "import_demo_statement", statement)
    return success_response(PlatformStatementSerializer(statement).data, status=201)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def withdrawal_collection(request):
    queryset = WithdrawalRecord.objects.filter(tenant=request.user.tenant)
    return success_response(WithdrawalRecordSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsFinanceImporter])
def import_demo_withdrawal_view(request):
    withdrawal = import_demo_withdrawal(request.user.tenant)
    write_finance_audit_log(request.user.tenant, request.user, "import_demo_withdrawal", withdrawal)
    return success_response(WithdrawalRecordSerializer(withdrawal).data, status=201)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def bank_receipt_collection(request):
    queryset = BankReceiptImport.objects.filter(tenant=request.user.tenant)
    return success_response(BankReceiptImportSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsFinanceImporter])
def import_demo_bank_receipt_view(request):
    receipt = import_demo_bank_receipt(request.user.tenant, account_hint=request.data.get("account_hint", "demo-account"))
    write_finance_audit_log(
        request.user.tenant,
        request.user,
        "import_demo_bank_receipt",
        receipt,
        detail={"masked_account": receipt.masked_account},
    )
    return success_response(BankReceiptImportSerializer(receipt).data, status=201)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def reconciliation_match_collection(request):
    queryset = ReconciliationMatch.objects.filter(tenant=request.user.tenant)
    return success_response(ReconciliationMatchSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsFinanceReconciler])
def run_mock_reconciliation_view(request):
    match = run_mock_reconciliation(request.user.tenant)
    write_finance_audit_log(
        request.user.tenant,
        request.user,
        "run_mock_reconciliation",
        match,
        detail={"status": match.status, "difference_amount": str(match.difference_amount)},
    )
    return success_response(ReconciliationMatchSerializer(match).data, status=201)


@api_view(["POST"])
@permission_classes([IsFinanceReconciler])
def confirm_reconciliation_match(request, pk):
    match = get_object_or_404(ReconciliationMatch, pk=pk, tenant=request.user.tenant)
    match = confirm_match(match, request.user)
    return success_response(ReconciliationMatchSerializer(match).data)


@api_view(["POST"])
@permission_classes([IsFinanceReconciler])
def reject_reconciliation_match(request, pk):
    match = get_object_or_404(ReconciliationMatch, pk=pk, tenant=request.user.tenant)
    match = reject_match(match, request.user, reason=request.data.get("reason", ""))
    return success_response(ReconciliationMatchSerializer(match).data)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def reconciliation_exception_collection(request):
    queryset = ReconciliationException.objects.filter(tenant=request.user.tenant)
    return success_response(ReconciliationExceptionSerializer(queryset, many=True).data)


def _audit_analytics_view(request, action):
    FinanceAuditLog.objects.create(
        tenant=request.user.tenant,
        actor=request.user,
        action=action,
        object_type="FinanceAnalytics",
        object_id="aggregate",
        masked_detail={"mode": "read_only", "sensitive_fields": "masked"},
    )


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def finance_analytics_overview(request):
    rows = list(
        PlatformStatement.objects.filter(tenant=request.user.tenant)
        .values("currency")
        .annotate(
            statement_count=Count("id"),
            gross_amount=Sum("gross_amount"),
            fee_amount=Sum("fee_amount"),
            net_amount=Sum("net_amount"),
        )
        .order_by("currency")
    )
    _audit_analytics_view(request, "view_finance_analytics_overview")
    return success_response({"currencies": rows, "account_details": "***", "read_only": True})


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def finance_analytics_reconciliation(request):
    rows = list(
        ReconciliationMatch.objects.filter(tenant=request.user.tenant)
        .values("status")
        .annotate(match_count=Count("id"), total_difference=Sum("difference_amount"))
        .order_by("status")
    )
    _audit_analytics_view(request, "view_finance_analytics_reconciliation")
    return success_response({"statuses": rows, "read_only": True, "fund_action_available": False})


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def finance_analytics_exceptions(request):
    rows = list(
        ReconciliationException.objects.filter(tenant=request.user.tenant)
        .values("exception_type", "status")
        .annotate(exception_count=Count("id"), total_difference=Sum("difference_amount"))
        .order_by("exception_type", "status")
    )
    _audit_analytics_view(request, "view_finance_analytics_exceptions")
    return success_response({"exceptions": rows, "read_only": True, "account_details": "***"})
