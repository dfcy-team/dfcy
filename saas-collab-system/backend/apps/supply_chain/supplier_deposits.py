"""Supplier deposits and audited transfers to existing purchase prepayments."""
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q, Sum
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.masterdata.models import SupplierMaster
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes

from . import costs, services
from .api import key, validated
from .dates import business_date
from .models import PaymentRecord, PurchaseOrder, SupplierDepositEntry, domain_write
from .payment_request_models import SupplyPaymentRequest
from .permissions import MANAGE, VIEW, internal_orders
from .views import InternalAPI

ZERO = Decimal('0')


def suppliers_for(actor, permission, country_id=None):
    scopes = get_permission_data_scopes(actor, permission)
    can_all = any(scope['scope_type'] == DataScope.ScopeType.ALL for scope in scopes)
    suppliers = SupplierMaster.objects.filter(tenant_id=actor.tenant_id)
    if not can_all:
        # An own-order grant does not grant access to a supplier-wide balance.
        ids = set()
        for scope in scopes:
            if scope['scope_type'] != DataScope.ScopeType.CUSTOM:
                continue
            values = (scope.get('config') or {}).get('supplier_ids', [])
            if isinstance(values, list):
                ids.update(int(value) for value in values if str(value).isdigit())
        suppliers = suppliers.filter(pk__in=ids)
    if country_id:
        orders = internal_orders(actor, PurchaseOrder.objects.filter(country_id=country_id), permission)
        suppliers = suppliers.filter(pk__in=orders.values('supplier_id'))
    return suppliers


class DepositInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SupplierDepositEntry.Kind.values)
    supplier_id = serializers.IntegerField(min_value=1)
    currency = serializers.RegexField(r'^[A-Z]{3}$')
    amount = serializers.DecimalField(max_digits=24, decimal_places=4, min_value=Decimal('0.0001'))
    date = serializers.DateField()
    reference = serializers.CharField(max_length=200)
    notes = serializers.CharField(max_length=10000, allow_blank=True, default='')
    deposit_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    purchase_order_number = serializers.CharField(max_length=80, required=False, allow_blank=True)

    def validate(self, data):
        if (data['kind'] != 'deposit') != bool(data.get('deposit_id')):
            raise serializers.ValidationError('退回或转款须关联原定金。')
        if (data['kind'] == 'transfer') != bool(data.get('purchase_order_number')):
            raise serializers.ValidationError('转采购预付款须填写目标采购单号。')
        return data


def _row(entry, moved=ZERO):
    return {
        'id': entry.pk, 'supplier_id': entry.supplier_id, 'supplier_name': entry.supplier.name,
        'currency': entry.currency, 'amount': str(entry.amount), 'date': entry.date,
        'kind': entry.kind, 'reference': entry.reference, 'notes': entry.notes,
        'deposit_id': entry.deposit_id, 'balance': str(entry.amount - moved) if entry.kind == 'deposit' else None,
        'purchase_order_number': entry.payment.purchase_order.number if entry.payment_id else '',
    }


@transaction.atomic
def record(actor, data, request_key):
    services._internal(actor)
    services._tenant_lock(actor)
    supplier = suppliers_for(actor, MANAGE).filter(pk=data['supplier_id']).first()
    if supplier is None:
        raise NotFound('供应商不可访问。')
    digest = services.request_hash(data)
    prior = SupplierDepositEntry.objects.filter(tenant_id=actor.tenant_id, request_key=request_key).first()
    if prior:
        if prior.request_hash != digest:
            raise serializers.ValidationError('请求标识已用于另一笔业务。')
        return prior
    kind = data['kind']
    amount, currency, day = (data[field] for field in ('amount', 'currency', 'date'))
    if day > business_date():
        raise serializers.ValidationError({'date': '已发生资金的登记日期不得晚于今天。'})
    deposit = payment = None
    if kind != 'deposit':
        deposit = SupplierDepositEntry.objects.filter(tenant_id=actor.tenant_id,
            pk=data['deposit_id'], supplier=supplier, currency=currency, kind='deposit').first()
        if deposit is None:
            raise NotFound('原定金不可访问。')
        if day < deposit.date:
            raise serializers.ValidationError({'date': '处理日期不得早于原定金日期。'})
        used = deposit.movements.aggregate(total=Sum('amount'))['total'] or ZERO
        if amount > deposit.amount - used:
            raise serializers.ValidationError({'amount': '本次金额超过该笔定金可用余额。'})
    if kind in ('deposit', 'refund') and SupplierDepositEntry.objects.filter(
        tenant_id=actor.tenant_id, supplier=supplier, currency=currency, kind=kind, reference=data['reference'],
    ).exists():
        raise serializers.ValidationError({'reference': '同供应商、同币种已登记该凭证号。'})
    with domain_write():
        if kind == 'transfer':
            order = internal_orders(actor, PurchaseOrder.objects.filter(
                supplier=supplier, status='confirmed', number=data['purchase_order_number'],
            ), MANAGE).first()
            if order is None:
                raise NotFound('找不到该供应商下有权限的已下单采购单。')
            costs.validate_payment_currency(actor, 'purchase', order, currency)
            state = costs.payment_summary(actor, 'purchase', order.pk)
            remaining = state['summary']['remaining_amount']
            reserved = SupplyPaymentRequest.objects.filter(
                tenant_id=actor.tenant_id, kind='purchase', source_id=order.pk,
                status='submitted', payment__isnull=True,
            ).exclude(approval__status__in=['rejected', 'withdrawn']).exclude(
                batch__approval__status__in=['rejected', 'withdrawn'],
            ).aggregate(total=Sum('amount'))['total'] or ZERO
            if remaining is None or amount + reserved > Decimal(remaining):
                raise serializers.ValidationError({'amount': '转入金额不得超过目标采购单的剩余应付。'})
            payment = PaymentRecord.objects.create(
                tenant_id=actor.tenant_id, created_by=actor, purchase_order=order, amount=amount,
                date=day, reference_number=data['reference'], notes=data['notes'],
                account_snapshot={'currency': currency},
                idempotency_key='supplier-deposit:' + services.request_hash({'key': request_key}),
            )
        entry = SupplierDepositEntry.objects.create(
            tenant_id=actor.tenant_id, created_by=actor, supplier=supplier, currency=currency, amount=amount,
            date=day, reference=data['reference'], notes=data['notes'], kind=kind, deposit=deposit, payment=payment,
            request_key=request_key, request_hash=digest,
        )
    return entry


class SupplierDeposits(InternalAPI):
    def get(self, request):
        actor = request.user
        country = request.query_params.get('country_id')
        if country and (not country.isdigit() or len(country) > 15):
            raise serializers.ValidationError({'country_id': '国家编号无效。'})
        suppliers = suppliers_for(actor, VIEW, country)
        allowed_manage = check_user_permission(actor, MANAGE)
        writable = suppliers_for(actor, MANAGE, country) if allowed_manage else suppliers.none()
        writable = writable.filter(pk__in=suppliers.values('pk'))
        entries = SupplierDepositEntry.objects.filter(tenant_id=actor.tenant_id, supplier__in=suppliers)
        groups = []
        for row in entries.order_by().values('supplier_id', 'supplier__name', 'currency').annotate(
            paid=Sum('amount', filter=Q(kind='deposit')), refunded=Sum('amount', filter=Q(kind='refund')),
            transferred=Sum('amount', filter=Q(kind='transfer')),
        ).order_by('supplier__name', 'currency'):
            paid, refunded, transferred = [row[field] or ZERO for field in ('paid', 'refunded', 'transferred')]
            groups.append({'supplier_id': row['supplier_id'], 'supplier_name': row['supplier__name'],
                'currency': row['currency'], 'paid': str(paid), 'refunded': str(refunded),
                'transferred': str(transferred), 'balance': str(paid - refunded - transferred)})
        offset = request.query_params.get('offset', '0')
        if not offset.isdigit() or len(offset) > 9:
            raise serializers.ValidationError({'offset': '分页参数无效。'})
        offset = int(offset)
        detailed = entries.select_related('supplier', 'payment__purchase_order').annotate(moved=Sum('movements__amount'))
        page = list(detailed[offset:offset + 20])
        available = detailed.filter(supplier__in=writable, kind='deposit').filter(
            Q(moved__isnull=True) | Q(amount__gt=F('moved')),
        )

        return Response({'data': {'can_manage': writable.exists(), 'groups': groups,
            'suppliers': list(writable.order_by('name').values('id', 'name')),
            'entries': [_row(entry, entry.moved or ZERO) for entry in page],
            'entry_count': entries.count(),
            'available_deposits': [_row(entry, entry.moved or ZERO) for entry in available]}})

    def post(self, request):
        entry = record(request.user, validated(DepositInput, request), key(request))
        moved = entry.movements.aggregate(total=Sum('amount'))['total'] or ZERO
        return Response({'data': _row(entry, moved)})
