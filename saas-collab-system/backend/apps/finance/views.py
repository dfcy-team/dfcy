from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsFinanceImporter, IsFinanceReconciler, IsFinanceUser, IsFinanceViewer
from apps.permissions.ui_p6_scopes import filter_finance_queryset
from .models import BankReceiptImport, FinanceAuditLog, PlatformStatement, ReconciliationException, ReconciliationMatch, WithdrawalRecord
from .serializers import (
    BankReceiptImportSerializer,
    FinanceAnalyticsQuerySerializer,
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


def _analytics_query(request, *, allow_status=False):
    if not allow_status and "status" in request.query_params:
        raise ValidationError({"status": "Unknown query parameter."})
    serializer = FinanceAnalyticsQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _filter_period(queryset, query, prefix=""):
    if query.get("period_start"):
        queryset = queryset.filter(**{f"{prefix}period_end__gte": query["period_start"]})
    if query.get("period_end"):
        queryset = queryset.filter(**{f"{prefix}period_start__lte": query["period_end"]})
    if query.get("platform"):
        queryset = queryset.filter(**{f"{prefix}platform": query["platform"]})
    if query.get("currency"):
        queryset = queryset.filter(**{f"{prefix}currency": query["currency"]})
    return queryset


def _analytics_payload(request, rows, query, *, sources):
    paginator = Paginator(rows, query["page_size"])
    if query["page"] > paginator.num_pages:
        raise NotFound("Requested page does not exist.")
    page_obj = paginator.page(query["page"])

    def page_url(number):
        if number is None:
            return None
        params = request.query_params.copy()
        params["page"] = number
        params["page_size"] = query["page_size"]
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    return {
        "count": paginator.count,
        "next": page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "previous": page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "results": list(page_obj.object_list),
        "api_status": "connected",
        "quality": {
            "status": "passed" if paginator.count else "unknown",
            "score": 100 if paginator.count else None,
            "metric_version": "finance-analytics-v1",
            "refreshed_at": None,
            "missing_fields": [],
            "source_summary": sources,
        },
        "read_only": True,
        "fund_action_available": False,
    }


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def finance_analytics_overview(request):
    query = _analytics_query(request)
    statements = filter_finance_queryset(
        request.user,
        PlatformStatement.objects.filter(tenant=request.user.tenant),
        "finance.view",
    )
    statements = _filter_period(statements, query)
    receipt_totals = {
        row["bank_receipt__currency"]: row["receipt_amount"] or 0
        for row in ReconciliationMatch.objects.filter(tenant=request.user.tenant, statement__in=statements)
        .values("bank_receipt__currency")
        .annotate(receipt_amount=Sum("bank_receipt__receipt_amount"))
    }
    rows = list(
        statements.values("period_start", "period_end", "platform", "currency")
        .annotate(
            statement_amount=Sum("gross_amount"),
            exception_count=Count("reconciliation_matches__exceptions", distinct=True),
        )
        .order_by("-period_end", "platform", "currency")
    )
    for row in rows:
        row["receipt_amount"] = receipt_totals.get(row["currency"], 0)
        row["difference_amount"] = row["statement_amount"] - row["receipt_amount"]
        row["account_mask"] = "***"
        row["quality_status"] = "passed"
    _audit_analytics_view(request, "view_finance_analytics_overview")
    payload = _analytics_payload(request, rows, query, sources=["platform_statements", "bank_receipts"])
    payload["metrics"] = []
    payload["trend"] = []
    return success_response(payload)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def finance_analytics_reconciliation(request):
    query = _analytics_query(request, allow_status=True)
    matches = filter_finance_queryset(
        request.user,
        ReconciliationMatch.objects.filter(tenant=request.user.tenant),
        "finance.view",
        platform_field="statement__platform",
        currency_field="statement__currency",
    )
    matches = _filter_period(matches, query, prefix="statement__")
    if query.get("status"):
        matches = matches.filter(status=query["status"])
    rows = list(
        matches.values("status", "statement__currency")
        .annotate(match_count=Count("id"), matched_amount=Sum("matched_amount"), total_difference=Sum("difference_amount"))
        .order_by("status", "statement__currency")
    )
    for row in rows:
        row["currency"] = row.pop("statement__currency")
        row["quality_status"] = "passed"
    _audit_analytics_view(request, "view_finance_analytics_reconciliation")
    return success_response(_analytics_payload(request, rows, query, sources=["reconciliation_matches"]))


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def finance_analytics_exceptions(request):
    query = _analytics_query(request, allow_status=True)
    exceptions = filter_finance_queryset(
        request.user,
        ReconciliationException.objects.filter(tenant=request.user.tenant),
        "finance.view",
        platform_field="reconciliation_match__statement__platform",
        currency_field="reconciliation_match__statement__currency",
    )
    exceptions = _filter_period(exceptions, query, prefix="reconciliation_match__statement__")
    if query.get("status"):
        exceptions = exceptions.filter(status=query["status"])
    rows = list(
        exceptions.values("exception_type", "status", "reconciliation_match__statement__currency")
        .annotate(exception_count=Count("id"), total_difference=Sum("difference_amount"))
        .order_by("exception_type", "status", "reconciliation_match__statement__currency")
    )
    for row in rows:
        row["currency"] = row.pop("reconciliation_match__statement__currency")
        row["quality_status"] = "passed"
    _audit_analytics_view(request, "view_finance_analytics_exceptions")
    return success_response(_analytics_payload(request, rows, query, sources=["reconciliation_exceptions"]))
