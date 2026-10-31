"""Read-only reminder queries: scope, compute, filter, then paginate in SQL."""
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db.models import Case, CharField, Count, DateField, DateTimeField, F, Func, IntegerField, Max, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, NullIf, TruncDate
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from . import dashboard, dispatch_allocations
from .cost_models import PaymentTermsRecord
from .dates import business_date
from .models import DispatchMembership, ShipmentLine
from .views import InternalAPI

KINDS={'shipment':'supplier','domestic_freight':'domestic','batch':'carrier','inbound':'clearance'}


class AddDays(Func):
    output_field=DateField()
    def as_sql(self, compiler, connection, **extra_context):
        left, lp=compiler.compile(self.source_expressions[0])
        right, rp=compiler.compile(self.source_expressions[1])
        if connection.vendor=='mysql':
            sql=f'DATE_ADD({left}, INTERVAL {right} DAY)'
        elif connection.vendor=='sqlite':
            sql=f"DATE({left}, CAST({right} AS TEXT) || ' days')"
        else:
            sql=f'({left} + {right})'
        return sql, [*lp,*rp]


def reminder_query(actor, kind, country_id=None):
    if kind not in KINDS:
        raise ValidationError('不支持该账期单据类型。')
    query=dashboard._money_targets(KINDS[kind], dashboard.scope(actor,country_id))
    owner='shipment' if kind=='domestic_freight' else kind
    record=PaymentTermsRecord.objects.filter(tenant_id=actor.tenant_id,kind=kind,**{f'{owner}_id':OuterRef('pk')})
    snapshot={'shipment':'order__supplier_terms_snapshot','domestic_freight':'domestic_terms_snapshot',
        'batch':'freight_terms_snapshot','inbound':'batch__freight_terms_snapshot'}[kind]
    def frozen(key, output):
        return Cast(NullIf(KeyTextTransform(key,F(snapshot)),Value('null')),output)
    query=query.annotate(_terms_id=Subquery(record.values('current_revision_id')[:1]),
        _reconciliation=Subquery(record.values('current_revision__reconciliation_date')[:1],output_field=DateField()),
        _due_override=Subquery(record.values('current_revision__due_date_override')[:1],output_field=DateField()))
    fields={}
    for key, output in [('days',IntegerField()),('start',CharField()),('reminder_days',IntegerField())]:
        fallback=frozen(key,output)
        if key=='reminder_days':
            fallback=Coalesce(fallback,Value(7))
        fields[f'terms_{key if key!="reminder_days" else "reminder"}']=Case(
            When(_terms_id__isnull=False,then=Subquery(record.values(f'current_revision__{key}')[:1],output_field=output)),
            default=fallback,output_field=output)
    query=query.annotate(**fields)
    tz=ZoneInfo(getattr(settings,'SUPPLY_CHAIN_TIME_ZONE','Asia/Shanghai'))
    if kind in ('shipment','domestic_freight'):
        allocation=dispatch_allocations.active().filter(shipment_line__shipment_id=OuterRef('pk'),shipment_line__is_active=True).order_by().values('shipment_line__shipment_id')
        allocation=allocation.annotate(total=Sum('quantity'),missing=Count('pk',filter=Q(membership__batch__arrived_warehouse_at__isnull=True)),last=Max('membership__batch__arrived_warehouse_at'))
        lines=ShipmentLine.objects.filter(shipment_id=OuterRef('pk'),is_active=True).order_by().values('shipment_id').annotate(total=Sum('quantity'))
        query=query.annotate(_allocated=Subquery(allocation.values('total')[:1]),_expected=Subquery(lines.values('total')[:1]),
            _missing=Subquery(allocation.values('missing')[:1]),_last_arrival=Subquery(allocation.values('last')[:1],output_field=DateTimeField()))
        warehouse=Case(When(_allocated=F('_expected'),_missing=0,then=TruncDate('_last_arrival',tzinfo=tz)),default=Value(None),output_field=DateField())
        shipment=F('shipment_date')
        collection=TruncDate('collection_arrived_at',tzinfo=tz)
    else:
        batch_ref='pk' if kind=='batch' else 'batch_id'
        members=DispatchMembership.objects.filter(batch_id=OuterRef(batch_ref),active_guard=True).order_by().values('batch_id').annotate(
            ship=Max('shipment__shipment_date'),collect=Max('shipment__collection_arrived_at'),
            missing=Count('pk',filter=Q(shipment__collection_arrived_at__isnull=True)))
        query=query.annotate(_shipment_date=Subquery(members.values('ship')[:1],output_field=DateField()),
            _collection_date=Subquery(members.values('collect')[:1],output_field=DateTimeField()),
            _missing_collection=Subquery(members.values('missing')[:1]))
        shipment=F('_shipment_date')
        collection=Case(When(_missing_collection=0,then=TruncDate('_collection_date',tzinfo=tz)),default=Value(None),output_field=DateField())
        warehouse=TruncDate('arrived_warehouse_at' if kind=='batch' else 'batch__arrived_warehouse_at',tzinfo=tz)
    query=query.annotate(terms_anchor=Case(
        When(terms_start='reconciliation_date',then=F('_reconciliation')),
        When(terms_start='shipment_date',then=shipment),
        When(terms_start='collection_arrival',then=collection),
        When(terms_start='warehouse_arrival',then=warehouse),default=Value(None),output_field=DateField()))
    query=query.annotate(terms_due=Coalesce(F('_due_override'),AddDays(F('terms_anchor'),F('terms_days'))))
    today=business_date()
    return query.annotate(terms_status=Case(
        When(remaining_amount=0,then=Value('settled')),
        When(Q(terms_due__isnull=True)|Q(remaining_amount__isnull=True),then=Value('unknown')),
        When(terms_due__lt=today,then=Value('overdue')),
        When(terms_due__lte=AddDays(Value(today,output_field=DateField()),F('terms_reminder')),then=Value('due_soon')),
        default=Value('scheduled'),output_field=CharField()))


class ReminderQuery(serializers.Serializer):
    kind=serializers.ChoiceField(choices=tuple(KINDS),default='shipment')
    country_id=serializers.IntegerField(min_value=1,required=False)
    status=serializers.ChoiceField(choices=('all','overdue','due_soon','unknown'),default='overdue')
    limit=serializers.IntegerField(min_value=1,max_value=50,default=20)
    offset=serializers.IntegerField(min_value=0,default=0)


class PaymentReminders(InternalAPI):
    http_method_names=['get','head','options']
    def get(self,request):
        params=ReminderQuery(data=request.query_params)
        params.is_valid(raise_exception=True)
        v=params.validated_data
        query=reminder_query(request.user,v['kind'],v.get('country_id')).exclude(terms_status='settled')
        if v['status']!='all':
            query=query.filter(terms_status=v['status'])
        summary=query.aggregate(documents=Count('pk'),total_remaining=Sum('remaining_amount'))
        rows=[]
        for obj in query.order_by(F('terms_due').asc(nulls_last=True),'pk')[v['offset']:v['offset']+v['limit']]:
            rows.append({'id':obj.pk,'kind':v['kind'],'number':obj.number,'country_name':obj._country_name,
                'party_name':obj._party_name,'anchor_date':obj.terms_anchor,'due_date':obj.terms_due,
                'remaining_amount':None if obj.remaining_amount is None else str(obj.remaining_amount),
                'status':obj.terms_status,'href':f'/supply-chain/costs?kind={v["kind"]}&id={obj.pk}'})
        return Response({'data':rows,'count':summary['documents'],'summary':{
            'documents':summary['documents'],'remaining_amount':str(summary['total_remaining'] or 0)},
            'limit':v['limit'],'offset':v['offset']})
