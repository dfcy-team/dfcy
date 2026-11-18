"""Authenticated, tenant-wide read-only arrival information for notification recipients."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import InboundOrder
from .views import ReadAPI


def _confirmed_inbound(request, pk):
    if not request.user.is_active or not request.user.tenant_id:
        raise PermissionDenied('账户不可用。')
    return get_object_or_404(
        InboundOrder.objects.select_related('batch', 'warehouse'),
        pk=pk, tenant_id=request.user.tenant_id, status=InboundOrder.Status.CONFIRMED,
    )


def _image_path(inbound, item, kind):
    sku_id = item['image_sku_id']
    return f'/api/internal/supply-chain/v2/inbound-notices/{inbound.pk}/{kind}/{sku_id}/image/' if sku_id else ''


class InboundNoticeDetail(ReadAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request, pk):
        inbound = _confirmed_inbound(request, pk)
        from .inbound_notifications import notice_detail_data
        detail = notice_detail_data(inbound)
        header, summary = detail['inbound'], detail['summary']
        response = Response({'data': {
            'number': header['number'], 'batch_number': header['batch_number'],
            'country_label': header['country_name'], 'warehouse_name': header['warehouse_name'],
            'confirmed_at': header['confirmed_at'],
            'expected_quantity': summary['expected_quantity'],
            'received_quantity': summary['received_quantity'],
            'difference': summary['difference_quantity'],
            'items': [{'image_path': _image_path(inbound, item, 'arrival'), **{key: item[key] for key in (
                'product_name', 'sku_code', 'legacy_sku_code', 'expected_quantity',
                'received_quantity', 'difference', 'is_extra',
            )}} for item in detail['lines']],
            'transit_styles': [{'image_path': _image_path(inbound, item, 'transit'), **{key: item[key] for key in (
                'product_name', 'spu_code', 'legacy_spu_code',
            )}} for item in detail['transit_styles']],
            'preview_as_of': detail['preview_as_of'],
        }})
        response['Cache-Control'] = 'private, no-store'
        return response


class InboundNoticeImage(ReadAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request, pk, kind, sku_id):
        from rest_framework.exceptions import NotFound
        from apps.products.models import ProductSKU
        from .inbound_notifications import _transit_styles, _transit_images
        from .internal_product_images import _image_file

        inbound = _confirmed_inbound(request, pk)
        if kind == 'arrival':
            allowed = (inbound.lines.filter(shipment_line__sku_id=sku_id).exists()
                       or inbound.extra_lines.filter(is_active=True, sku_id=sku_id).exists())
        elif kind == 'transit':
            sku = get_object_or_404(ProductSKU, pk=sku_id, tenant_id=inbound.tenant_id)
            rows, _ = _transit_styles(inbound, spu_id=sku.spu_id)
            allowed = bool(rows) and _transit_images(inbound, [sku.spu_id]).get(sku.spu_id) == sku_id
        else:
            allowed = False
        if not allowed:
            raise NotFound('商品图片不可访问。')
        return _image_file(inbound.tenant_id, sku_id, None)
