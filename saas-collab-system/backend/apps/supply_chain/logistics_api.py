from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.exceptions import custom_exception_handler
from apps.masterdata.models import CountrySiteMaster, WarehouseMaster
from . import logistics, services, shipments
from .read_batches import prepare_shipments, prepare_batches
from .api import key, price_queryset, validated
from .models import BusinessEvent, DispatchAllocation, DispatchBatch, FreightCompany, InboundExtraLine, InboundLine, InboundOrder, PurchaseOrder, ShipmentLine
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


class InboundExtraLineInput(serializers.Serializer):
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal('0'), allow_null=True, required=False)
    sku_id = serializers.IntegerField(min_value=1)
    received_quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    difference_note = serializers.CharField(allow_blank=True, max_length=10000, default='')


class InboundEditInput(VersionInput):
    warehouse_id = serializers.IntegerField(min_value=1, required=False)
    notes = serializers.CharField(allow_blank=True, max_length=10000, required=False)
    lines = InboundLineInput(many=True, required=False, allow_empty=False)
    extra_lines = InboundExtraLineInput(many=True, required=False, allow_empty=True, max_length=500)
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
        carrier_ids = [pk for pk, scopes in FreightCompany.objects.filter(
            tenant=request.user.tenant, is_active=True).values_list('pk', 'service_scopes')
            if 'international' in (scopes or [])]
        carriers = FreightCompany.objects.filter(pk__in=carrier_ids)
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
            product_match = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True).filter(
                Q(sku_code_snapshot__icontains=search) | Q(product_name_snapshot__icontains=search)
                | Q(purchase_line__order__number__icontains=search)
                | Q(sku__sku_code__icontains=search) | Q(sku__legacy_sku_code__icontains=search)
                | Q(sku__product_name__icontains=search) | Q(sku__spu__spu_code__icontains=search) | Q(sku__spu__product_name__icontains=search))
            rows = rows.annotate(_search_product_match=Exists(product_match)).filter(
                Q(number__icontains=search) | Q(order__number__icontains=search)
                | Q(order__supplier__name__icontains=search) | Q(notes__icontains=search)
                | Q(_search_product_match=True))
        return _page(request, rows, lambda obj: shipments.snapshot(obj, internal=True), prepare=prepare_shipments)


class Dispatches(InternalAPI):
    def get(self, request):
        rows = logistics.batches_for(request.user).select_related('freight_company', 'planned_warehouse')
        if request.query_params.get('country_code'):
            rows = rows.filter(country_code_snapshot__iexact=request.query_params['country_code'].strip())
        if request.query_params.get('stage'):
            rows = rows.filter(stage=request.query_params['stage'])
        if request.query_params.get('status'):
            rows = rows.filter(status=request.query_params['status'])
        search = request.query_params.get('search', '').strip()
        if search:
            allocated_product = DispatchAllocation.objects.filter(
                membership__batch_id=OuterRef('pk'), membership__active_guard=True,
                shipment_line__is_active=True).filter(
                Q(shipment_line__sku_code_snapshot__icontains=search)
                | Q(shipment_line__product_name_snapshot__icontains=search)
                | Q(shipment_line__shipment__order__number__icontains=search)
                | Q(shipment_line__purchase_line__order__number__icontains=search)
                | Q(shipment_line__sku__sku_code__icontains=search)
                | Q(shipment_line__sku__legacy_sku_code__icontains=search)
                | Q(shipment_line__sku__product_name__icontains=search)
                | Q(shipment_line__sku__spu__spu_code__icontains=search) | Q(shipment_line__sku__spu__product_name__icontains=search))
            rows = rows.annotate(_search_product_match=Exists(allocated_product)).filter(
                Q(number__icontains=search) | Q(freight_number__icontains=search)
                | Q(freight_company__name__icontains=search) | Q(notes__icontains=search)
                | Q(_search_product_match=True)).distinct()
        return _page(request, rows, logistics.batch_data, prepare=prepare_batches)

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


def prepare_inbound_list(page):
    """Load only the quantities, prices and suppliers needed by the list."""
    summaries = {
        obj.pk: {'suppliers': set(), 'quantity': 0, 'amount': Decimal('0'), 'complete': True}
        for obj in page
    }
    if not summaries:
        return
    lines = InboundLine.objects.filter(inbound_id__in=summaries).values_list(
        'inbound_id', 'received_quantity', 'shipment_line__unit_price',
        'shipment_line__shipment__order__supplier__name',
    ).order_by()
    for inbound_id, quantity, price, supplier in lines.iterator():
        summary = summaries[inbound_id]
        summary['suppliers'].add(supplier)
        summary['quantity'] += quantity or 0
        if quantity is not None and price is not None:
            summary['amount'] += quantity * price
        if quantity is None or (quantity != 0 and price is None):
            summary['complete'] = False
    extra_lines = InboundExtraLine.objects.filter(inbound_id__in=summaries, is_active=True).values_list(
        'inbound_id', 'received_quantity', 'unit_price')
    for inbound_id, quantity, unit_price in extra_lines.iterator():
        summary = summaries[inbound_id]
        summary['quantity'] += quantity
        if unit_price is None:
            summary['complete'] = False
        else:
            summary['amount'] += quantity * unit_price
    for obj in page:
        obj.list_summary = summaries[obj.pk]


def inbound_list_data(obj):
    summary = obj.list_summary
    return {
        'id': obj.pk, 'number': obj.number, 'batch_id': obj.batch_id,
        'batch_number': obj.batch.number, 'country_code': obj.batch.country_code_snapshot,
        'warehouse_id': obj.warehouse_id, 'warehouse_name': obj.warehouse.name,
        'planned_warehouse_id': obj.batch.planned_warehouse_id,
        'planned_warehouse_name': obj.batch.planned_warehouse.name if obj.batch.planned_warehouse_id else '',
        'status': obj.status, 'version': obj.version, 'notes': obj.notes,
        'stock_receipt_ref': obj.stock_receipt_ref, 'confirmed_at': obj.confirmed_at,
        'supplier_names': ', '.join(sorted(summary['suppliers'])),
        'received_quantity': summary['quantity'], 'received_amount': str(summary['amount']),
        'received_amount_complete': summary['complete'],
    }


class Inbounds(InternalAPI):
    def get(self, request):
        rows = InboundOrder.objects.filter(tenant=request.user.tenant, batch__in=logistics.batches_for(request.user)).select_related('batch', 'batch__planned_warehouse', 'warehouse')
        if request.query_params.get('status'):
            rows = rows.filter(status=request.query_params['status'])
        country_code = request.query_params.get('country_code', '').strip().upper()
        if country_code:
            rows = rows.filter(batch__country_code_snapshot=country_code)
        search = request.query_params.get('search', '').strip()
        if search:
            inbound_product = InboundLine.objects.filter(inbound_id=OuterRef('pk')).filter(
                Q(shipment_line__is_active=True) & (Q(shipment_line__purchase_line__order__number__icontains=search)
                | Q(shipment_line__shipment__order__number__icontains=search)
                | Q(shipment_line__sku_code_snapshot__icontains=search)
                | Q(shipment_line__product_name_snapshot__icontains=search)
                | Q(shipment_line__sku__sku_code__icontains=search)
                | Q(shipment_line__sku__legacy_sku_code__icontains=search)
                | Q(shipment_line__sku__product_name__icontains=search)
                | Q(shipment_line__sku__spu__spu_code__icontains=search) | Q(shipment_line__sku__spu__product_name__icontains=search)))
            extra_product = InboundExtraLine.objects.filter(inbound_id=OuterRef('pk'), is_active=True).filter(
                Q(sku_code_snapshot__icontains=search) | Q(legacy_sku_code_snapshot__icontains=search)
                | Q(product_name_snapshot__icontains=search) | Q(sku__sku_code__icontains=search)
                | Q(sku__legacy_sku_code__icontains=search) | Q(sku__product_name__icontains=search)
                | Q(sku__spu__spu_code__icontains=search) | Q(sku__spu__product_name__icontains=search))
            rows = rows.annotate(_search_product_match=Exists(inbound_product),
                _search_extra_product_match=Exists(extra_product)).filter(
                Q(number__icontains=search) | Q(batch__number__icontains=search)
                | Q(warehouse__name__icontains=search) | Q(notes__icontains=search)
                | Q(_search_product_match=True) | Q(_search_extra_product_match=True)).distinct()
        return _page(request, rows, inbound_list_data, prepare=prepare_inbound_list)


class InboundExtraSkuOptions(InternalAPI):
    def get(self, request, pk):
        from apps.products.models import ProductSKU

        inbound = logistics.inbound_for(request.user, pk, MANAGE)
        search = request.query_params.get('search', '').strip()[:160]
        if inbound.status != 'draft' or len(search) < 2:
            return Response({'data': []})
        source_skus = inbound.lines.values('shipment_line__sku_id')
        latest_price = price_queryset(request.user).filter(
            sku_id=OuterRef('pk'), effective_date__lte=timezone.localdate(),
        ).order_by('-effective_date', '-updated_at', '-pk').values('unit_price')[:1]
        matches = ProductSKU.objects.filter(tenant_id=inbound.tenant_id, is_active=True).exclude(
            pk__in=source_skus
        ).filter(
            Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search)
            | Q(product_name__icontains=search) | Q(spu__product_name__icontains=search)
        ).annotate(
            reference_unit_price=Coalesce(Subquery(latest_price), 'purchase_price'),
        ).order_by('sku_code', 'pk').values(
            'id', 'sku_code', 'legacy_sku_code', 'product_name', 'spu__product_name', 'reference_unit_price'
        )[:50]
        return Response({'data': [
            {'id': row['id'], 'sku_code': row['sku_code'], 'legacy_sku_code': row['legacy_sku_code'],
             'product_name': row['product_name'] or row['spu__product_name'],
             'reference_unit_price': str(row['reference_unit_price']) if row['reference_unit_price'] is not None else None}
            for row in matches
        ]})


class InboundDetail(InternalAPI):
    def get(self, request, pk):
        obj = logistics.inbound_for(request.user, pk, VIEW)
        return Response({'data': {**logistics.inbound_data(obj), 'history': history(request.user, obj)}})

    def patch(self, request, pk):
        obj = logistics.update_inbound(request.user, pk, validated(InboundEditInput, request), key(request))
        return Response({'data': logistics.inbound_data(obj)})


class InboundExport(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request, pk):
        from django.http import HttpResponse
        from .documents import inbound_reconciliation_workbook
        from .supplier_product_images import load_product_images
        obj = logistics.inbound_for(request.user, pk, VIEW)
        snapshot = logistics.inbound_data(obj)
        content = inbound_reconciliation_workbook(snapshot, images=load_product_images(snapshot, request.user.tenant_id))
        response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{obj.number}-reconciliation.xlsx"'
        response['Cache-Control'] = 'private, no-store'
        return response


class InboundBigSeller(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request, pk):
        from io import BytesIO
        from django.http import FileResponse
        from .bigseller import export_inbound
        inbound = logistics.inbound_for(request.user, pk, VIEW)
        response = FileResponse(BytesIO(export_inbound(inbound, sku_mode=request.query_params.get('sku_mode', 'legacy'))),
            as_attachment=True, filename=f'{inbound.batch.number}-bigseller.xlsx',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


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
        payload = validated(VersionInput, request)
        request_key = key(request)
        try:
            obj = logistics.confirm_inbound(request.user, pk, payload, request_key)
        except DjangoValidationError as exc:
            response = custom_exception_handler(exc, self.get_exception_handler_context())
            response.data['message'] = '；'.join(exc.messages) or '确认入库失败，请检查入库单。'
            return response
        return Response({'data': logistics.inbound_data(obj)})


class DispatchBigSeller(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request, pk):
        raise ValidationError('BigSeller 采购单须从已确认入库单导出。')
