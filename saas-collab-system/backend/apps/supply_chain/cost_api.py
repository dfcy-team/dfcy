from decimal import Decimal
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import costs
from . import cost_ledger
from .api import key, validated
from .views import InternalAPI, _page


class SourceVersion(serializers.Serializer):
    expected_source_version = serializers.IntegerField(min_value=1)


class MeasurementInput(serializers.Serializer):
    shipment_line_id = serializers.IntegerField(min_value=1)
    volume_cbm = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=0, allow_null=True, required=False)
    weight_kg = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=0, allow_null=True, required=False)


class FeeInput(SourceVersion):
    expected_version = serializers.IntegerField(min_value=0)
    amount = serializers.DecimalField(max_digits=20, decimal_places=4, min_value=0)
    state = serializers.ChoiceField(choices=['estimated', 'confirmed'])
    method = serializers.ChoiceField(choices=['volume', 'weight', 'mixed'])
    volume_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, allow_null=True)
    billed_cbm = serializers.DecimalField(max_digits=16, decimal_places=6, min_value=0, allow_null=True, default=None)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default='')
    reason = serializers.CharField(max_length=10000)
    measurements = MeasurementInput(many=True, required=False)

    def validate(self, value):
        if value['method'] == 'volume':
            value['volume_percent'] = 100
        elif value['method'] == 'weight':
            value['volume_percent'] = 0
        elif value['volume_percent'] is None:
            raise serializers.ValidationError('混合分摊须填写体积比例。')
        return value


class CalculationInput(SourceVersion):
    expected_input_fingerprint = serializers.RegexField(r'^[0-9a-f]{64}$')


class PayeeAllocationInput(serializers.Serializer):
    account_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('0.0001'))


class PayeeAccountInput(serializers.Serializer):
    nature = serializers.ChoiceField(choices=['corporate', 'personal'])
    account_name = serializers.CharField(max_length=160)
    account_holder = serializers.CharField(max_length=160)
    bank_name = serializers.CharField(max_length=160)
    account_number = serializers.CharField(max_length=128)
    active = serializers.BooleanField(default=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class SettlementInput(SourceVersion):
    expected_version = serializers.IntegerField(min_value=0)
    recorded_amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=0)
    reference_number = serializers.CharField(max_length=200)
    date = serializers.DateField()
    notes = serializers.CharField(max_length=10000, allow_blank=True, default='')
    reason = serializers.CharField(max_length=10000)
    payee_allocations = PayeeAllocationInput(many=True, max_length=100, required=False)


class PaymentInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('0.0001'))
    date = serializers.DateField()
    payee_account_id = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(max_length=10000, allow_blank=True, required=False, default='')
    reference_number = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    expected_version = serializers.IntegerField(min_value=0)


class PrepaymentApplicationInput(serializers.Serializer):
    payment_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('0.0001'))
    date = serializers.DateField()
    expected_version = serializers.IntegerField(min_value=0)


class ReversalInput(serializers.Serializer):
    reason = serializers.CharField(max_length=10000)
    expected_version = serializers.IntegerField(min_value=0)
    date = serializers.DateField(required=False)


class LedgerQuery(serializers.Serializer):
    search = serializers.CharField(max_length=200, allow_blank=True, default='')
    versions = serializers.ChoiceField(choices=['latest', 'all'], default='latest')
    sku_id = serializers.IntegerField(min_value=1, required=False)
    country_id = serializers.IntegerField(min_value=1, required=False)
    warehouse_id = serializers.IntegerField(min_value=1, required=False)
    batch_id = serializers.IntegerField(min_value=1, required=False)


class ProductCostLedger(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        query = LedgerQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        rows = cost_ledger.filter_entries(cost_ledger.entries_for(request.user,
            history=params['versions'] == 'all'), params)
        fingerprints = {}
        try:
            limit, offset = int(request.query_params.get('limit', 50)), int(request.query_params.get('offset', 0))
        except (ValueError, TypeError):
            raise ValidationError('Invalid pagination.')
        if not 1 <= limit <= 100 or offset < 0:
            raise ValidationError('Limit must be 1–100 and offset must be nonnegative.')
        data = cost_ledger.serialize_many(rows.order_by('-id')[offset:offset + limit], fingerprints)
        from rest_framework.response import Response
        return Response({'data': data, 'count': rows.count(), 'limit': limit, 'offset': offset})


class ProductCostLedgerOptions(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        from apps.masterdata.models import CountrySiteMaster, WarehouseMaster
        from .models import DispatchBatch
        # Filters never enumerate another supplier's or tenant's cost owners.
        rows = cost_ledger.entries_for(request.user, history=True)
        search = request.query_params.get('search', '').strip()[:200]
        kind = request.query_params.get('kind')
        if kind == 'countries':
            options = CountrySiteMaster.objects.filter(tenant=request.user.tenant,
                pk__in=rows.values('shipment_line__shipment__order__country_id'))
            if search:
                options = options.filter(Q(name__icontains=search) | Q(country_code__icontains=search))
            return _page(request, options, lambda obj: {'id': obj.pk, 'name': obj.name, 'country_code': obj.country_code})
        if kind == 'warehouses':
            options = WarehouseMaster.objects.filter(tenant=request.user.tenant,
                pk__in=rows.values('receipt_line__receipt__warehouse_id'))
            if search:
                options = options.filter(Q(name__icontains=search) | Q(code__icontains=search))
            return _page(request, options, lambda obj: {'id': obj.pk, 'name': obj.name, 'country_code': obj.country_code})
        if kind == 'batches':
            options = DispatchBatch.objects.filter(tenant=request.user.tenant,
                pk__in=rows.values('cost_version__batch_id'))
            if search:
                options = options.filter(number__icontains=search)
            return _page(request, options, lambda obj: {'id': obj.pk, 'name': obj.number, 'country_code': obj.country_code_snapshot})
        raise serializers.ValidationError('请选择国家、仓库或批次。')


class CostTargets(InternalAPI):
    def get(self, request):
        kind = request.query_params.get('kind', 'shipment')
        rows = costs.targets(request.user, kind)
        search = request.query_params.get('search', '').strip()
        if search:
            predicate = Q(number__icontains=search)
            if kind == 'shipment':
                predicate |= Q(order__number__icontains=search) | Q(order__supplier__name__icontains=search)
            elif kind == 'batch':
                predicate |= Q(freight_number__icontains=search) | Q(freight_company__name__icontains=search)
            rows = rows.filter(predicate)
        return _page(request, rows.order_by('-pk'), lambda row: costs.target_data(kind, row),
            prepare=lambda page: (costs.prepare_target_parties(kind, page), costs.prepare_target_financials(kind, page)))


class CostContext(InternalAPI):
    def get(self, request, kind, pk):
        return Response({'data': costs.context(request.user, kind, pk)})


class CostFee(InternalAPI):
    def put(self, request, kind, pk):
        costs.save_fee(request.user, kind, pk, validated(FeeInput, request), key(request))
        return Response({'data': costs.context(request.user, kind, pk)})


class CostCalculate(InternalAPI):
    def post(self, request, kind, pk):
        obj = costs.calculate(request.user, kind, pk, validated(CalculationInput, request), key(request))
        return Response({'data': costs.cost_data(obj)})


class CostSettlement(InternalAPI):
    def post(self, request, kind, pk):
        costs.save_settlement(request.user, kind, pk, validated(SettlementInput, request), key(request))
        return Response({'data': costs.context(request.user, kind, pk)})


class CostPayments(InternalAPI):
    def get(self, request, kind, pk):
        return Response({'data': costs.payment_summary(request.user, kind, pk)})

    def post(self, request, kind, pk):
        return Response({'data': costs.create_payment(request.user, kind, pk,
            validated(PaymentInput, request), key(request))}, status=201)



class CostPaymentReverse(InternalAPI):
    def post(self, request, kind, pk, payment_id):
        return Response({'data': costs.reverse_payment(request.user, kind, pk, payment_id,
            validated(ReversalInput, request), key(request))})


class CostPrepaymentApplications(InternalAPI):
    def post(self, request, pk):
        return Response({'data': costs.apply_prepayment(request.user, pk,
            validated(PrepaymentApplicationInput, request), key(request))}, status=201)



class CostPrepaymentApplicationReverse(InternalAPI):
    def post(self, request, pk, application_id):
        return Response({'data': costs.reverse_prepayment_application(request.user, pk, application_id,
            validated(ReversalInput, request), key(request))})


class CostPayeeAccounts(InternalAPI):
    def get(self, request, kind, pk):
        return Response({'data': {'accounts': costs.payee_accounts(request.user, kind, pk)}})

    def post(self, request, kind, pk):
        account = costs.create_payee_account(request.user, kind, pk, validated(PayeeAccountInput, request), key(request))
        return Response({'data': {'account': account}}, status=201)


class CostPayeeAccountDetail(InternalAPI):
    def put(self, request, kind, pk, account_id):
        account = costs.update_payee_account(request.user, kind, pk, account_id, validated(PayeeAccountInput, request), key(request))
        return Response({'data': {'account': account}})


class CostVersionDetail(InternalAPI):
    def get(self, request, kind, pk, sequence):
        return Response({'data': costs.version_for(request.user, kind, pk, sequence)})
