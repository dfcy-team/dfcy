import hashlib
from io import BytesIO
from django.utils import timezone
from django.http import FileResponse
from rest_framework.exceptions import NotFound, PermissionDenied
from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import serializers
from apps.accounts.external_auth import resolve_supplier_web_binding
from apps.accounts.models import CustomUser
from apps.products.models import ProductSKU
from . import shipments
from .api import key, validated
from .models import BusinessEvent, PurchaseOrder, SupplierShipment
from .permissions import VIEW, internal_orders, supplier_orders
from .serializers import VersionInput
from .services import _order, mark_collection_arrival, purchase_snapshot
from .supplier_products import product_details
from .views import InternalAPI, ReadAPI, _page


class ShipmentRowInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1, required=False)
    sku_id = serializers.IntegerField(min_value=1)
    purchase_line_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0, required=False, allow_null=True)


class ShipmentInput(serializers.Serializer):
    order_id = serializers.IntegerField(min_value=1, required=False)
    expected_version = serializers.IntegerField(min_value=1, required=False)
    shipment_date = serializers.DateField(required=False)
    delivery_mode = serializers.ChoiceField(choices=SupplierShipment.DeliveryMode.choices, required=False)
    loading_address = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    notes = serializers.CharField(max_length=10000, allow_blank=True, required=False)
    lines = ShipmentRowInput(many=True, allow_empty=False, required=False)

    def validate_lines(self, value):
        if len(value) > 500:
            raise serializers.ValidationError("最多 500 行商品。")
        return value


class ShipmentPriceRowInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0, allow_null=True)


class ShipmentPriceInput(VersionInput):
    lines = ShipmentPriceRowInput(many=True, allow_empty=False)
    reason = serializers.CharField(max_length=10000, allow_blank=True, default='')

    def validate_lines(self, value):
        if len(value) > 500:
            raise serializers.ValidationError("最多 500 行商品。")
        return value


def shipment_input(request, *, create=False):
    raw = request.data
    if not isinstance(raw, dict):
        raise ValidationError("发货单内容须为对象。")
    rows = raw.get("lines", [])
    if request.user.user_type == "external" and isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and any(k in row for k in ("unit_price", "purchase_price_snapshot", "supplier_reference_price", "product_reference_price")):
                raise PermissionDenied("供应商不能修改采购价格。")
    value = validated(ShipmentInput, request)
    if create and ("order_id" not in value or "lines" not in value):
        raise ValidationError("请选择采购单并填写商品明细。")
    if not create and "expected_version" not in value:
        raise ValidationError("缺少单据版本，请刷新后重试。")
    return value


class SupplierAPI(ReadAPI):
    permission_classes = ReadAPI.permission_classes

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        resolve_supplier_web_binding(request.user)
        if not request.auth or request.auth.get("channel") != "supplier_web":
            raise PermissionDenied("请使用供应商独立登录入口。")


def supplier_purchase(order, *, with_products=False):
    result = purchase_snapshot(order)
    if with_products:
        from .supplier_products import order_product_details
        result = order_product_details(order, result)
    for row in result["lines"]:
        for field in ("product_reference_price", "supplier_reference_price"):
            row.pop(field, None)
    return result


class SupplierIdentity(SupplierAPI):
    def get(self, request):
        tenant, profile, supplier = resolve_supplier_web_binding(request.user)
        return Response({"data": {"id": request.user.pk, "username": request.user.username,
            "full_name": request.user.full_name, "user_type": "external", "supplier_id": supplier.pk,
            "supplier_name": supplier.name, "tenant_id": tenant.pk, "permissions": []}})


class SupplierOrderList(SupplierAPI):
    def get(self, request):
        query = supplier_orders(request.user, PurchaseOrder.objects.all()).select_related("supplier").prefetch_related("lines")
        return _page(request, query, supplier_purchase)


class SupplierOrderDetail(SupplierAPI):
    def get(self, request, pk):
        return Response({"data": supplier_purchase(_order(request.user, pk, VIEW), with_products=True)})


class SupplierProductImage(SupplierAPI):
    def get(self, request, pk, sku_id):
        from .supplier_products import order_product_details
        from .supplier_product_images import load_product_images
        order = _order(request.user, pk, VIEW)
        snapshot = order_product_details(order, purchase_snapshot(order))
        snapshot['lines'] = [line for line in snapshot['lines'] if line['sku_id'] == sku_id]
        if not snapshot['lines']:
            from rest_framework.exceptions import NotFound
            raise NotFound('该商品不属于本采购订单。')
        image = load_product_images(snapshot, request.user.tenant_id).get(sku_id, {})
        if not image.get('body'):
            from rest_framework.exceptions import NotFound
            raise NotFound('商品图片尚未维护或暂不可用。')
        response = FileResponse(BytesIO(image['body']), content_type='image/jpeg')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class SupplierOptions(SupplierAPI):
    def get(self, request):
        # The active tenant catalog is intentionally offered for extra SKU shipment.
        rows = ProductSKU.objects.filter(tenant=request.user.tenant, is_active=True).select_related('spu__category_node').order_by("sku_code")
        return Response({"data": {"skus": [{"id": row.pk, "sku_code": row.sku_code,
            "legacy_sku_code": row.legacy_sku_code or '', "product_name": row.product_name,
            "product_details": {"image_url": (details := product_details(row))['image_url']},
            "image_preview_url": (f"/api/external/supplier/supply-chain/v2/shipment-options/skus/{row.pk}/image/"
                if details['image_url'] else '')} for row in rows]}})


class SupplierOptionProductImage(SupplierAPI):
    def get(self, request, sku_id):
        from .internal_product_images import _image_file
        sku = ProductSKU.objects.filter(tenant_id=request.user.tenant_id, pk=sku_id,
            is_active=True).select_related('spu__category_node').first()
        if sku is None:
            raise NotFound('商品不可访问。')
        return _image_file(request.user.tenant_id, sku.pk, product_details(sku))


class InternalShipmentOptions(InternalAPI):
    def get(self, request):
        internal_orders(request.user, PurchaseOrder.objects.all())
        rows = ProductSKU.objects.filter(tenant=request.user.tenant, is_active=True).select_related('spu__category_node').order_by("sku_code")
        return Response({"data": {"skus": [{"id": row.pk, "sku_code": row.sku_code,
            "legacy_sku_code": row.legacy_sku_code or '', "product_name": row.product_name,
            "product_details": {"image_url": (details := product_details(row))['image_url']},
            "image_preview_url": (f"/api/internal/supply-chain/v2/options/skus/{row.pk}/image/"
                if details['image_url'] else '')} for row in rows]}})


class ShipmentList(InternalAPI):
    supplier = False

    def data(self, obj):
        return shipments.snapshot(obj, internal=not self.supplier)

    def get(self, request):
        orders = (supplier_orders if self.supplier else internal_orders)(request.user, PurchaseOrder.objects.all())
        rows = SupplierShipment.objects.filter(tenant=request.user.tenant, order__in=orders)
        if request.query_params.get("order_id"):
            if not request.query_params["order_id"].isdigit() or len(request.query_params["order_id"]) > 15:
                raise ValidationError("采购单标识不正确。")
            rows = rows.filter(order_id=request.query_params["order_id"])
        if request.query_params.get("status"):
            rows = rows.filter(status=request.query_params["status"])
        return _page(request, rows.select_related("order__supplier"), self.data)

    def post(self, request):
        return Response({"data": self.data(shipments.create_draft(request.user, shipment_input(request, create=True), key(request)))}, status=201)


class ShipmentDetail(ShipmentList):
    def get(self, request, pk):
        obj = shipments.shipment_for(request.user, pk, VIEW)
        data = self.data(obj)
        data["history"] = list(BusinessEvent.objects.filter(tenant=request.user.tenant,
            aggregate_type="suppliershipment", aggregate_id=pk).order_by("id").values("id", "action", "aggregate_version", "created_at"))
        return Response({"data": data})

    def patch(self, request, pk):
        return Response({"data": self.data(shipments.update_draft(request.user, pk, shipment_input(request), key(request)))})

    def post(self, request, pk):
        raise ValidationError("请选择明确的发货单操作。")


class ShipmentAction(ShipmentList):
    action_name = "submitted"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        value = validated(VersionInput, request)
        return Response({"data": self.data(shipments.action(request.user, pk, value, key(request), self.action_name))})


class ShipmentCancel(ShipmentAction):
    action_name = "cancelled"


class ShipmentPrices(ShipmentDetail):
    http_method_names = ["patch", "options"]

    def patch(self, request, pk):
        return Response({"data": self.data(shipments.prices(request.user, pk, validated(ShipmentPriceInput, request), key(request)))})


class ShipmentArrival(ShipmentAction):
    def post(self, request, pk):
        obj = shipments.shipment_for(request.user, pk)
        if obj.status != "submitted":
            raise ValidationError("只有已提交发货单可标记集货到仓。")
        value = validated(VersionInput, request)
        # Stable input timestamp makes retries share the same event fingerprint.
        from django.utils.dateparse import parse_datetime
        event = BusinessEvent.objects.filter(tenant=request.user.tenant, aggregate_type="suppliershipment",
            aggregate_id=pk, action="collection_arrival", request_key=key(request)).first()
        at = parse_datetime(event.payload["occurred_at"]) if event else timezone.now()
        return Response({"data": self.data(mark_collection_arrival(request.user, pk,
            expected_version=value["expected_version"], occurred_at=at, idempotency_key=key(request)))})


class ShipmentUpload(ShipmentList):
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        value = validated(VersionInput, request)
        return Response({"data": self.data(shipments.upload_box(request.user, pk, request.FILES.get("file"),
            value["expected_version"], key(request)))})


class ShipmentRemove(ShipmentList):
    http_method_names = ["post", "options"]

    def post(self, request, pk, attachment_id):
        value = validated(VersionInput, request)
        return Response({"data": self.data(shipments.remove_box(request.user, pk, attachment_id, value, key(request)))})


class ShipmentDownload(ShipmentList):
    http_method_names = ["get", "options"]

    def get(self, request, pk, attachment_id):
        obj = shipments.shipment_for(request.user, pk, VIEW)
        attachment = obj.box_attachments.filter(pk=attachment_id, content__isnull=False).select_related("file", "content").first()
        if not attachment:
            raise NotFound("箱号附件不存在。")
        body = bytes(attachment.content.body)
        if hashlib.sha256(body).hexdigest() != attachment.sha256:
            raise ValidationError("附件完整性校验失败，请联系采购。")
        response = FileResponse(BytesIO(body), as_attachment=True, filename=attachment.file.file_name,
            content_type=attachment.file.file_type)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-File-SHA256"] = attachment.sha256
        return response


class SupplierShipmentList(SupplierAPI, ShipmentList):
    supplier = True


class SupplierShipmentDetail(SupplierAPI, ShipmentDetail):
    supplier = True


class SupplierShipmentAction(SupplierAPI, ShipmentAction):
    supplier = True


class SupplierShipmentCancel(SupplierAPI, ShipmentCancel):
    supplier = True


class SupplierShipmentUpload(SupplierAPI, ShipmentUpload):
    supplier = True


class SupplierShipmentRemove(SupplierAPI, ShipmentRemove):
    supplier = True


class SupplierShipmentDownload(SupplierAPI, ShipmentDownload):
    supplier = True
