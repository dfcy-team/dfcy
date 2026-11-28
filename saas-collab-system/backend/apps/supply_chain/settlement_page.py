"""Evaluate expensive financial base projections once, before Python table operations."""
from decimal import Decimal, localcontext
from .document_time import document_time
from .settlement_table_query import MONEY_FIELDS
Z=Decimal(0)

def financial_page(records,kind,v):
    fields=['pk','number','_party_type','_party_id','_party_name','due','opening_amount','paid_amount','applied_amount','corporate_paid','personal_paid','has_payment_history']
    with localcontext() as ctx:
        ctx.prec=40
        projected=list(records.order_by().values(*fields))
        for r in projected:
            due=r['due'];paid=r['paid_amount'];applied=r['applied_amount'];recorded=paid if kind=='deposit' else paid+applied
            r.update(due_amount=due,recorded=recorded,unknown_paid=paid-r['corporate_paid']-r['personal_paid'],
                remaining_amount=None if due is None else max(due-paid-(Z if kind=='deposit' else applied),Z),
                over_recorded=Z if due is None else max(recorded-due,Z),
                unsettled=None if due is None else max(due-recorded,Z),
                available_prepayment=max(paid-r['opening_amount']-applied,Z) if kind=='deposit' else Z)
        def matches(r):
            if v['status']=='pending' and not(r['due'] is None or r['remaining_amount']>0 or r['over_recorded']>0):return False
            if v['status']=='settled' and not(r['due'] is not None and r['remaining_amount']==0 and r['over_recorded']==0):return False
            n=v.get('payment_nature')
            if n=='mixed' and not(r['corporate_paid']>0 and r['personal_paid']>0):return False
            if n in ('corporate','personal') and r[n+'_paid']<=0:return False
            if n=='unknown' and not(r['unknown_paid']>0 or r['paid_amount']==0):return False
            for f in MONEY_FIELDS:
                for suffix,cmp in [('min',lambda a,b:a>=b),('max',lambda a,b:a<=b)]:
                    val=v.get(f+'_'+suffix)
                    if val is not None and (r[f] is None or not cmp(r[f],val)):return False
            return True
        projected=[r for r in projected if matches(r)]
        target={'supplier':'shipment','domestic':'domestic_freight','carrier':'batch','clearance':'inbound','deposit':'purchase'}[kind]
        rel=('order__country','order__supplier','domestic_carrier') if kind in ('supplier','domestic') else ('batch__country','batch__freight_company') if kind=='clearance' else ('country','supplier') if kind=='deposit' else ('country','freight_company')
        base=records.model.objects.filter(pk__in=[r['pk'] for r in projected]).select_related(*rel)
        objects={o.pk:o for o in base}
        for r in projected:
            o=objects[r['pk']];country=o.order.country if kind in ('supplier','domestic') else o.batch.country if kind=='clearance' else o.country
            r['country_name']=country.name;r['party_name']=r['_party_name'];r['document_time']=document_time(target,o)
        start=str(v.get('document_from') or '');end=str(v.get('document_to') or '')
        projected=[r for r in projected if(not start or r['document_time'] and r['document_time'][:10]>=start) and(not end or r['document_time'] and r['document_time'][:10]<=end)]
        key=v.get('sort_by');desc=v.get('sort_order')=='descending'
        if key:
            known=sorted((r for r in projected if r.get(key) is not None and r.get(key)!=''),key=lambda r:r['pk'],reverse=bool(key=='document_time' and desc))
            known.sort(key=lambda r:r[key],reverse=desc)
            projected=known+sorted((r for r in projected if r.get(key) is None or r.get(key)==''),key=lambda r:r['pk'])
        else:projected.sort(key=lambda r:r['pk'],reverse=True)
        summary={'documents':len(projected),'unknown_documents':sum(r['due'] is None for r in projected)}
        for f in ['due_amount','opening_amount','paid_amount','applied_amount','remaining_amount','available_prepayment','corporate_paid','personal_paid','unknown_paid']:
            summary[f]=str(sum((r[f] or Z for r in projected),Z))
        page=[]
        for r in projected[v['offset']:v['offset']+v['limit']]:
            o=objects[r['pk']]
            for k,val in r.items():
                if k not in ('pk','number','country_name','party_name','document_time'):setattr(o,k,val)
            page.append(o)
        return len(projected),summary,page
