from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.masterdata.models import CountrySiteMaster, WarehouseMaster
from . import logistics, services, shipments
from .api import key, validated
from .models import BusinessEvent, DispatchBatch, FreightCompany, InboundOrder, PurchaseOrder
from .permissions import MANAGE, VIEW, internal_orders
from .serializers import VersionInput
from .views import InternalAPI, _page


class ShipmentVersionInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    version = serializers.IntegerField(min_value=1)


class AllocationInput(serializers.Serializer):
    shipment_line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)


class BatchCreateInput(serializers.Serializer):
    shipment_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=100)
    shipment_versions = ShipmentVersionInput(many=True, allow_empty=False)
    allocations = AllocationInput(many=True, allow_empty=False, required=False)
    freight_company_id = serializers.IntegerField(min_value=1)
    freight_number = serializers.CharField(max_length=120)
    notes = serializers.CharField(allow_blank=True, max_length=10000, default='')
    freight_channel_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    freight_quote_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    planned_warehouse_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    container_number = serializers.CharField(max_length=128, allow_blank=True, required=False)
    container_count = serializers.IntegerField(min_value=1, max_value=1000, required=False)
    expected_warehouse_date = serializers.DateField(allow_null=True, required=False)


class BatchEditInput(VersionInput):
    freight_company_id = serializers.IntegerField(min_value=1, required=False)
    freight_number = serializers.CharField(max_length=120, required=False)
    notes = serializers.CharField(allow_blank=True, max_length=10000, required=False)
    freight_channel_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    freight_quote_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    planned_warehouse_id = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    container_number = serializers.CharField(max_length=128, allow_blank=True, required=False)
    container_count = serializers.IntegerField(min_value=1, max_value=1000, required=False)
    expected_warehouse_date = serializers.DateField(allow_null=True, required=False)
    reason = serializers.CharField(allow_blank=True, max_length=10000, required=False)


class AwareDateTime(serializers.DateTimeField):
    def to_internal_value(self, value):
        try:
            parsed = parse_datetime(value) if isinstance(value, str) else None
        except (ValueError, TypeError):
            parsed = None
        if parsed is None or timezone.is_naive(parsed):
            raise serializers.ValidationError('请使用包含时区的实际物流时间。')
        return super().to_internal_value(value)


class StageInput(VersionInput):
    stage = serializers.ChoiceField(choices=['departed', 'arrived_port', 'arrived_warehouse'])
    occurred_at = AwareDateTime()


class ReasonInput(VersionInput):
    reason = serializers.CharField(max_length=10000)


class BatchMembersInput(ReasonInput):
    shipment_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=100)
    shipment_versions = ShipmentVersionInput(many=True, allow_empty=False)
    allocations = AllocationInput(many=True, allow_empty=False, required=False)


class CorrectDatesInput(StageInput):
    reason = serializers.CharField(max_length=10000)


class GenerateInput(VersionInput):
    warehouse_id = serializers.IntegerField(min_value=1, allow_null=True, required=False, default=None)
    reason = serializers.CharField(max_length=10000, allow_blank=True, required=False)


class InboundLineInput(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    received_quantity = serializers.IntegerField(min_value=0, max_value=2147483647, allow_null=True)
    difference_note = serializers.CharField(allow_blank=True, max_length=10000, default='')


class InboundEditInput(VersionInput):
    warehouse_id = serializers.IntegerField(min_value=1, required=False)
    notes = serializers.CharField(allow_blank=True, max_length=10000, required=False)
    lines = InboundLineInput(many=True, required=False, allow_empty=False)
    reason = serializers.CharField(max_length=10000, allow_blank=True, required=False)


class ExpectedWarehouseDateInput(VersionInput):
    expected_warehouse_date = serializers.DateField(allow_null=True, required=False)
    reason = serializers.CharField(max_length=10000)


class WmsAllocationInput(serializers.Serializer):
    inbound_line_id = serializers.IntegerField(min_value=1)
    wms_line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    notes = serializers.CharField(allow_blank=True, max_length=10000, required=False, default='')


class WmsAllocationDeactivateInput(VersionInput):
    reason = serializers.CharField(max_length=10000)


def history(actor, obj):
    return list(BusinessEvent.objects.filter(tenant=actor.tenant, aggregate_type=obj._meta.model_name,
        aggregate_id=obj.pk).order_by('id').values('id', 'action', 'aggregate_version', 'created_at', 'created_by_id', 'payload'))


class DispatchOptions(InternalAPI):
    def get(self, request):
        internal_orders(request.user, PurchaseOrder.objects.all())
        country = request.query_params.get('country_code', '')
        from .warehouse_archives import warehouse_refs
        warehouses = warehouse_refs(request.user).filter(status='active', country_code__iexact=country) if country else WarehouseMaster.objects.none()
        carriers = FreightCompany.objects.filter(tenant=request.user.tenant, is_active=True)
        country_rows = CountrySiteMaster.objects.filter(tenant=request.user.tenant, status='active')
        return Response({'data': {'freight_companies': list(carriers.order_by('code').values('id', 'code', 'name', 'shipping_marks')),
                                  'countries': [{'code': row.country_code.upper(), 'name': row.name} for row in country_rows.order_by('code')],
                                  'warehouses': list(warehouses.order_by('code').values('id', 'code', 'name', 'country_code'))}})


class DispatchCandidates(InternalAPI):
    def get(self, request):
        rows = logistics.candidates(request.user)
        if request.query_params.get('country_code'):
            rows = rows.filter(order__country_code_snapshot=request.query_params['country_code'].upper())
        search = request.query_params.get('search', '').strip()
        if search:
            rows = rows.filter(Q(number__icontains=search) | Q(order__number__icontains=search) | Q(order__supplier__name__icontains=search))
        return _page(request, rows, lambda obj: shipments.snapshot(obj, internal=True))


class Dispatches(InternalAPI):
    def get(self, request):
        rows = logistics.batches_for(request.user).select_related('freight_company', 'planned_warehouse')
        if request.query_params.get('stage'):
            rows = rows.filter(stage=request.query_params['stage'])
        if request.query_params.get('status'):
            rows = rows.filter(status=request.query_params['status'])
        search = request.query_params.get('search', '').strip()
        if search:
            rows = rows.filter(Q(number__icontains=search) | Q(freight_number__icontains=search) | Q(freight_company__name__icontains=search))
        return _page(request, rows, logistics.batch_data)

    def post(self, request):
        obj = logistics.create_batch(request.user, validated(BatchCreateInput, request), key(request))
        return Response({'data': logistics.batch_data(obj)}, status=201)


class DispatchDetail(InternalAPI):
    def get(self, request, pk):
        obj = logistics.batch_for(request.user, pk, VIEW)
        return Response({'data': {**logistics.batch_data(obj), 'history': history(request.user, obj)}})

    def patch(self, request, pk):
        obj = logistics.update_batch(request.user, pk, validated(BatchEditInput, request), key(request))
        return Response({'data': logistics.batch_data(obj)})


class DispatchStage(InternalAPI):
    def post(self, request, pk):
        obj = services.mark_logistics_stage(request.user, pk, **validated(StageInput, request), idempotency_key=key(request))
        return Response({'data': logistics.batch_data(obj)})


class DispatchMembers(InternalAPI):
    def post(self, request, pk):
        obj = logistics.replace_members(request.user, pk, validated(BatchMembersInput, request), key(request))
        return Response({'data': {**logistics.batch_data(obj), 'history': history(request.user, obj)}})


class DispatchCancel(InternalAPI):
    def post(self, request, pk):
        obj = logistics.cancel_batch(request.user, pk, validated(ReasonInput, request), key(request))
        return Response({'data': {**logistics.batch_data(obj), 'history': history(request.user, obj)}})


class DispatchDates(InternalAPI):
    def post(self, request, pk):
        obj = logistics.correct_dates(request.user, pk, validated(CorrectDatesInput, request), key(request))
        return Response({'data': {**logistics.batch_data(obj), 'history': history(request.user, obj)}})


class DispatchExpectedWarehouseDate(InternalAPI):
    def post(self, request, pk):
        obj = logistics.update_expected_warehouse_date(request.user, pk,
            validated(ExpectedWarehouseDateInput, request), key(request))
        return Response({'data': {**logistics.batch_data(obj), 'history': history(request.user, obj)}})


class GenerateInbound(InternalAPI):
    def post(self, request, pk):
        obj = services.generate_inbound_draft(request.user, pk, **validated(GenerateInput, request), idempotency_key=key(request))
        return Response({'data': logistics.inbound_data(obj)})


class Inbounds(InternalAPI):
    def get(self, request):
        rows = InboundOrder.objects.filter(tenant=request.user.tenant, batch__in=logistics.batches_for(request.user)).select_related('batch', 'batch__planned_warehouse', 'warehouse')
        if request.query_params.get('status'):
            rows = rows.filter(status=request.query_params['status'])
        search = request.query_params.get('search', '').strip()
        if search:
            rows = rows.filter(Q(number__icontains=search) | Q(batch__number__icontains=search) | Q(warehouse__name__icontains=search))
        return _page(request, rows, logistics.inbound_data)


class InboundDetail(InternalAPI):
    def get(self, request, pk):
        obj = logistics.inbound_for(request.user, pk, VIEW)
        return Response({'data': {**logistics.inbound_data(obj), 'history': history(request.user, obj)}})

    def patch(self, request, pk):
        obj = logistics.update_inbound(request.user, pk, validated(InboundEditInput, request), key(request))
        return Response({'data': logistics.inbound_data(obj)})


class WmsReconciliation(InternalAPI):
    def get(self, request, pk):
        obj = logistics.inbound_for(request.user, pk, VIEW)
        from . import wms_reconciliation
        return Response({'data': wms_reconciliation.reconcile_data(request.user, obj)})


class WmsCandidates(InternalAPI):
    def get(self, request, pk):
        obj = logistics.inbound_for(request.user, pk, VIEW)
        line_id = request.query_params.get('inbound_line_id', '')
        if not str(line_id).isdigit() or int(line_id) <= 0:
            raise ValidationError('请提供有效的本地入库行编号。')
        from . import wms_reconciliation
        return Response({'data': wms_reconciliation.candidates(request.user, obj, int(line_id),
            request.query_params.get('search', '').strip())})


class WmsAllocations(InternalAPI):
    def post(self, request, pk):
        obj = logistics.inbound_for(request.user, pk, MANAGE)
        from . import wms_reconciliation
        row = wms_reconciliation.allocate(request.user, obj, validated(WmsAllocationInput, request), key(request))
        return Response({'data': {'id': row.pk, 'version': row.version}}, status=201)


class WmsAllocationDeactivate(InternalAPI):
    def post(self, request, pk, allocation_id):
        obj = logistics.inbound_for(request.user, pk, MANAGE)
        from . import wms_reconciliation
        row = wms_reconciliation.deactivate(request.user, obj, allocation_id,
            validated(WmsAllocationDeactivateInput, request), key(request))
        return Response({'data': {'id': row.pk, 'version': row.version, 'is_active': row.is_active}})


class ConfirmInbound(InternalAPI):
    def post(self, request, pk):
        obj = logistics.confirm_inbound(request.user, pk, validated(VersionInput, request), key(request))
        return Response({'data': logistics.inbound_data(obj)})
