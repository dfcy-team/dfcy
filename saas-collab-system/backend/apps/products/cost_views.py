from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.db.models import Case, Count, F, IntegerField, Q, Subquery, Value, When, Window
from django.db.models.functions import RowNumber
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.audit.models import DataImportLog
from apps.masterdata.models import StoreMaster, WarehouseMaster, StatusChoices

from .cost_services import (
    append_cost_version,
    confirm_pending_cost_version,
    effective_cost_for,
    execute_system_backfill,
    preview_system_backfill,
)
from .cost_import_services import confirm_cost_import, preview_cost_import
from .models import ProductCostVersion, ProductSKU
from .permissions import IsProductCostApprover, IsProductCostBackfillOperator, IsProductCostManager, IsProductCostViewer
from .serializers import ProductCostVersionSerializer


@api_view(["GET"])
@permission_classes([IsProductCostViewer])
def product_cost_collection(request):
    queryset = ProductCostVersion.objects.filter(tenant=request.user.tenant).select_related("sku__spu", "warehouse", "created_by")
    warehouse_id = request.query_params.get("warehouse_id")
    if warehouse_id:
        warehouse = get_object_or_404(WarehouseMaster, tenant=request.user.tenant, pk=warehouse_id)
        queryset = queryset.filter(warehouse=warehouse)
    sku_id = request.query_params.get("sku_id")
    if sku_id:
        queryset = queryset.filter(sku_id=sku_id)
    search = str(request.query_params.get("search") or "").strip()
    if search:
        queryset = queryset.filter(
            Q(sku__sku_code__icontains=search)
            | Q(sku__legacy_sku_code__icontains=search)
            | Q(sku__spu__spu_code__icontains=search)
            | Q(sku__spu__legacy_spu_code__icontains=search)
            | Q(sku__product_name__icontains=search)
            | Q(sku__spu__product_name__icontains=search)
        )
    occurred_at = request.query_params.get("occurred_at")
    if occurred_at and sku_id:
        parsed = parse_datetime(occurred_at)
        if parsed is None:
            raise ValidationError({"occurred_at": "Use an ISO-8601 datetime."})
        sku = get_object_or_404(ProductSKU, tenant=request.user.tenant, pk=sku_id)
        if not warehouse_id:
            raise ValidationError({"warehouse_id": "Select a warehouse for effective cost lookup."})
        store_id = request.query_params.get("store_id")
        if not store_id:
            raise ValidationError({"store_id": "Select a store for effective cost lookup."})
        store = get_object_or_404(StoreMaster, tenant=request.user.tenant, pk=store_id)
        if store.country_code.strip().upper() != warehouse.country_code.strip().upper():
            raise ValidationError({"warehouse_id": "Warehouse country must match store country."})
        item = effective_cost_for(tenant=request.user.tenant, sku=sku, warehouse=warehouse, occurred_at=parsed)
        return success_response(ProductCostVersionSerializer(item).data if item else None)
    if request.query_params.get("view") == "current":
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 50))))
        except (ValueError, TypeError) as exc:
            raise ValidationError({"page": "Use positive integer page and page_size values."}) from exc
        open_first = Case(When(effective_to__isnull=True, then=Value(0)), default=Value(1), output_field=IntegerField())
        current_ids = queryset.order_by().annotate(
            cost_rank=Window(
                expression=RowNumber(),
                partition_by=[F("sku_id"), F("warehouse_id")],
                order_by=[open_first.asc(), F("version_no").desc(), F("pk").desc()],
            )
        ).filter(cost_rank=1).values("pk")
        current = ProductCostVersion.objects.filter(pk__in=Subquery(current_ids)).select_related(
            "sku__spu", "warehouse", "created_by"
        )
        status = request.query_params.get("status")
        difference = Q(status=ProductCostVersion.Status.CONFIRMED, system_cost__isnull=False) & ~Q(confirmed_cost=F("system_cost"))
        if status == "difference":
            current = current.filter(difference)
        elif status in (ProductCostVersion.Status.PENDING, ProductCostVersion.Status.CONFIRMED):
            current = current.filter(status=status)
        elif status:
            raise ValidationError({"status": "Use pending, difference, or confirmed."})
        totals = current.aggregate(
            total=Count("pk"),
            pending=Count("pk", filter=Q(status=ProductCostVersion.Status.PENDING)),
            difference=Count("pk", filter=difference),
            confirmed=Count("pk", filter=Q(status=ProductCostVersion.Status.CONFIRMED)),
        )
        start = (page - 1) * page_size
        items = current.order_by("sku_id", "warehouse_id", "pk")[start:start + page_size]
        item_data = ProductCostVersionSerializer(items, many=True).data
        # Project supply-chain estimates only for this page. Reuse its scoped
        # ledger query and batch serializer so supplier visibility and tenant
        # boundaries remain enforced.
        from apps.supply_chain import cost_ledger
        page_rows = list(items)
        country_by_warehouse = {item.warehouse_id: (item.warehouse.country_code or "").strip().upper()
                                for item in page_rows if item.warehouse_id and item.warehouse}
        sku_ids = {item.sku_id for item in page_rows}
        pairs = {(item.sku_id, country_by_warehouse.get(item.warehouse_id, ""))
                 for item in page_rows if item.warehouse_id}
        country_codes = {country for _, country in pairs if country}
        source_rows = []
        if pairs:
            from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
            try:
                candidates = cost_ledger.entries_for(request.user).filter(
                    shipment_line__sku_id__in=sku_ids,
                    shipment_line__shipment__order__country_code_snapshot__in=country_codes,
                    cost_version__state="estimated",
                ).annotate(provisional_rank=Window(
                    expression=RowNumber(),
                    partition_by=[F("shipment_line__sku_id"), F("shipment_line__shipment__order__country_code_snapshot")],
                    order_by=[F("cost_version__created_at").desc(), F("cost_version_id").desc(), F("pk").desc()],
                )).filter(provisional_rank=1)
                source_rows = cost_ledger.serialize_many(candidates, {})
            except DRFPermissionDenied:
                # Product-cost permission does not grant supplier prices.
                source_rows = []
        provisional = {}
        for source in source_rows:
            pair = (source["sku_id"], (source["country_code"] or "").strip().upper())
            if pair not in pairs or not source["is_latest"]:
                continue
            # The newest current source owns the answer even when it is stale
            # or lacks a usable unit price; do not silently fall back in time.
            if pair in provisional:
                continue
            amount_field = "received_unit_cost" if source["stage"] == "received" else "shipped_unit_cost"
            amount = source.get(amount_field)
            provisional.setdefault(pair, {
                "price": amount if source["status"] != "recalculation_required" else None,
                "status": source["status"],
                "stage": source["stage"], "created_at": source["created_at"],
                "number": source["batch_number"] or source["shipment_number"],
            })
        for row in item_data:
            country_code = (row.get("warehouse_country_code") or "").strip().upper()
            estimate = provisional.get((row["sku"], country_code))
            row["provisional_cost_price"] = estimate["price"] if estimate and estimate["price"] is not None else None
            row["provisional_cost_status"] = estimate["status"] if estimate else None
            row["provisional_cost_stage"] = estimate["stage"] if estimate else None
            row["provisional_cost_source_time"] = estimate["created_at"] if estimate else None
            row["provisional_cost_source_number"] = estimate["number"] if estimate else None
            row["provisional_cost_currency"] = "供应链金额（币种未记录）" if estimate and estimate["price"] is not None else ""
        return success_response({
            "items": item_data,
            "total": totals["total"], "page": page, "page_size": page_size,
            "summary": totals,
        })
    return success_response(ProductCostVersionSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsProductCostViewer])
def product_cost_warehouses(request):
    warehouses = WarehouseMaster.objects.filter(
        tenant=request.user.tenant, status=StatusChoices.ACTIVE,
    ).order_by("country_code", "code").values("id", "code", "name", "country_code")
    return success_response(list(warehouses))


def _warehouse_for_request(request):
    warehouse_id = request.data.get("warehouse_id") or request.data.get("warehouse")
    if not warehouse_id:
        raise ValidationError({"warehouse_id": "Select a warehouse."})
    try:
        return WarehouseMaster.objects.get(pk=warehouse_id, tenant=request.user.tenant, status=StatusChoices.ACTIVE)
    except (WarehouseMaster.DoesNotExist, ValueError, TypeError) as exc:
        raise ValidationError({"warehouse_id": "Select an active warehouse in this tenant."}) from exc


@api_view(["POST"])
@permission_classes([IsProductCostManager])
def product_cost_create(request):
    serializer = ProductCostVersionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if not serializer.validated_data.get("warehouse"):
        raise ValidationError({"warehouse": "Select a warehouse."})
    if serializer.validated_data.get("status", ProductCostVersion.Status.PENDING) == ProductCostVersion.Status.CONFIRMED:
        if not IsProductCostApprover().has_permission(request, None):
            raise PermissionDenied("products.cost.approve permission is required to confirm a version.")
    sku = get_object_or_404(ProductSKU, tenant=request.user.tenant, pk=serializer.validated_data.pop("sku").pk)
    warehouse = _warehouse_for_request(request)
    serializer.validated_data["warehouse"] = warehouse
    try:
        item = append_cost_version(
            tenant=request.user.tenant, sku=sku, actor=request.user, **serializer.validated_data
        )
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
    return success_response(ProductCostVersionSerializer(item).data, status=201)


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_backfill_preview(request):
    warehouse = _warehouse_for_request(request)
    sku_ids = request.data.get("sku_ids") or []
    if not isinstance(sku_ids, list):
        raise ValidationError({"sku_ids": "Must be a list."})
    return success_response({"dry_run": True, "results": preview_system_backfill(tenant=request.user.tenant, warehouse=warehouse, sku_ids=sku_ids)})


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_backfill_execute(request):
    warehouse = _warehouse_for_request(request)
    sku_ids = request.data.get("sku_ids") or []
    if not isinstance(sku_ids, list):
        raise ValidationError({"sku_ids": "Must be a list."})
    effective_from = parse_datetime(str(request.data.get("effective_from") or ""))
    if effective_from is None:
        raise ValidationError({"effective_from": "Use an ISO-8601 datetime."})
    return success_response(execute_system_backfill(
        tenant=request.user.tenant,
        warehouse=warehouse,
        actor=request.user,
        effective_from=effective_from,
        sku_ids=sku_ids,
        reason=str(request.data.get("reason") or "System cost backfill"),
    ), status=201)


@api_view(["POST"])
@permission_classes([IsProductCostApprover])
def product_cost_confirm(request, pk):
    try:
        item = confirm_pending_cost_version(
            tenant=request.user.tenant,
            version_id=pk,
            actor=request.user,
            confirmed_cost=request.data.get("confirmed_cost"),
            reason=str(request.data.get("reason") or ""),
        )
    except ProductCostVersion.DoesNotExist as exc:
        raise ValidationError({"id": "Pending cost version was not found."}) from exc
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
    return success_response(ProductCostVersionSerializer(item).data)


def _uploaded_cost_file(request):
    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": "A CSV or XLSX file is required."})
    if not upload.name.lower().endswith((".csv", ".xlsx")):
        raise ValidationError({"file": "Only CSV and XLSX files are supported."})
    raw = upload.read()
    if not raw:
        raise ValidationError({"file": "The import file is empty."})
    return raw, upload.name


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_import_preview(request):
    raw, filename = _uploaded_cost_file(request)
    result = preview_cost_import(tenant=request.user.tenant, raw=raw, filename=filename)
    if result["errors"]:
        log = DataImportLog.objects.create(
            tenant=request.user.tenant,
            import_type="product_cost_preview",
            file_name=filename[:255],
            status=DataImportLog.Status.FAILED,
            total_count=result["total"],
            success_count=result["valid"],
            failed_count=len({item.get("row") for item in result["errors"] if item.get("row")}),
            error_summary={"digest": result["digest"], "errors": result["errors"],
                           "source_headers": result["source_headers"], "error_rows": result["error_rows"], "stage": "preview"},
            created_by=request.user,
            finished_at=timezone.now(),
        )
        result["error_batch_id"] = log.pk
    return success_response(result)


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_import_confirm(request):
    if not IsProductCostApprover().has_permission(request, None):
        raise PermissionDenied("products.cost.approve permission is required to confirm an import.")
    raw, filename = _uploaded_cost_file(request)
    result = confirm_cost_import(
        tenant=request.user.tenant,
        actor=request.user,
        raw=raw,
        filename=filename,
        token=request.data.get("token", ""),
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    return success_response(result, status=201)
