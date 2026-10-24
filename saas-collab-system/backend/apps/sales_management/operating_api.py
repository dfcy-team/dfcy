from decimal import Decimal
from datetime import timedelta
from django.db.models import Q
from rest_framework import serializers
from rest_framework.response import Response
from io import BytesIO
from django.http import FileResponse
from rest_framework.exceptions import NotFound, ValidationError
from apps.masterdata.models import CountrySiteMaster
from apps.products.models import ProductSKU
from apps.supply_chain.api import key, validated
from apps.supply_chain.dates import business_date
from apps.supply_chain.serializers import VersionInput
from apps.supply_chain.services import purchase_snapshot
from apps.supply_chain.supplier_products import product_details
from apps.supply_chain.supplier_product_images import load_product_images
from apps.supply_chain.views import InternalAPI, _page
from apps.supply_chain.logistics_api import history
from . import operating as domain
from .operating_models import OperatingOrder


def search_orders(rows, value):
    value = value.strip()
    if value:
        return rows.filter(Q(number__icontains=value) | Q(country__name__icontains=value) |
                           Q(country_code_snapshot__icontains=value))
    return rows


class DemandLineInput(serializers.Serializer):
    sku_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)


class DemandInput(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1)
    source_kind = serializers.ChoiceField(choices=['new_goods', 'cycle', 'season'])
    order_date = serializers.DateField(default=business_date)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default='')
    lines = DemandLineInput(many=True, allow_empty=False)
    expected_version = serializers.IntegerField(min_value=1, required=False)
    preview_token = serializers.CharField(max_length=64, required=False)
    campaign = serializers.CharField(max_length=120, allow_blank=True, required=False)
    demand_start = serializers.DateField(allow_null=True, required=False)
    demand_end = serializers.DateField(allow_null=True, required=False)
    plan_revision = serializers.CharField(max_length=40, allow_blank=True, required=False)

    def validate(self, attrs):
        start, end = attrs.get('demand_start'), attrs.get('demand_end')
        if bool(start) != bool(end) or (start and end and start > end):
            raise serializers.ValidationError('需求期间须同时填写起止日期，结束日期不能早于开始日期。')
        return attrs

    def validate_lines(self, rows):
        if len(rows) > 1000:
            raise serializers.ValidationError('每次最多1000行。')
        return rows


class PreviewInput(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1)
    sku_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=100)
    sales_start = serializers.DateField(required=False)
    sales_end = serializers.DateField(required=False)
    target_stock_sales_ratio = serializers.DecimalField(max_digits=10, decimal_places=4, min_value=Decimal('0.0001'), max_value=100, required=False)
    include_in_transit = serializers.BooleanField(default=True)
    sales_window_days = serializers.ChoiceField(choices=[7, 15, 30], required=False)
    target_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    exclude_operating_order_id = serializers.IntegerField(min_value=1, required=False)
    strategy_id = serializers.IntegerField(min_value=1, required=False)
    source_kind = serializers.ChoiceField(choices=['cycle', 'season'], required=False)
    activity_start = serializers.DateField(required=False, allow_null=True)
    activity_end = serializers.DateField(required=False, allow_null=True)
    activity_factor = serializers.DecimalField(max_digits=8, decimal_places=4, min_value=Decimal('0.01'), max_value=Decimal('20'), required=False, default=Decimal(1))

    def validate(self, attrs):
        strategy_mode = bool(attrs.get('strategy_id'))
        if strategy_mode:
            if attrs.get('source_kind') not in ('cycle', 'season'):
                raise serializers.ValidationError({'source_kind': '新算法须提供周期或季节订货来源。'})
            start, end = attrs.get('activity_start'), attrs.get('activity_end')
            if bool(start) != bool(end) or (start and start > end):
                raise serializers.ValidationError('活动开始、结束日期须同时填写，结束日期不能早于开始日期。')
            if attrs['source_kind'] == 'season' and not start:
                raise serializers.ValidationError('季节订货必须填写活动日期。')
            attrs.setdefault('sales_end', business_date() - timedelta(days=1))
            return attrs
        if not attrs.get('sales_start') or not attrs.get('sales_end') or attrs.get('target_stock_sales_ratio') is None:
            raise serializers.ValidationError('旧算法须提供销量日期和目标库销比；新算法请提供 strategy_id。')
        if ('sales_window_days' in attrs) != ('target_days' in attrs):
            raise serializers.ValidationError('最近自然日测算须同时提供销量窗口和目标覆盖天数。')
        return attrs


class DemandUpdateInput(DemandInput):
    expected_version = serializers.IntegerField(min_value=1)


class SplitLineInput(serializers.Serializer):
    operating_line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=2147483647)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0, required=False, allow_null=True)


class SplitInput(VersionInput):
    supplier_id = serializers.IntegerField(min_value=1)
    reference_number = serializers.CharField(max_length=120, allow_blank=True, default='')
    notes = serializers.CharField(max_length=10000, allow_blank=True, default='')
    lines = SplitLineInput(many=True, allow_empty=False)

    def validate_lines(self, rows):
        if len(rows) > 1000:
            raise serializers.ValidationError('每次最多1000行。')
        return rows


class OperatingAPI(InternalAPI):
    read_permission_code = domain.VIEW
    write_permission_code = domain.MANAGE


class OperatingOptions(OperatingAPI):
    def get(self, request):
        domain._require(request.user, domain.VIEW)
        kind, search = request.query_params.get('kind', ''), request.query_params.get('search', '')
        if kind == 'countries':
            rows = CountrySiteMaster.objects.filter(tenant=request.user.tenant, status='active')
            scopes = domain._require(request.user, domain.VIEW)
            if not any(s['scope_type'] in ['all', 'own'] for s in scopes):
                ids = [pk for scope in scopes for pk in domain.country_ids(scope)]
                rows = rows.filter(pk__in=ids)
            if search:
                rows = rows.filter(Q(name__icontains=search) | Q(country_code__icontains=search))
            return _page(request, rows, lambda r: {'id': r.pk, 'code': r.code, 'name': r.name, 'country_code': r.country_code})
        rows = ProductSKU.objects.filter(tenant=request.user.tenant, is_active=True, spu__product_type="standard").exclude(inventory_type="virtual")
        if search:
            rows = rows.filter(Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search) | Q(product_name__icontains=search))
        rows = rows.select_related('spu__category_node')
        return _page(request, rows, lambda r: {'id': r.pk, 'sku_code': r.sku_code,
            'legacy_sku_code': r.legacy_sku_code or '', 'product_name': r.product_name,
            'product_details': product_details(r)})


class OperatingSKUImage(OperatingAPI):
    def get(self, request, sku_id):
        domain._require(request.user, domain.VIEW)
        sku = ProductSKU.objects.filter(tenant_id=request.user.tenant_id, pk=sku_id,
            is_active=True).select_related('spu__category_node').first()
        if sku is None:
            raise NotFound('商品不可访问。')
        image = load_product_images({'lines': [{'sku_id': sku.pk,
            'product_details': product_details(sku)}]}, request.user.tenant_id).get(sku.pk, {})
        if not image.get('body'):
            raise NotFound('商品图片尚未维护或暂不可用。')
        response = FileResponse(BytesIO(image['body']), content_type='image/jpeg')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class OperatingOrders(OperatingAPI):
    def get(self, request):
        rows = domain.orders_for(request.user).select_related('country')
        if request.query_params.get('status'):
            rows = rows.filter(status=request.query_params['status'])
        rows = search_orders(rows, request.query_params.get('search', ''))
        return _page(request, rows, lambda obj: domain.snapshot(obj, request.user))

    def post(self, request):
        obj = domain.save_order(request.user, validated(DemandInput, request), key(request))
        return Response({'data': domain.snapshot(obj, request.user)}, status=201)


def visible_operating_history(actor, obj):
    def redact(value):
        if isinstance(value, dict):
            return {k: domain.visible_calculation(actor, v) if k == 'calculation_snapshot'
                    else redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value
    return redact(history(actor, obj))


class OperatingDetail(OperatingAPI):
    def get(self, request, pk):
        obj = domain.order_for(request.user, pk, permission=domain.VIEW)
        return Response({'data': {**domain.snapshot(obj, request.user), 'history': visible_operating_history(request.user, obj)}})

    def patch(self, request, pk):
        validated(VersionInput, request)
        obj = domain.save_order(request.user, validated(DemandUpdateInput, request), key(request), pk)
        return Response({'data': domain.snapshot(obj, request.user)})


class OperatingSubmit(OperatingAPI):
    target = 'submitted'
    def post(self, request, pk):
        obj = domain.action(request.user, pk, validated(VersionInput, request), key(request), self.target)
        return Response({'data': domain.snapshot(obj, request.user)})


class OperatingCancel(OperatingSubmit):
    target = 'cancelled'


class OperatingPreview(OperatingAPI):
    def post(self, request):
        domain._require(request.user, domain.MANAGE)
        from apps.commerce.country_decisions import require_metrics
        require_metrics(request.user)
        if not request.data.get('strategy_id'):
            raise ValidationError({'strategy_id': '新生成的周期/季节订货建议须使用已配置的国家补货策略。旧计算快照仍可查看；请勿继续使用旧库销比公式。'})
        return Response({'data': domain.preview(request.user, validated(PreviewInput, request), key(request))})


class ProcurementOperatingOrders(InternalAPI):
    def get(self, request):
        rows = domain.procurement_orders_for(request.user).select_related('country')
        rows = search_orders(rows, request.query_params.get('search', ''))
        return _page(request, rows, lambda obj: domain.snapshot(obj, request.user))


class ProcurementOperatingDetail(InternalAPI):
    def get(self, request, pk):
        return Response({'data': domain.snapshot(domain.order_for(request.user, pk, procurement=True), request.user)})


class ProcurementSplit(InternalAPI):
    def post(self, request, pk):
        obj, order = domain.split(request.user, pk, validated(SplitInput, request), key(request))
        return Response({'data': {'operating_order': domain.snapshot(obj, request.user), 'purchase_order': purchase_snapshot(order)}}, status=201)
