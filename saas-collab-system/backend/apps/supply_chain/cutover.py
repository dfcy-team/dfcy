"""Keep legacy supply records readable while the v2 workflow owns new writes."""
from django.conf import settings
from django.http import JsonResponse


LEGACY_PREFIXES = (
    '/api/internal/purchasing/orders/',
    '/api/internal/purchasing/supply-orders/',
    '/api/internal/supply-chain/consolidations/',
    '/api/internal/supply-chain/shipments/',
    '/api/external/supplier/purchase-orders/',
    '/api/external/supplier/shipments/',
    '/api/external/supplier/consolidations/',
    '/api/miniapp/supply-chain/orders/',
    '/api/miniapp/supply-chain/consolidations/',
)


class LegacySupplyWriteFence:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info.rstrip('/') + '/'
        read_ticket = request.method == 'POST' and path.endswith('/download-ticket/')
        if (request.method not in ('GET', 'HEAD', 'OPTIONS') and not read_ticket and
                not getattr(settings, 'SUPPLY_CHAIN_LEGACY_WRITES_ENABLED', False) and
                any(path.startswith(prefix) for prefix in LEGACY_PREFIXES)):
            return JsonResponse({'success': False, 'code': 'LEGACY_SUPPLY_READ_ONLY',
                'message': '旧供应链单据仅供历史查询，请在新版采购协同、供应商发货单或集货发运与入库办理新业务。'}, status=409)
        return self.get_response(request)
