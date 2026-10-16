from io import BytesIO

from django.http import FileResponse
from rest_framework.exceptions import NotFound

from apps.products.models import ProductSKU
from .permissions import internal_orders
from .models import PurchaseOrder
from .supplier_products import product_details
from .supplier_product_images import load_product_images
from .views import InternalAPI
from .services import _order, purchase_snapshot
from .supplier_products import order_product_details
from .permissions import VIEW
from .supplier_products import shipment_line_product_details
from .shipment_api import SupplierAPI


def _image_file(tenant_id, sku_id, details):
    sku = ProductSKU.objects.filter(tenant_id=tenant_id, pk=sku_id).select_related('spu__category_node').first()
    if sku is None:
        raise NotFound("商品不可访问。")
    if details is None:
        details = product_details(sku)
    image = load_product_images({'lines': [{'sku_id': sku.pk, 'product_details': details}]}, tenant_id).get(sku.pk, {})
    if not image.get('body'):
        raise NotFound("商品图片尚未维护或暂不可用。")
    response = FileResponse(BytesIO(image['body']), content_type='image/jpeg')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _shipment_sku_image(shipment, sku_id):
    line = shipment.lines.filter(sku_id=sku_id).select_related('shipment__order').order_by('-is_active', 'pk').first()
    if line is None:
        raise NotFound("该商品不属于本发货单。")
    return shipment_line_product_details([line]).get(line.pk)


class InternalProductImage(InternalAPI):
    def get(self, request, sku_id):
        internal_orders(request.user, PurchaseOrder.objects.all())
        sku = ProductSKU.objects.filter(tenant_id=request.user.tenant_id, pk=sku_id, is_active=True).select_related("spu__category_node").first()
        if sku is None:
            raise NotFound("商品不可访问。")
        image = load_product_images({"lines": [{"sku_id": sku.pk, "product_details": product_details(sku)}]}, request.user.tenant_id).get(sku.pk, {})
        if not image.get("body"):
            raise NotFound("商品图片尚未维护或暂不可用。")
        response = FileResponse(BytesIO(image["body"]), content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class InternalPurchaseProductImage(InternalAPI):
    def get(self, request, pk, sku_id):
        internal_orders(request.user, PurchaseOrder.objects.all())
        order = _order(request.user, pk, VIEW)
        snapshot = order_product_details(order, purchase_snapshot(order))
        snapshot["lines"] = [line for line in snapshot["lines"] if line["sku_id"] == sku_id]
        if not snapshot["lines"]:
            raise NotFound("该商品不属于本采购订单。")
        image = load_product_images(snapshot, request.user.tenant_id).get(sku_id, {})
        if not image.get("body"):
            raise NotFound("商品图片尚未维护或暂不可用。")
        response = FileResponse(BytesIO(image["body"]), content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class InternalShipmentProductImage(InternalAPI):
    def get(self, request, pk, sku_id):
        from .shipments import shipment_for
        shipment = shipment_for(request.user, pk, VIEW)
        return _image_file(request.user.tenant_id, sku_id, _shipment_sku_image(shipment, sku_id))


class SupplierShipmentProductImage(SupplierAPI):
    def get(self, request, pk, sku_id):
        from .shipments import shipment_for
        shipment = shipment_for(request.user, pk, VIEW)
        return _image_file(request.user.tenant_id, sku_id, _shipment_sku_image(shipment, sku_id))


class InternalBatchProductImage(InternalAPI):
    def get(self, request, pk, sku_id):
        from .logistics import batch_for
        batch = batch_for(request.user, pk, VIEW)
        line = batch.memberships.filter(active_guard=True, allocations__shipment_line__sku_id=sku_id).values_list('allocations__shipment_line_id', flat=True).first()
        if line is None:
            raise NotFound("该商品不属于本集货批次。")
        from .models import ShipmentLine
        source = ShipmentLine.objects.filter(pk=line).select_related('shipment__order').first()
        return _image_file(request.user.tenant_id, sku_id, shipment_line_product_details([source]).get(source.pk))


class InternalInboundProductImage(InternalAPI):
    def get(self, request, pk, sku_id):
        from .logistics import inbound_for
        inbound = inbound_for(request.user, pk, VIEW)
        source = inbound.lines.filter(shipment_line__sku_id=sku_id).values_list('shipment_line_id', flat=True).first()
        if source is None:
            raise NotFound("该商品不属于本入库单。")
        from .models import ShipmentLine
        line = ShipmentLine.objects.filter(pk=source).select_related('shipment__order').first()
        return _image_file(request.user.tenant_id, sku_id, shipment_line_product_details([line]).get(line.pk))
