from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Count, F, Sum
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import BasePermission

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsFinanceExceptionHandler, IsFinanceImporter, IsFinanceReconciler, IsFinanceUser, IsFinanceViewer
from apps.permissions.ui_p6_scopes import filter_finance_queryset, finance_values_allowed
from .models import BankReceiptImport, FinanceAuditLog, LazadaFinanceWide, PlatformFinanceTransaction, PlatformStatement, ReconciliationException, ReconciliationMatch, WithdrawalRecord
from .serializers import (
    BankReceiptImportSerializer,
    FinanceAnalyticsQuerySerializer,
    FinanceTransactionQuerySerializer,
    FinanceLegacyListQuerySerializer,
    LazadaFinanceWideQuerySerializer,
    LazadaFinanceWideSerializer,
    PlatformFinanceTransactionSerializer,
    PlatformStatementSerializer,
    ReconciliationExceptionSerializer,
    ReconciliationMatchSerializer,
    ReconciliationMatchDetailSerializer,
    ManualReconciliationMatchSerializer,
    ReconciliationExceptionResolveSerializer,
    WithdrawalRecordSerializer,
)
from .services import (
    confirm_match,
    create_manual_match,
    import_demo_bank_receipt,
    import_demo_statement,
    import_demo_withdrawal,
    reject_match,
    run_mock_reconciliation,
    resolve_exception,
    write_finance_audit_log,
)


@api_view(["GET"])
@permission_classes([IsFinanceUser])
def health(request):
    return success_response({"status": "ok", "service": "finance"})


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def statement_collection(request):
    query = _legacy_list_query(request, PlatformStatement)
    queryset = filter_finance_queryset(
        request.user, PlatformStatement.objects.filter(tenant=request.user.tenant), "finance.view"
    )
    queryset = _apply_legacy_filters(queryset, query)
    return success_response(PlatformStatementSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def finance_transaction_collection(request):
    serializer = FinanceTransactionQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = filter_finance_queryset(request.user, PlatformFinanceTransaction.objects.filter(tenant=request.user.tenant), "finance.view").select_related("store")
    for field in ("platform", "store_id", "currency", "fee_category", "match_status", "external_order_id"):
        if query.get(field) not in (None, ""):
            queryset = queryset.filter(**{field: query[field]})
    if query.get("platforms"):
        queryset = queryset.filter(platform__in=query["platforms"])
    if query.get("store_ids"):
        queryset = queryset.filter(store_id__in=query["store_ids"])
    if query.get("raw_fee_name"):
        queryset = queryset.filter(raw_fee_name=query["raw_fee_name"])
    if query.get("period_start"):
        queryset = queryset.filter(business_date__gte=query["period_start"])
    if query.get("period_end"):
        queryset = queryset.filter(business_date__lte=query["period_end"])
    queryset = queryset.order_by("-occurred_at_utc", "-id")
    paginator = Paginator(queryset, query["page_size"])
    page = paginator.get_page(query["page"])
    return success_response(
        {
            "items": PlatformFinanceTransactionSerializer(page.object_list, many=True).data,
            "pagination": {
                "page": page.number,
                "page_size": query["page_size"],
                "total": paginator.count,
                "pages": paginator.num_pages,
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def lazada_finance_wide_collection(request):
    serializer = LazadaFinanceWideQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = filter_finance_queryset(request.user, LazadaFinanceWide.objects.filter(tenant=request.user.tenant), "finance.view", platform_field="store__platform__platform_type").select_related("store")
    for field in ("store_id", "currency", "external_order_id", "seller_sku"):
        if query.get(field) not in (None, ""):
            queryset = queryset.filter(**{field: query[field]})
    if query.get("period_start"):
        queryset = queryset.filter(transaction_date__gte=query["period_start"])
    if query.get("period_end"):
        queryset = queryset.filter(transaction_date__lte=query["period_end"])
    paginator = Paginator(queryset, query["page_size"])
    page = paginator.get_page(query["page"])
    return success_response({
        "items": LazadaFinanceWideSerializer(page.object_list, many=True).data,
        "pagination": {
            "page": page.number,
            "page_size": query["page_size"],
            "total": paginator.count,
            "pages": paginator.num_pages,
        },
    })


@api_view(["POST"])
@permission_classes([IsFinanceImporter])
def import_demo_statement_view(request):
    statement = import_demo_statement(request.user.tenant)
    write_finance_audit_log(request.user.tenant, request.user, "import_demo_statement", statement)
    return success_response(PlatformStatementSerializer(statement).data, status=201)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def withdrawal_collection(request):
    query = _legacy_list_query(request, WithdrawalRecord)
    queryset = filter_finance_queryset(
        request.user, WithdrawalRecord.objects.filter(tenant=request.user.tenant), "finance.view"
    )
    queryset = _apply_legacy_filters(queryset, query)
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
    query = _legacy_list_query(request, BankReceiptImport, allow_platform=False)
    queryset = BankReceiptImport.objects.filter(tenant=request.user.tenant)
    allowed_currencies = [currency for currency in queryset.values_list("currency", flat=True).distinct()
                          if finance_values_allowed(request.user, "finance.view", platform="", currency=currency)]
    queryset = queryset.filter(currency__in=allowed_currencies)
    queryset = _apply_legacy_filters(queryset, query)
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


class IsFinanceMatchCollectionUser(BasePermission):
    def has_permission(self, request, view):
        permission = IsFinanceViewer if request.method == "GET" else IsFinanceReconciler
        return permission().has_permission(request, view)


@api_view(["GET", "POST"])
@permission_classes([IsFinanceMatchCollectionUser])
def reconciliation_match_collection(request):
    if request.method == "POST":
        serializer = ManualReconciliationMatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        match = create_manual_match(request.user.tenant, request.user, **{
            "statement_id": serializer.validated_data["statement_id"],
            "withdrawal_id": serializer.validated_data["withdrawal_id"],
            "receipt_id": serializer.validated_data["bank_receipt_id"],
        })
        return success_response(ReconciliationMatchSerializer(match).data, status=201)
    query = _legacy_list_query(request, ReconciliationMatch)
    queryset = ReconciliationMatch.objects.filter(
        tenant=request.user.tenant,
        statement__tenant=request.user.tenant,
        withdrawal__tenant=request.user.tenant,
        bank_receipt__tenant=request.user.tenant,
        withdrawal__platform=F("statement__platform"),
        withdrawal__currency=F("statement__currency"),
        bank_receipt__currency=F("statement__currency"),
    )
    queryset = filter_finance_queryset(
        request.user, queryset, "finance.view",
        platform_field="statement__platform", currency_field="statement__currency",
    )
    queryset = _apply_legacy_filters(queryset, query, platform_field="statement__platform",
                                     currency_field="statement__currency")
    queryset = queryset.filter(bank_receipt__currency__in=_viewable_receipt_currencies(request, queryset))
    return success_response(ReconciliationMatchSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def reconciliation_match_detail(request, pk):
    queryset = ReconciliationMatch.objects.filter(
        tenant=request.user.tenant,
        statement__tenant=request.user.tenant,
        withdrawal__tenant=request.user.tenant,
        bank_receipt__tenant=request.user.tenant,
        withdrawal__platform=F("statement__platform"),
        withdrawal__currency=F("statement__currency"),
        bank_receipt__currency=F("statement__currency"),
    )
    queryset = filter_finance_queryset(
        request.user, queryset, "finance.view",
        platform_field="statement__platform", currency_field="statement__currency",
    )
    match = get_object_or_404(queryset.select_related("statement", "withdrawal", "bank_receipt"), pk=pk)
    if not finance_values_allowed(request.user, "finance.view", platform="", currency=match.bank_receipt.currency):
        raise NotFound()
    return success_response(ReconciliationMatchDetailSerializer(match).data)


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
    match = _scoped_reconciliation_match(request, pk)
    match = confirm_match(match, request.user)
    return success_response(ReconciliationMatchSerializer(match).data)


@api_view(["POST"])
@permission_classes([IsFinanceReconciler])
def reject_reconciliation_match(request, pk):
    match = _scoped_reconciliation_match(request, pk)
    reason = request.data.get("reason", "")
    match = reject_match(match, request.user, reason=reason)
    return success_response(ReconciliationMatchSerializer(match).data)


@api_view(["GET"])
@permission_classes([IsFinanceViewer])
def reconciliation_exception_collection(request):
    query = _legacy_list_query(request, ReconciliationException)
    queryset = ReconciliationException.objects.filter(tenant=request.user.tenant)
    queryset = queryset.filter(
        reconciliation_match__tenant=request.user.tenant,
        reconciliation_match__statement__tenant=request.user.tenant,
        reconciliation_match__withdrawal__tenant=request.user.tenant,
        reconciliation_match__bank_receipt__tenant=request.user.tenant,
        reconciliation_match__withdrawal__platform=F("reconciliation_match__statement__platform"),
        reconciliation_match__withdrawal__currency=F("reconciliation_match__statement__currency"),
    )
    queryset = filter_finance_queryset(
        request.user, queryset, "finance.view",
        platform_field="reconciliation_match__statement__platform",
        currency_field="reconciliation_match__statement__currency",
    )
    queryset = queryset.filter(reconciliation_match__bank_receipt__currency=F("reconciliation_match__statement__currency"))
    queryset = _apply_legacy_filters(
        queryset, query, platform_field="reconciliation_match__statement__platform",
        currency_field="reconciliation_match__statement__currency",
    )
    queryset = queryset.filter(reconciliation_match__bank_receipt__currency__in=_viewable_receipt_currencies(
        request, queryset, currency_field="reconciliation_match__bank_receipt__currency"
    ))
    return success_response(ReconciliationExceptionSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsFinanceExceptionHandler])
def resolve_reconciliation_exception(request, pk):
    serializer = ReconciliationExceptionResolveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    exception = get_object_or_404(ReconciliationException, pk=pk, tenant=request.user.tenant)
    result = resolve_exception(exception, request.user, serializer.validated_data["reason"])
    return success_response(ReconciliationExceptionSerializer(result).data)


def _legacy_list_query(request, model, *, allow_platform=True):
    serializer = FinanceLegacyListQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    if not allow_platform and query.get("platform"):
        raise ValidationError({"platform": "This list has no platform dimension."})
    if query.get("status") and query["status"] not in dict(model.Status.choices):
        raise ValidationError({"status": "Unknown status."})
    return query


def _apply_legacy_filters(queryset, query, *, platform_field="platform", currency_field="currency"):
    if query.get("platform"):
        queryset = queryset.filter(**{platform_field: query["platform"]})
    if query.get("currency"):
        queryset = queryset.filter(**{currency_field: query["currency"]})
    if query.get("status"):
        queryset = queryset.filter(status=query["status"])
    return queryset


def _viewable_receipt_currencies(request, queryset, *, currency_field="bank_receipt__currency"):
    currencies = queryset.values_list(currency_field, flat=True).distinct()
    return [currency for currency in currencies if finance_values_allowed(
        request.user, "finance.view", platform="", currency=currency
    )]


def _scoped_reconciliation_match(request, pk):
    queryset = ReconciliationMatch.objects.filter(
        tenant=request.user.tenant,
        statement__tenant=request.user.tenant,
        withdrawal__tenant=request.user.tenant,
        bank_receipt__tenant=request.user.tenant,
        withdrawal__platform=F("statement__platform"),
        withdrawal__currency=F("statement__currency"),
        bank_receipt__currency=F("statement__currency"),
    )
    queryset = filter_finance_queryset(
        request.user, queryset, "finance.reconcile",
        platform_field="statement__platform", currency_field="statement__currency",
    )
    match = get_object_or_404(queryset.select_related("statement", "withdrawal", "bank_receipt"), pk=pk)
    if not finance_values_allowed(request.user, "finance.reconcile", platform="", currency=match.bank_receipt.currency):
        raise NotFound()
    return match


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
    group_fields = ("period_start", "period_end", "platform", "currency")
    match_groups = tuple("statement__" + field for field in group_fields)
    matches = ReconciliationMatch.objects.filter(
        tenant=request.user.tenant, statement__in=statements,
        withdrawal__tenant=request.user.tenant, bank_receipt__tenant=request.user.tenant,
        status=ReconciliationMatch.Status.CONFIRMED,
        bank_receipt__currency=F("statement__currency"),
    )
    matches = matches.filter(bank_receipt__currency__in=_viewable_receipt_currencies(request, matches))
    receipt_totals = {
        tuple(row[field] for field in match_groups): row["receipt_amount"] or 0
        for row in matches.values(*match_groups).annotate(receipt_amount=Sum("matched_amount"))
    }
    exception_groups = tuple("reconciliation_match__statement__" + field for field in group_fields)
    exception_totals = {
        tuple(row[field] for field in exception_groups): row["exception_count"]
        for row in ReconciliationException.objects.filter(
            tenant=request.user.tenant, reconciliation_match__statement__in=statements,
            status=ReconciliationException.Status.OPEN,
        ).values(*exception_groups).annotate(exception_count=Count("pk"))
    }
    rows = list(
        statements.values("period_start", "period_end", "platform", "currency")
        .annotate(
            statement_amount=Sum("gross_amount"),
        )
        .order_by("-period_end", "platform", "currency")
    )
    for row in rows:
        group = tuple(row[field] for field in group_fields)
        row["receipt_amount"] = receipt_totals.get(group, 0)
        row["exception_count"] = exception_totals.get(group, 0)
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
