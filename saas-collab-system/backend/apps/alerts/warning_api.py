"""Read-only, paginated access to atomically published warning snapshots."""
from django.db import transaction
from django.db.models import Q, Count
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework import serializers
from apps.common.responses import success_response
from apps.commerce import country_decisions as domain
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from .permissions import IsAlertViewer, IsAlertEvaluator
from .models import InventoryWarningRun, InventoryWarningRow

FLAGS = ('forecast_stockout','key_variant_shortage','supply_risk','excess_stock','new_product')

class Query(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1, required=False)
    spu_id = serializers.IntegerField(min_value=1, required=False)
    search = serializers.CharField(max_length=200, default='', allow_blank=True)
    warning_type = serializers.ChoiceField(choices=['all',*FLAGS], default='all')
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.ChoiceField(choices=[20,50,100], default=20)


def require_country_scope(actor, country):
    # Shared tenant snapshots contain all stores/warehouses in a country.
    # Partial store/warehouse access must never expose their aggregates.
    if actor.is_superuser:
        return
    for code, resource in ((domain.INVENTORY,'commerce.inventory'),(domain.SALES,'sales_management.sales'),
                           ('sales_management.supply_summary.view','sales_management.supply_summary')):
        scopes = get_permission_data_scopes(actor,code,resource_code=resource)
        full = any(s['scope_type']=='all' for s in scopes)
        if code.endswith('supply_summary.view'):
            full |= any(s['scope_type']=='custom' and set(s.get('config') or {})=={'site_ids'} and
                        country.pk in s['config']['site_ids'] for s in scopes)
        if not check_user_permission(actor,code) or not full:
            raise PermissionDenied('此预警汇总需要完整国家库存、销售和供应查看范围；原有预警跟进仍可按授权范围查看。')
    alert_scopes = get_permission_data_scopes(actor,'alerts.view')
    if not any(s['scope_type']=='all' for s in alert_scopes):
        raise PermissionDenied('此整款预警需要完整库存预警查看范围。')


@api_view(['GET'])
@permission_classes([IsAlertViewer])
def warning_list(request):
    form=Query(data=request.query_params);form.is_valid(raise_exception=True);q=form.validated_data
    countries=list(domain.countries_for(request.user))
    options=[{'id':c.pk,'name':c.name,'country_code':c.country_code} for c in countries]
    if not q.get('country_id'):
        return success_response({'countries':options,'results':[],'count':0,'summary':None,'status':'select_country'})
    country=domain.country_for(request.user,q['country_id']);require_country_scope(request.user,country)
    run=InventoryWarningRun.objects.filter(tenant=request.user.tenant,country=country,status__in=['ready','partial']).order_by('-completed_at','-pk').first()
    latest=InventoryWarningRun.objects.filter(tenant=request.user.tenant,country=country).order_by('-pk').first()
    meta={'countries':options,'run_id':run.pk if run else None,'status':run.status if run else 'unavailable',
          'updated_at':run.completed_at if run else None,'latest_status':latest.status if latest else None,
          'issues':run.issues if run else [],'config':{k:v for k,v in run.config.items() if k!='spu_summaries'} if run else {}}
    if not run:
        return success_response({**meta,'results':[],'count':0,'summary':None})
    rows=InventoryWarningRow.objects.filter(run=run)
    if q['search']:
        value=q['search'];matching=rows.filter(Q(sku__sku_code__icontains=value)|Q(sku__legacy_sku_code__icontains=value)|
           Q(sku__product_name__icontains=value)|Q(spu__spu_code__icontains=value)|Q(spu__legacy_spu_code__icontains=value))
        rows=rows.filter(spu_id__in=matching.values('spu_id'))
    summary=rows.aggregate(total=Count('spu_id',distinct=True),**{f:Count('spu_id',filter=Q(**{f:True}),distinct=True) for f in FLAGS})
    if q.get('spu_id'):
        # Always show every sibling, including healthy variants, for comparison.
        rows=rows.filter(spu_id=q['spu_id'])
        payload=list(rows.order_by('sku__sku_code','sku_id').values_list('payload',flat=True))
        from apps.sales_management.abc_access import decorate_rows
        meta['abc_meta']=decorate_rows(request.user,country,payload)
        return success_response({**meta,'results':payload,'count':len(payload),'summary':summary})
    matched=rows.filter(**{q['warning_type']:True}) if q['warning_type']!='all' else rows
    ids=list(matched.order_by('spu_id').values_list('spu_id',flat=True).distinct());count=len(ids)
    cached=run.config.get('spu_summaries') or {}
    from apps.masterdata.models import InventoryABCEntry
    grades=dict(InventoryABCEntry.objects.filter(run_id=run.config.get('abc_run_id'),entity_type='spu',entity_id__in=ids).values_list('entity_id','grade'))
    def priority(spu_id):
        summary=cached.get(str(spu_id),{});flags=summary.get('warnings',[])
        risk=0 if 'forecast_stockout' in flags else 1 if 'supply_risk' in flags else 2 if 'excess_stock' in flags else 3
        return (risk,summary.get('first_shortage_date') or '9999-12-31',0 if 'key_variant_shortage' in flags else 1,{'A':0,'B':1,'C':2}.get(grades.get(spu_id),3),spu_id or 0)
    ids.sort(key=priority)
    page=int(q['page']);size=int(q['page_size'])
    page_ids=ids[(page-1)*size:page*size]
    grouped=run.config.get('spu_summaries')
    if grouped is None:
        from .warning_presentation import summarize_spus
        siblings=list(rows.filter(spu_id__in=page_ids).order_by('spu_id','sku_id').values('spu_id','payload',*FLAGS))
        grouped=summarize_spus(siblings)
    results=[grouped[str(k)] for k in page_ids if str(k) in grouped]
    from apps.sales_management.abc_access import decorate_rows
    meta['abc_meta']=decorate_rows(request.user,country,results)
    return success_response({**meta,'results':results,'count':count,'summary':summary})


@api_view(['POST'])
@permission_classes([IsAlertEvaluator])
def warning_rebuild(request):
    form=Query(data=request.data);form.is_valid(raise_exception=True)
    if not form.validated_data.get('country_id'):
        raise serializers.ValidationError({'country_id':'请选择国家。'})
    country=domain.country_for(request.user,form.validated_data['country_id']);require_country_scope(request.user,country)
    from apps.masterdata.models import StoreMaster
    from apps.supply_chain.models import ReplenishmentStrategy
    from apps.sales_management.inventory_batches import latest_complete_inventory_runs
    if not StoreMaster.objects.filter(tenant=request.user.tenant,country_code__iexact=country.country_code,status='active').exists() or not ReplenishmentStrategy.objects.filter(tenant=request.user.tenant,country=country,active=True).exists():
        raise serializers.ValidationError('该国家需先配置有效店铺和补货策略。')
    if not latest_complete_inventory_runs(request.user.tenant_id,country.country_code):
        raise serializers.ValidationError('该国家尚无已完成的仓库库存批次，请先完成库存采集。')
    with transaction.atomic():
        type(country).objects.select_for_update().get(pk=country.pk)
        run=InventoryWarningRun.objects.filter(tenant=request.user.tenant,country=country,status__in=['queued','building']).order_by('-pk').first()
        if not run:run=InventoryWarningRun.objects.create(tenant=request.user.tenant,country=country,status='queued',config={'requested_by':request.user.pk})
    return success_response({'run_id':run.pk,'status':run.status})
