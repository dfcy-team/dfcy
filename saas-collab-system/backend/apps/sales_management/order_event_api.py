from django.db.models import Min, Max
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.integrations.models import MarketplaceStoreAuthorization, WebhookEvent
from .order_presentation import factual_events
from .order_event_scope import shop_identity, milestone_filters


class OrderEventView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = 'sales_management.orders.view'

    def get(self, request, pk):
        from .views import _scoped_orders
        order = get_object_or_404(_scoped_orders(request, self.read_permission_code), pk=pk)
        try:
            page = int(request.query_params.get('page', 1))
            if not 1 <= page <= 10000:
                raise ValueError
        except ValueError:
            raise ValidationError({'page': 'Invalid page.'}) from None
        shops = MarketplaceStoreAuthorization.objects.filter(
            tenant_id=order.tenant_id, store_id=order.store_id,
            platform=order.platform.platform_type).values_list('platform', 'region', 'platform_store_id')
        shops = [shop_identity(*identity) for identity in shops]
        rows = WebhookEvent.objects.filter(
            tenant_id=order.tenant_id, platform=order.platform.platform_type,
            signature_status='valid', external_shop_id__in=shops,
            external_order_id=order.external_order_id, event_at__isnull=False)
        milestones = rows.aggregate(**{key: (Max if key == 'cancel_requested_at' else Min)(
            'event_at', filter=value) for key, value in milestone_filters().items()})
        from .order_warehouse_summary import attach_warehouse_summaries
        summary = {'id': order.pk}
        attach_warehouse_summaries(request.user, [summary])
        facts = factual_events(order, summary['warehouse_summary'])
        end = page * 100
        events = [dict(id=row.event_id, status=row.order_status,
                       completed_scenario=row.completed_scenario, event_at=row.event_at,
                       received_at=row.received_at, source='平台状态推送',
                       title=('售后商品行状态：' if row.event_type == 'lazada.reverse_order_line' else
                              '订单商品行状态：') + row.order_status if row.platform == 'lazada' else
                              ({'CANCEL': '订单取消', 'COMPLETED': '订单完成', 'ON_HOLD': '订单暂缓',
                                'AWAITING_SHIPMENT': '待发货', 'AWAITING_COLLECTION': '待揽收',
                                'IN_TRANSIT': '运输中', 'DELIVERED': '包裹已妥投'}.get(row.order_status, '')
                               if row.platform == 'tiktok' else ''),
                       event_type=row.event_type)
                  for row in rows.order_by('-event_at', '-event_id')[:end]]
        events.extend(facts)
        events.sort(key=lambda item: (item['event_at'], item['id']), reverse=True)
        count = rows.count() + len(facts)
        return success_response({'events': events[end-100:end], 'count': count,
            'page': page, 'has_more': count > end, 'limited': False, 'milestones': milestones,
            'message': '根据已保存的平台事实和状态推送整理；不代表完整状态历史，物流妥投不等于订单完成。'})
