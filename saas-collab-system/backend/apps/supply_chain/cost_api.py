from .serializers import VersionInput
from decimal import Decimal
from django.db.models import Exists, OuterRef, Q
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


class FeeCostExchangeInput(serializers.Serializer):
    currency = serializers.RegexField(r'^[A-Z]{3}$')
    rate_date = serializers.DateField(required=False)


class FeeInput(SourceVersion):
    cost_exchange = FeeCostExchangeInput(required=False)
    expected_version = serializers.IntegerField(min_value=0)
    amount = serializers.DecimalField(max_digits=20, decimal_places=4, min_value=0)
    state = serializers.ChoiceField(choices=['estimated', 'confirmed'])
    method = serializers.ChoiceField(choices=['volume', 'weight', 'mixed'])
    volume_percent = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, allow_null=True)
    billed_cbm = serializers.DecimalField(max_digits=16, decimal_places=6, min_value=0, allow_null=True, default=None)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default='')
    reason = serializers.CharField(max_length=10000)
    measurements = MeasurementInput(many=True, required=False)
    item_breakdown = serializers.ListField(child=serializers.DictField(), required=False)

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
    fee_item_id = serializers.IntegerField(min_value=1, required=False)
    currency = serializers.RegexField(r'^[A-Z]{3}$', required=False)


class PrepaymentApplicationInput(serializers.Serializer):
    cross_order = serializers.BooleanField(required=False)
    target_purchase_order_id = serializers.IntegerField(min_value=1, required=False)
    payment_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('0.0001'))
    date = serializers.DateField()
    expected_version = serializers.IntegerField(min_value=0)


class ShipmentDiscountInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=20, decimal_places=4, min_value=Decimal('0.0001'))
    source_reference = serializers.CharField(max_length=160)
    reason = serializers.CharField(max_length=10000)


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
        if kind == 'inbound':
            rows = rows.exclude(
                ~Q(payment_records__isnull=False),
                status='draft',
                clearance_fee_record__current_revision__isnull=True,
            )
        search = request.query_params.get('search', '').strip()
        if search:
            predicate = Q(number__icontains=search)
            if kind == 'shipment':
                predicate |= Q(order__number__icontains=search) | Q(order__supplier__name__icontains=search)
                from .models import ShipmentLine
                product_match = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True).filter(
                    Q(sku_code_snapshot__icontains=search) | Q(product_name_snapshot__icontains=search)
                    | Q(sku__sku_code__icontains=search) | Q(sku__legacy_sku_code__icontains=search)
                    | Q(sku__product_name__icontains=search) | Q(sku__spu__spu_code__icontains=search) | Q(sku__spu__product_name__icontains=search))
                rows = rows.annotate(_search_product_match=Exists(product_match))
                predicate |= Q(_search_product_match=True)
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


class PaymentTermsInput(serializers.Serializer):
    days = serializers.IntegerField(min_value=0, max_value=3650, allow_null=True, required=False, default=None)
    start = serializers.ChoiceField(choices=['unspecified','shipment_date','collection_arrival','warehouse_arrival','reconciliation_date'])
    reminder_days = serializers.IntegerField(min_value=0, max_value=365, default=7)
    reconciliation_date = serializers.DateField(required=False, allow_null=True)
    due_date_override = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=10000)
    expected_version = serializers.IntegerField(min_value=0)


class CostPaymentTerms(InternalAPI):
    def get(self, request, kind, pk):
        from .payment_terms import terms_data
        return Response({'data': terms_data(request.user, kind, pk)})

    def put(self, request, kind, pk):
        from .payment_terms import save_terms, terms_data
        save_terms(request.user, kind, pk, validated(PaymentTermsInput, request), key(request))
        return Response({'data': terms_data(request.user, kind, pk)})


class PaymentPlanLine(serializers.Serializer):
    line_id = serializers.CharField(max_length=64, required=False)
    nature = serializers.ChoiceField(choices=['corporate','personal'])
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('0.0001'))
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
    fee_item_id = serializers.IntegerField(required=False, allow_null=True)


class PaymentPlanInput(serializers.Serializer):
    expected_source_version = serializers.IntegerField(min_value=1)
    expected_version = serializers.IntegerField(min_value=0)
    lines = PaymentPlanLine(many=True, max_length=100)
    reason = serializers.CharField(max_length=1000)
    currency = serializers.RegexField(r'^[A-Z]{3}$')


class CostPaymentPlans(InternalAPI):
    def get(self, request, kind, pk):
        from .payment_plans import plan_data
        return Response({'data': plan_data(request.user, kind, pk)})

    def post(self, request, kind, pk):
        from .payment_plans import save_plan, plan_data
        payload = validated(PaymentPlanInput, request)
        save_plan(request.user, kind, pk, payload, key(request))
        return Response({'data': plan_data(request.user, kind, pk)})


class PayableClassificationInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=0)
    expected_source_version = serializers.IntegerField(min_value=1)
    expected_payable_amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=0)
    currency = serializers.RegexField(r'^[A-Z]{3}$')
    corporate_amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=0)
    personal_amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=0)
    reason = serializers.CharField(max_length=1000)


class CostPayableClassification(InternalAPI):
    def get(self, request, kind, pk):
        from .payable_classifications import classification_data
        return Response({'data': classification_data(request.user, kind, pk)})

    def post(self, request, kind, pk):
        from .payable_classifications import save_classification, classification_data
        payload = validated(PayableClassificationInput, request)
        save_classification(request.user, kind, pk, payload, key(request))
        return Response({'data': classification_data(request.user, kind, pk)})

class PaymentClassificationLine(serializers.Serializer):
    nature = serializers.ChoiceField(choices=['corporate','personal'])
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('0.0001'))


class PaymentClassificationInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=0)
    allocations = PaymentClassificationLine(many=True, max_length=2)
    reason = serializers.CharField(max_length=1000)


class CostPaymentClassification(InternalAPI):
    def get(self, request, kind, pk, entry_type, entry_id):
        from .payment_classification import classification_data
        return Response({'data': classification_data(request.user, kind, pk, entry_type, entry_id)})

    def put(self, request, kind, pk, entry_type, entry_id):
        from .payment_classification import save_classification, classification_data
        payload = validated(PaymentClassificationInput, request)
        save_classification(request.user, kind, pk, entry_type, entry_id, payload, key(request))
        return Response({'data': classification_data(request.user, kind, pk, entry_type, entry_id)})


class PaymentCurrencyInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=0)
    currency = serializers.RegexField(r'^[A-Z]{3}$')
    reason = serializers.CharField(max_length=1000)


class CostPaymentCurrency(InternalAPI):
    def get(self, request, kind, pk, entry_type, entry_id):
        from .payment_currencies import currency_data
        return Response({'data': currency_data(request.user, kind, pk, entry_type, entry_id)})

    def put(self, request, kind, pk, entry_type, entry_id):
        from .payment_currencies import save_currency, currency_data
        payload=validated(PaymentCurrencyInput,request)
        if not payload['reason'].strip(): raise ValidationError({'reason':'补充原因必填。'})
        save_currency(request.user,kind,pk,entry_type,entry_id,payload,key(request))
        return Response({'data':currency_data(request.user,kind,pk,entry_type,entry_id)})

class CostPayments(InternalAPI):
    def get(self, request, kind, pk):
        return Response({'data': costs.payment_summary(request.user, kind, pk)})

    def post(self, request, kind, pk):
        return Response({'data': costs.create_payment(request.user, kind, pk,
            validated(PaymentInput, request), key(request))}, status=201)


class CostShipmentDiscountAdjustment(InternalAPI):
    http_method_names = ['post', 'options']

    def post(self, request, pk):
        costs.record_shipment_discount_adjustment(request.user, pk,
            validated(ShipmentDiscountInput, request), key(request))
        return Response({'data': costs.payment_summary(request.user, 'shipment', pk)}, status=201)



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
    def delete(self, request, kind, pk, account_id):
        data = validated(VersionInput, request)
        costs.delete_supplier_payee_account(request.user, kind, pk, account_id, data['expected_version'], key(request))
        return Response({'data': {'id': account_id}})

    def put(self, request, kind, pk, account_id):
        account = costs.update_payee_account(request.user, kind, pk, account_id, validated(PayeeAccountInput, request), key(request))
        return Response({'data': {'account': account}})


class CostVersionDetail(InternalAPI):
    def get(self, request, kind, pk, sequence):
        return Response({'data': costs.version_for(request.user, kind, pk, sequence)})
