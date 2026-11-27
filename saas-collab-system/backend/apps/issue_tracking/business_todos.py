"""Read-only automatic business work; never creates manual Issues or unread messages."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.db.models import Exists, OuterRef, Sum, F, Value, IntegerField, BigIntegerField, Subquery
from django.db.models.functions import Coalesce, Greatest, Cast
from django.utils import timezone
from rest_framework.views import APIView
from apps.common.responses import success_response as Response
from rest_framework import permissions

class InternalOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.user_type == "internal")

BEIJING = ZoneInfo('Asia/Shanghai')

def cutoff(now, days=3):
    today = now.astimezone(BEIJING).date()
    # Arrival date plus three calendar days, inclusive of that whole arrival date.
    return datetime.combine(today - timedelta(days=days-1), time.min, BEIJING)

def pending_batches(actor, now=None):
    from apps.permissions.services import check_user_permission
    from apps.supply_chain.logistics import batches_for
    from apps.supply_chain.models import DispatchAllocation, InboundOrder, InboundShortageTermination
    if not check_user_permission(actor, 'supply.v2.view'):
        from apps.supply_chain.models import DispatchBatch
        return DispatchBatch.objects.none()
    from apps.supply_chain.inbound_notify_models import InboundNotificationConfig
    days = InboundNotificationConfig.objects.filter(tenant_id=actor.tenant_id).values_list('arrival_unreceived_reminder_days',flat=True).first() or 3
    confirmed = InboundOrder.objects.filter(batch_id=OuterRef('pk'), status='confirmed')
    allocations = DispatchAllocation.objects.filter(membership__batch_id=OuterRef('pk'), membership__active_guard=True,
        shipment_line__is_active=True, shipment_line__shipment__status='submitted').values('membership__batch_id').annotate(total=Sum('quantity')).values('total')
    closed = InboundShortageTermination.objects.filter(batch_id=OuterRef('pk')).values('batch_id').annotate(total=Sum('quantity')).values('total')
    return batches_for(actor).filter(status='active', stage='arrived_warehouse',
        arrived_warehouse_at__lt=cutoff(now or timezone.now(), days)).annotate(
        has_confirmed=Exists(confirmed),
        pending_quantity=Greatest(Cast(Coalesce(Subquery(allocations, output_field=IntegerField()), Value(0)), BigIntegerField())-
            Cast(Coalesce(Subquery(closed, output_field=IntegerField()), Value(0)), BigIntegerField()), Value(0), output_field=BigIntegerField())).filter(
        has_confirmed=False, pending_quantity__gt=0).select_related('country', 'planned_warehouse').order_by('arrived_warehouse_at','pk')

class BusinessTodos(APIView):
    permission_classes = [InternalOnly]
    def get(self, request):
        now=timezone.now()
        queryset=pending_batches(request.user, now)
        from django.core.paginator import Paginator
        try: page=max(1,int(request.query_params.get('page',1)))
        except (ValueError,TypeError): page=1
        paginator=Paginator(queryset,20)
        result=paginator.get_page(page)
        return Response({'count':paginator.count,'page':result.number,'page_size':20,'results':[
            {'id':row.pk,'number':row.number,'country':row.country_code_snapshot,
             'warehouse':row.planned_warehouse.name if row.planned_warehouse_id else '未指定计划仓',
             'arrived_at':row.arrived_warehouse_at,'arrived_days':(now.astimezone(BEIJING).date()-row.arrived_warehouse_at.astimezone(BEIJING).date()).days,
             'pending_quantity':row.pending_quantity,'path':f'/supply-chain/logistics?batch_id={row.pk}'}
            for row in result.object_list]})
