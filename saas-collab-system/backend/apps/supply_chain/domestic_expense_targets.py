"""Scoped payable list for independently billed domestic expenses."""
from django.db.models import Q
from rest_framework.response import Response
from .document_time import document_time
from .permissions import VIEW
from . import shipments


def targets(request):
    from .domestic_expense_models import DomesticExpenseGroup
    from .shipment_sources import accessible_shipments
    from .permissions import internal_orders
    from .models import PurchaseOrder
    from .costs import payment_summary
    from .views import _page

    orders = internal_orders(request.user, PurchaseOrder.objects.all(), VIEW)
    query = DomesticExpenseGroup.objects.filter(
        tenant_id=request.user.tenant_id, is_active=True,
        shipment__in=accessible_shipments(orders),
    ).select_related('shipment__order__country', 'supplier', 'carrier')
    search = request.query_params.get('search', '').strip()[:160]
    if search:
        query = query.filter(Q(shipment__number__icontains=search) | Q(supplier__name__icontains=search)
                             | Q(carrier__name__icontains=search))
    def render(group):
        summary = payment_summary(request.user, 'domestic_expense', group.pk)['summary']
        party = group.supplier or group.carrier
        order = group.shipment.order
        return {'id': group.pk, 'kind': 'domestic_expense', 'number': group.shipment.number,
                'version': group.version, 'document_time': document_time('domestic_freight', group.shipment),
                'country_code': order.country_code_snapshot, 'country_name': order.country.name,
                'supplier_names': party.name, 'currency': group.currency,
                'stage': group.shipment.status,
                'due_amount': summary['due_amount'], 'paid_amount': summary['paid_amount'],
                'remaining_amount': summary['remaining_amount']}
    return _page(request, query, render)
