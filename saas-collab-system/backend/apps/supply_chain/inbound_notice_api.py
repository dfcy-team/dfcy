"""Authenticated, tenant-wide read-only arrival information for notification recipients."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import InboundOrder
from .views import ReadAPI


class InboundNoticeDetail(ReadAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request, pk):
        # This deliberately does not require supply-chain menu or data-scope grants.
        # Tenant isolation and active-account authentication still apply.
        if not request.user.is_active or not request.user.tenant_id:
            raise PermissionDenied('账户不可用。')
        inbound = get_object_or_404(
            InboundOrder.objects.select_related('batch', 'warehouse').filter(
                tenant_id=request.user.tenant_id, status=InboundOrder.Status.CONFIRMED,
            ), pk=pk,
        )
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
            'items': [{key: item[key] for key in (
                'product_name', 'sku_code', 'legacy_sku_code', 'expected_quantity',
                'received_quantity', 'difference', 'is_extra',
            )} for item in detail['lines']],
            'transit_styles': [{key: item[key] for key in (
                'product_name', 'spu_code', 'legacy_spu_code',
            )} for item in detail['transit_styles']],
            'preview_as_of': detail['preview_as_of'],
        }})
        response['Cache-Control'] = 'private, no-store'
        return response
