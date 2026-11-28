"""Whitelisted settlement table filters, applied before totals and pagination."""
from decimal import Decimal
from django.db.models import F, Q, Case, When, IntegerField
from .document_time import document_time
MONEY_FIELDS = ('due_amount','opening_amount','paid_amount','applied_amount','remaining_amount')
SORT_FIELDS = ('number','document_time','country_name','party_name') + MONEY_FIELDS

def apply_table_query(records, kind, values):
    financial = kind in ('supplier','domestic','carrier','clearance','deposit')
    if not financial: return records, ['-pk']
    country = 'order__country__name' if kind in ('supplier','domestic') else 'batch__country__name' if kind == 'clearance' else 'country__name'
    if values.get('column_number'): records=records.filter(number__icontains=values['column_number'])
    if values.get('column_country'): records=records.filter(**{country+'__icontains':values['column_country']})
    if values.get('column_party'): records=records.filter(_party_name__icontains=values['column_party'])
    for field in MONEY_FIELDS:
        dbfield='due' if field=='due_amount' else field
        for suffix,lookup in [('min','gte'),('max','lte')]:
            value=values.get(field+'_'+suffix)
            if value is not None: records=records.filter(**{dbfield+'__'+lookup:value})
    key=values.get('sort_by'); descending=values.get('sort_order')=='descending'
    if key=='document_time' or values.get('document_from') or values.get('document_to'):
        target={'supplier':'shipment','domestic':'domestic_freight','carrier':'batch','clearance':'inbound','deposit':'purchase'}[kind]
        projected=[(obj.pk, document_time(target,obj)) for obj in records]
        start=str(values.get('document_from') or '');end=str(values.get('document_to') or '')
        projected=[(pk,date) for pk,date in projected if (not start or date and date[:10]>=start) and (not end or date and date[:10]<=end)]
        records=records.filter(pk__in=[pk for pk,_ in projected])
        if key=='document_time':
            known=sorted(((pk,date) for pk,date in projected if date),key=lambda x:(x[1],x[0]),reverse=descending)
            ids=[pk for pk,_ in known]+sorted(pk for pk,date in projected if not date)
            if not ids:return records, ['pk']
            records=records.annotate(_table_position=Case(*[When(pk=pk,then=index) for index,pk in enumerate(ids)],output_field=IntegerField()))
            return records, ['_table_position','pk']
    fields={'number':'number','country_name':country,'party_name':'_party_name',**{f:('due' if f=='due_amount' else f) for f in MONEY_FIELDS}}
    if key in fields:
        expression=F(fields[key]);return records, [expression.desc(nulls_last=True) if descending else expression.asc(nulls_last=True),'pk']
    return records, ['-pk']
