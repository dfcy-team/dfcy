from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.permissions.services import check_stored_business_read_permission, get_stored_business_read_scopes
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from apps.integrations.models import WarehouseAuthorization
from .warehouse_orders import lookup_data, request_lookup, require_access


class OrderWarehouseView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = 'sales_management.orders.view'
    write_permission_code = 'integrations.run_live_readonly'

    def order(self, request, pk):
        from .views import _scoped_orders
        return get_object_or_404(_scoped_orders(request, self.read_permission_code), pk=pk)

    def get(self, request, pk):
        order = self.order(request, pk)
        if not check_stored_business_read_permission(request.user, 'integrations.warehouse.view'):
            return success_response({'status': 'forbidden', 'status_label': '无仓库信息查看权限',
                                     'message': '当前角色未获授权查看仓库信息。', 'can_retry': False})
        data = lookup_data(order)
        ids = {item.get('authorization_id') for item in data.get('checks', [])}
        ids.add(data.get('snapshot', {}).get('authorization_id'))
        visible_ids = set()
        for auth in WarehouseAuthorization.objects.filter(pk__in=[pk for pk in ids if pk],
                tenant_id=request.user.tenant_id).select_related('integration_config'):
            if integration_values_allowed(request.user, 'integrations.warehouse.view', platform=auth.provider,
                    environment=auth.integration_config.environment, regions=[auth.external_warehouse_region],
                    config_id=auth.integration_config_id, warehouse_id=auth.warehouse_id,
                    scope_resolver=get_stored_business_read_scopes):
                visible_ids.add(auth.pk)
        if data.get('snapshot') and data['snapshot'].get('authorization_id') not in visible_ids:
            data['snapshot'] = {}
            data['message'] = '关联仓库不在当前账户的查看范围内。'
        data['checks'] = [item for item in data.get('checks', []) if item.get('authorization_id') in visible_ids]
        try:
            require_access(request.user, order)
            data['can_retry'] = bool(getattr(settings, 'SALES_ORDER_WAREHOUSE_SYNC_ENABLED', False))
        except PermissionDenied:
            data['can_retry'] = False
        return success_response(data)

    def post(self, request, pk):
        order = self.order(request, pk)
        if not getattr(settings, 'SALES_ORDER_WAREHOUSE_SYNC_ENABLED', False):
            raise PermissionDenied('仓库订单查询尚未启用。')
        request_lookup(order.pk, request.user, manual=True)
        # Return only submission status; GET applies the warehouse visibility scope to snapshots.
        return success_response({'status': 'pending'})
