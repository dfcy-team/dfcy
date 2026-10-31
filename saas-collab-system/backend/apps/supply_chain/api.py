from io import BytesIO
from datetime import date
import re

from django.db import transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.db.models import Prefetch, Q
from django.http import FileResponse
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.audit.services import write_operation_log
from apps.common.exceptions import StateConflict
from apps.masterdata.models import CountrySiteMaster, WarehouseMaster
from apps.products.models import ProductSKU
from .archives import allowed_suppliers, authorize_archive_supplier, freight_data, freight_scope, price_data, save_freight, save_price, save_supplier, supplier_data
from .documents import import_template, purchase_workbook, sku_labels
from .imports import MAX_FILE_BYTES, commit_import, create_import, import_data
from .models import BusinessEvent, PurchaseImport, PurchaseOrder, Record, SupplierProductPrice
from .permissions import MANAGE, VIEW, accessible_orders, internal_orders
from .serializers import FreightInput, MetadataInput, PriceInput, PurchaseInput, PurchaseEditInput, SupplierInput, VersionInput
from .services import _order, cancel_purchase_draft, confirm_purchase_order, create_purchase_order, purchase_snapshot, update_purchase_metadata, update_purchase_order
from .views import InternalAPI, ReadAPI, _page


def key(request):
    value = request.headers.get("Idempotency-Key", "")
    if not value.strip() or len(value) > 128:
        raise ValidationError("请求须提供 Idempotency-Key（最多 128 字符）。")
    return value


def validated(serializer, request):
    value = serializer(data=request.data)
    value.is_valid(raise_exception=True)
    return value.validated_data


def purchase_queryset(request, *, apply_workflow=True):
    query = internal_orders(request.user, PurchaseOrder.objects.all()).select_related("supplier", "country").prefetch_related(Prefetch("lines", queryset=PurchaseOrder._meta.get_field("lines").related_model.objects.filter(is_active=True), to_attr="_read_purchase_lines"))
    term = request.query_params.get("search", "").strip()
    if term:
        query = query.filter(Q(number__icontains=term) | Q(reference_number__icontains=term) | Q(supplier__name__icontains=term))
    for field in ("status", "source_kind"):
        if request.query_params.get(field):
            query = query.filter(**{field: request.query_params[field]})
    country = request.query_params.get('country_code', '').strip()
    if country:
        query = query.filter(country_code_snapshot__iexact=country)
    supplier_id = request.query_params.get('supplier_id', '').strip()
    if supplier_id:
        if not re.fullmatch(r"[0-9]+", supplier_id) or int(supplier_id) < 1:
            raise ValidationError("供应商筛选参数须为正整数。")
        query = query.filter(supplier_id=int(supplier_id))
    date_from = _purchase_filter_date(request.query_params.get('order_date_from', ''), 'order_date_from')
    date_to = _purchase_filter_date(request.query_params.get('order_date_to', ''), 'order_date_to')
    if date_from and date_to and date_from > date_to:
        raise ValidationError("下单开始日期不能晚于结束日期。")
    if date_from:
        query = query.filter(order_date__gte=date_from)
    if date_to:
        query = query.filter(order_date__lte=date_to)
    if apply_workflow:
        from .fulfillment import filter_orders
        return filter_orders(query, request.query_params.get('workflow', ''))
    return query


def _purchase_filter_date(value, field):
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} 日期格式须为 YYYY-MM-DD。")
    if parsed.isoformat() != value:
        raise ValidationError(f"{field} 日期格式须为 YYYY-MM-DD。")
    return parsed


def internal_purchase_data(obj):
    from .supplier_products import order_product_details
    data = order_product_details(obj, purchase_snapshot(obj))
    from .notification_config import public_base
    from django.core.exceptions import ValidationError as ConfigValidationError
    try:
        data['supplier_url'] = public_base() + f'/supplier/orders/{obj.pk}'
    except ConfigValidationError:
        data['supplier_url'] = ''

    legacy_codes = dict(ProductSKU.objects.filter(tenant_id=obj.tenant_id,
        pk__in=[line["sku_id"] for line in data["lines"]]).values_list("pk", "legacy_sku_code"))
    for line in data["lines"]:
        line["legacy_sku_code"] = legacy_codes.get(line["sku_id"], "")
        line["image_preview_url"] = f'/api/internal/supply-chain/v2/purchase-orders/{obj.pk}/skus/{line["sku_id"]}/image/'
        line["label_pdf_url"] = f'/api/internal/supply-chain/v2/purchase-orders/{obj.pk}/skus/{line["sku_id"]}/labels/'
    from .fulfillment import enrich_order
    return enrich_order(obj, data, related=True)


def create_purchase_response(request):
    obj = create_purchase_order(request.user, validated(PurchaseInput, request), idempotency_key=key(request))
    return Response({"data": internal_purchase_data(obj)}, status=201)


class PurchaseDetail(InternalAPI):
    def get(self, request, pk):
        internal_orders(request.user, PurchaseOrder.objects.all())
        obj = _order(request.user, pk, VIEW)
        data = internal_purchase_data(obj)
        data["history"] = list(BusinessEvent.objects.filter(tenant=request.user.tenant, aggregate_type="purchaseorder", aggregate_id=pk).order_by("id").values("id", "action", "aggregate_version", "created_at"))
        return Response({"data": data})

    def patch(self, request, pk):
        version = validated(VersionInput, request)["expected_version"]
        obj = update_purchase_order(request.user, pk, validated(PurchaseEditInput, request), expected_version=version, idempotency_key=key(request))
        return Response({"data": internal_purchase_data(obj)})


class PurchaseAction(InternalAPI):
    cancel = False

    def post(self, request, pk):
        version = validated(VersionInput, request)["expected_version"]
        obj = (cancel_purchase_draft if self.cancel else confirm_purchase_order)(request.user, pk, expected_version=version, idempotency_key=key(request))
        data = internal_purchase_data(obj)
        if not self.cancel:
            from .models import NotificationOutbox
            from .notifications import MESSAGES
            notification = NotificationOutbox.objects.get(order=obj)
            data['notification_status'] = notification.status
            data['notification_reason'] = MESSAGES.get(notification.blocked_reason, notification.blocked_reason)
        return Response({"data": data})


class CancelPurchase(PurchaseAction):
    cancel = True


class PurchaseMetadata(InternalAPI):
    def patch(self, request, pk):
        payload = dict(validated(MetadataInput, request))
        version = payload.pop("expected_version")
        obj = update_purchase_metadata(request.user, pk, payload, expected_version=version, idempotency_key=key(request))
        return Response({"data": internal_purchase_data(obj)})


class Suppliers(InternalAPI):
    def get(self, request):
        query = allowed_suppliers(request.user)
        search = request.query_params.get("search", "")
        if search:
            query = query.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return _page(request, query, supplier_data)

    def post(self, request):
        return Response({"data": supplier_data(save_supplier(request.user, validated(SupplierInput, request), idempotency_key=key(request)))}, status=201)


class SupplierDetail(InternalAPI):
    def patch(self, request, pk):
        return Response({"data": supplier_data(save_supplier(request.user, validated(SupplierInput, request), pk=pk, idempotency_key=key(request)))})

    @transaction.atomic
    def delete(self, request, pk):
        supplier = allowed_suppliers(request.user, MANAGE).select_for_update().filter(pk=pk).first()
        if supplier is None:
            raise NotFound("供应商不可访问。")
        authorize_archive_supplier(request.user, supplier.pk)
        for relation in supplier._meta.related_objects:
            if relation.related_model._base_manager.filter(**{relation.field.name: supplier}).exists():
                raise StateConflict("供应商存在关联业务数据，请保留档案并停用。")
        from apps.accounts.models import ExternalUserProfile
        from apps.purchasing.models import PurchaseOrder as LegacyPurchaseOrder
        from apps.suppliers.models import SupplierPerformanceSnapshot, SupplierShipment, SupplierTask

        legacy_references = (
            SupplierShipment.objects.filter(tenant=request.user.tenant, supplier_id=supplier.pk),
            SupplierPerformanceSnapshot.objects.filter(tenant=request.user.tenant, supplier_id=supplier.pk),
            LegacyPurchaseOrder.objects.filter(tenant=request.user.tenant, supplier_id=supplier.pk),
            ExternalUserProfile.objects.filter(tenant=request.user.tenant, supplier_id=supplier.pk),
        )
        if SupplierTask.objects.filter(tenant=request.user.tenant, supplier_id=supplier.pk).exists() or any(
            references.exists() for references in legacy_references
        ):
            raise StateConflict("供应商存在关联业务数据，请保留档案并停用。")
        pk_value = supplier.pk
        before = {"code": supplier.code, "status": supplier.status}
        try:
            supplier.delete()
        except (ProtectedError, RestrictedError) as exc:
            raise StateConflict("供应商存在关联业务数据，请保留档案并停用。") from exc
        write_operation_log(tenant=request.user.tenant, user=request.user, module="supply_chain",
                            action="delete", object_type="suppliermaster", object_id=pk_value,
                            before_data=before)
        return Response({"data": {"id": pk_value, "deleted": True}})


class Freights(InternalAPI):
    def get(self, request):
        query = freight_scope(request.user)
        search = request.query_params.get("search", "")
        if search:
            query = query.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return _page(request, query, freight_data)

    def post(self, request):
        return Response({"data": freight_data(save_freight(request.user, validated(FreightInput, request), idempotency_key=key(request)))}, status=201)


class FreightDetail(InternalAPI):
    def patch(self, request, pk):
        return Response({"data": freight_data(save_freight(request.user, validated(FreightInput, request), pk=pk, idempotency_key=key(request)))})

    @transaction.atomic
    def delete(self, request, pk):
        freight = freight_scope(request.user, MANAGE).select_for_update().filter(pk=pk).first()
        if freight is None:
            raise NotFound("货运公司不可访问。")
        for relation in freight._meta.related_objects:
            if relation.related_model._base_manager.filter(**{relation.field.name: freight}).exists():
                raise StateConflict("货运公司存在关联业务数据，请保留档案并停用。")
        pk_value = freight.pk
        before = {"code": freight.code, "status": "active" if freight.is_active else "inactive"}
        try:
            # Record normally forbids deletion; only this archive endpoint reaches
            # the model implementation after proving every reverse relation empty.
            super(Record, freight).delete()
        except (ProtectedError, RestrictedError) as exc:
            raise StateConflict("货运公司存在关联业务数据，请保留档案并停用。") from exc
        write_operation_log(tenant=request.user.tenant, user=request.user, module="supply_chain",
                            action="delete", object_type="freightcompany", object_id=pk_value,
                            before_data=before)
        return Response({"data": {"id": pk_value, "deleted": True}})


def price_queryset(user):
    return SupplierProductPrice.objects.filter(tenant=user.tenant, supplier__in=allowed_suppliers(user)).select_related("sku", "supplier")


class Prices(InternalAPI):
    def get(self, request):
        query = price_queryset(request.user)
        supplier_id = request.query_params.get("supplier_id")
        if supplier_id:
            if not str(supplier_id).isdigit():
                raise ValidationError("供应商编号无效。")
            query = query.filter(supplier_id=supplier_id)
        search = request.query_params.get("search", "")
        if search:
            query = query.filter(Q(sku__sku_code__icontains=search) | Q(sku__product_name__icontains=search))
        return _page(request, query, price_data)

    def post(self, request):
        return Response({"data": price_data(save_price(request.user, validated(PriceInput, request), idempotency_key=key(request)))})


class PriceHistory(InternalAPI):
    def get(self, request, pk):
        obj = price_queryset(request.user).filter(pk=pk).first()
        if obj is None:
            raise NotFound("供应商价格不可访问。")
        return _page(request, obj.history.all(), lambda entry: {
            "id": entry.pk, "unit_price": str(entry.unit_price), "effective_date": entry.effective_date,
            "source_kind": entry.source_kind, "source_order_id": entry.source_order_id,
            "source_order_version": entry.source_order_version, "applied_to_current": entry.applied_to_current,
            "created_at": entry.created_at, "maintained_by": entry.created_by_id, "notes": entry.notes})


class Options(InternalAPI):
    def get(self, request):
        user = request.user
        internal_orders(user, PurchaseOrder.objects.all())
        kind, search = request.query_params.get("kind"), request.query_params.get("search", "")
        if kind == "suppliers":
            query = allowed_suppliers(user).filter(status="active")
            serialize = lambda x: {"id": x.pk, "code": x.code, "name": x.name}
            query = query.filter(Q(code__icontains=search) | Q(name__icontains=search))
        elif kind == "countries":
            query = CountrySiteMaster.objects.filter(tenant=user.tenant, status="active").filter(Q(code__icontains=search) | Q(name__icontains=search))
            serialize = lambda x: {"id": x.pk, "code": x.code, "name": x.name, "country_code": x.country_code}
        elif kind == "warehouses":
            country = request.query_params.get("country_code", "")
            if not country:
                raise ValidationError("请先选择国家。")
            from .warehouse_archives import warehouse_refs
            query = warehouse_refs(user).filter(status="active", country_code__iexact=country).filter(Q(code__icontains=search) | Q(name__icontains=search))
            serialize = lambda x: {"id": x.pk, "code": x.code, "name": x.name, "country_code": x.country_code}
        elif kind == "skus":
            supplier_id = request.query_params.get("supplier_id")
            prices = {}
            if supplier_id:
                supplier = allowed_suppliers(user).filter(pk=supplier_id).first() if str(supplier_id).isdigit() else None
                if supplier is None:
                    raise NotFound("供应商不可访问。")
                prices = {x.sku_id: x for x in SupplierProductPrice.objects.filter(tenant=user.tenant, supplier=supplier)}
            query = ProductSKU.objects.filter(tenant=user.tenant, is_active=True, spu__product_type="standard").select_related("spu__category_node").filter(
                Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search) | Q(product_name__icontains=search))
            from .supplier_products import product_details
            def serialize(x):
                recent = prices.get(x.pk)
                return {"id": x.pk, "sku": x.sku_code, "legacy_sku_code": x.legacy_sku_code, "name": x.product_name,
                        "product_reference_price": str(x.purchase_price) if x.purchase_price is not None else None,
                        "supplier_reference_price": str(recent.unit_price) if recent else None,
                        "supplier_price_version": recent.version if recent else 0,
                        "product_details": product_details(x)}
        else:
            raise ValidationError("可查询供应商、国家、仓库或商品选项。")
        return _page(request, query, serialize)

    def post(self, request):
        """Resolve pasted SKU codes in one bounded, read-only tenant query."""
        user = request.user
        internal_orders(user, PurchaseOrder.objects.all())
        codes = request.data.get("codes")
        if not isinstance(codes, list) or not 1 <= len(codes) <= 500 or any(not isinstance(code, str) or not code.strip() or len(code.strip()) > 160 for code in codes):
            raise ValidationError("codes 须为 1–500 个非空 SKU 编码。")
        supplier_id = request.data.get("supplier_id")
        prices = {}
        if supplier_id:
            if not str(supplier_id).isdigit() or int(supplier_id) < 1:
                raise ValidationError("供应商 ID 须为正整数。")
            supplier = allowed_suppliers(user).filter(pk=int(supplier_id)).first()
            if supplier is None:
                raise NotFound("供应商不可访问。")
            sku_codes = {code.strip() for code in codes}
            price_skus = ProductSKU.objects.filter(tenant=user.tenant, is_active=True, spu__product_type="standard").exclude(inventory_type="virtual").filter(
                Q(sku_code__in=sku_codes) | Q(legacy_sku_code__in=sku_codes)).values("id")
            prices = {row.sku_id: row for row in SupplierProductPrice.objects.filter(tenant=user.tenant, supplier=supplier, sku_id__in=price_skus)}
        from apps.products.models import ProductSKU
        from .supplier_products import product_details
        unique_codes = {code.strip() for code in codes}
        query = ProductSKU.objects.filter(tenant=user.tenant, is_active=True, spu__product_type="standard").exclude(inventory_type="virtual").filter(
            Q(sku_code__in=unique_codes) | Q(legacy_sku_code__in=unique_codes)).select_related("spu__category_node")
        by_code = {}
        for sku in query:
            item = {"id": sku.pk, "sku": sku.sku_code, "legacy_sku_code": sku.legacy_sku_code or "", "name": sku.product_name,
                    "product_reference_price": str(sku.purchase_price) if sku.purchase_price is not None else None,
                    "supplier_reference_price": str(prices[sku.pk].unit_price) if sku.pk in prices else None,
                    "product_details": product_details(sku)}
            by_code.setdefault(sku.sku_code, []).append(item)
            if sku.legacy_sku_code:
                by_code.setdefault(sku.legacy_sku_code, []).append(item)
        rows = []
        for index, code in enumerate(codes, 1):
            matches = {item["id"]: item for item in by_code.get(code.strip(), [])}
            rows.append({"row": index, "code": code, "item": next(iter(matches.values())) if len(matches) == 1 else None,
                         "error": "未找到启用的普通商品 SKU" if not matches else "编码匹配到多个 SKU" if len(matches) > 1 else None})
        return Response({"data": rows})


class ImportTemplate(InternalAPI):
    def get(self, request):
        internal_orders(request.user, PurchaseOrder.objects.all())
        return FileResponse(BytesIO(import_template()), as_attachment=True, filename="purchase-import-template.xlsx",
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class Imports(InternalAPI):
    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None or uploaded.size > MAX_FILE_BYTES:
            raise ValidationError("请选择 5MB 以内的 .xlsx 文件。")
        job = create_import(request.user, uploaded.name, uploaded.read(MAX_FILE_BYTES + 1), idempotency_key=key(request))
        return Response({"data": import_data(job)}, status=201)


class ImportDetail(InternalAPI):
    def get(self, request, pk):
        internal_orders(request.user, PurchaseOrder.objects.all(), MANAGE)
        job = PurchaseImport.objects.filter(tenant=request.user.tenant, created_by=request.user, pk=pk).first()
        if job is None:
            raise NotFound("导入任务不可访问。")
        return Response({"data": import_data(job)})


class ImportCommit(InternalAPI):
    def post(self, request, pk):
        version = validated(VersionInput, request)["expected_version"]
        job = commit_import(request.user, pk, expected_version=version, idempotency_key=key(request))
        return Response({"data": import_data(job)})


class PurchaseFile(InternalAPI):
    labels = False
    supplier = False

    def get(self, request, pk, sku_id=None):
        # Separate internal/supplier route classes prevent cross-channel access.
        if self.supplier:
            from .permissions import supplier_orders
            query = supplier_orders(request.user, PurchaseOrder.objects.all())
        else:
            query = internal_orders(request.user, PurchaseOrder.objects.all())
        order = query.filter(pk=pk).first()
        if order is None:
            raise NotFound("采购单不可访问。")
        # Confirmed file packages use the confirmation snapshot even after metadata edits.
        event = BusinessEvent.objects.filter(tenant=request.user.tenant, aggregate_type="purchaseorder", aggregate_id=pk, action="confirmed").first()
        snapshot = event.payload.get("purchase_snapshot") if event else None
        snapshot = snapshot or purchase_snapshot(order)
        if event and sku_id is None:
            from .models import NotificationPart
            from .notification_api import file_response
            import hashlib
            prepared = NotificationPart.objects.filter(outbox__event=event, kind='pdf' if self.labels else 'excel').first()
            if prepared:
                body = bytes(prepared.body)
                if hashlib.sha256(body).hexdigest() != prepared.sha256:
                    raise NotFound('采购附件校验失败。')
                return file_response(prepared, body)
        from .supplier_products import enrich_snapshot
        snapshot = enrich_snapshot(snapshot, request.user.tenant_id)
        if sku_id is not None:
            snapshot['lines'] = [line for line in snapshot['lines'] if line['sku_id'] == sku_id]
            if not snapshot['lines']:
                raise NotFound('该商品不属于本采购订单。')
        if self.labels:
            content = sku_labels(snapshot)
        else:
            from .supplier_product_images import load_product_images
            content = purchase_workbook(snapshot, images=load_product_images(snapshot, request.user.tenant_id))
        ext = "pdf" if self.labels else "xlsx"
        mime = "application/pdf" if self.labels else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        suffix = f'-sku-{sku_id}' if sku_id is not None else ''
        response = FileResponse(BytesIO(content), as_attachment=True, filename=f"purchase-{pk}-v{snapshot['version']}{suffix}.{ext}", content_type=mime)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class PurchaseLabels(PurchaseFile):
    labels = True


class SupplierPurchaseFile(PurchaseFile):
    supplier = True
    permission_classes = ReadAPI.permission_classes


class SupplierPurchaseLabels(SupplierPurchaseFile):
    labels = True
