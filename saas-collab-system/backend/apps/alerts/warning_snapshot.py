from datetime import date, timedelta
from zoneinfo import ZoneInfo
try:
    from .warning_math import assess_sku, assess_spu
except ImportError:
    from warning_math import assess_sku, assess_spu

def spu_key_shortage_ids(payloads):
    siblings={}
    for row in payloads:
        siblings.setdefault(row.get('spu_id'),[]).append({'sku_id':row['sku_id'],'sales_quantity':row.get('total_demand_quantity'),'warning':row['warning']})
    result=set()
    for spu_id,rows in siblings.items():
        if spu_id and all(row['sales_quantity'] is not None for row in rows):result.update(assess_spu(rows)['key_shortage_sku_ids'])
    return result


def change_token(tenant_id, country):
    """Cheap invalidation token; actual values are recomputed only in workers."""
    from django.apps import apps
    from django.db.models import Max, Count
    from django.utils import timezone
    from zoneinfo import ZoneInfo
    from apps.commerce.models import SalesOrder
    from apps.masterdata.models import StoreMaster, InventoryObservationSettings, InventoryABCRun
    from apps.supply_chain.models import ReplenishmentStrategy
    day=timezone.now().astimezone(ZoneInfo(country.timezone)).date().isoformat()
    stores=StoreMaster.objects.filter(tenant_id=tenant_id,country_code__iexact=country.country_code).values('pk')
    start=timezone.now().astimezone(ZoneInfo(country.timezone)).replace(hour=0,minute=0,second=0,microsecond=0)
    sales=SalesOrder.objects.filter(tenant_id=tenant_id,store_id__in=stores,paid_at_utc__lt=start).aggregate(latest=Max('ingested_at'),last_id=Max('pk'))
    state={'policy_version':'inventory-warning-v1','business_day':day,'sales':sales,'supply':{},'observation':list(InventoryObservationSettings.objects.filter(tenant_id=tenant_id).values('new_product_observation_days')),'abc_run_id':InventoryABCRun.objects.filter(tenant_id=tenant_id,country=country,status__in=['ready','partial']).order_by('-completed_at').values_list('pk',flat=True).first(),'strategy':list(ReplenishmentStrategy.objects.filter(tenant_id=tenant_id,country=country).values('pk','version','active'))}
    for name in ('PurchaseOrder','PurchaseLine','Shipment','ShipmentLine','DispatchBatch','DispatchAllocation','InternalStockReceipt','InternalStockReceiptLine','WmsReceiptAllocation'):
        try:model=apps.get_model('supply_chain',name)
        except LookupError:continue
        fields={f.name for f in model._meta.fields}
        if 'tenant' not in fields:continue
        measures={'count':Count('pk'),'last_id':Max('pk')}
        if 'updated_at' in fields:measures['latest']=Max('updated_at')
        if 'version' in fields:measures['version']=Max('version')
        state['supply'][name]=model.objects.filter(tenant_id=tenant_id).aggregate(**measures)
    from django.core.serializers.json import DjangoJSONEncoder
    import hashlib,json
    return hashlib.sha256(json.dumps(state,sort_keys=True,cls=DjangoJSONEncoder).encode()).hexdigest()

def calculate_country(actor,country,*,batch_size=200,run=None):
    from django.db import transaction
    from django.utils import timezone
    from django.db.models import Q
    from django.core.serializers.json import DjangoJSONEncoder
    import json, hashlib
    from decimal import Decimal
    from apps.products.models import ProductSKU
    from apps.masterdata.models import InventoryObservationSettings
    from apps.supply_chain.models import ReplenishmentStrategy
    from apps.supply_chain.replenishment import evaluate_replenishment_row
    from apps.sales_management.inventory_queries import latest_country_inventory
    from apps.masterdata.models import InventoryABCRun, InventoryABCEntry
    from apps.alerts.models import InventoryWarningRun, InventoryWarningRow
    from apps.commerce import country_decisions as domain
    country=domain.country_for(actor,country.pk);domain.require_metrics(actor)
    # Include all active physical catalog SKUs. The country decision service
    # reads latest complete inventory and its relevant sales/supply facts.
    def source_rows():
        return list(latest_country_inventory(domain._country_inventory_source(actor,country,timezone.now())).order_by('pk').values('pk','source_run_id','warehouse_id','internal_sku_id','available_qty','on_hand_qty'))
    def signature(values):
        return hashlib.sha256(json.dumps(values,sort_keys=True,cls=DjangoJSONEncoder).encode()).hexdigest()
    initial_stock=source_rows(); initial_signature=signature(initial_stock)
    initial_change_token=change_token(actor.tenant_id,country)
    stock_ids={x['internal_sku_id'] for x in initial_stock if x['internal_sku_id'] and ((x['available_qty'] or 0)>0 or (x['on_hand_qty'] or 0)>0)}
    skus=list(ProductSKU.objects.filter(tenant_id=actor.tenant_id).exclude(inventory_type='virtual').select_related('spu').only('id','tenant_id','spu_id','sku_code','legacy_sku_code','inventory_type','product_type','product_name','image_url','spu__id','spu__product_name','spu__spu_code','spu__legacy_spu_code').order_by('pk'))
    strategy=ReplenishmentStrategy.objects.filter(tenant_id=actor.tenant_id,country=country,active=True).first()
    settings=InventoryObservationSettings.objects.filter(tenant_id=actor.tenant_id).first()
    observation_days=settings.new_product_observation_days if settings else 30
    abc=InventoryABCRun.objects.filter(tenant_id=actor.tenant_id,country=country,status__in=['ready','partial']).order_by('-cutoff_date','-completed_at','-pk').first()
    first_dates={e.entity_id:e.first_sale_date for e in InventoryABCEntry.objects.filter(run=abc,entity_type='sku',entity_id__in=[s.pk for s in skus])} if abc else {}
    today=timezone.now().astimezone(ZoneInfo(country.timezone)).date()
    config={'inventory_run_ids':sorted({x['source_run_id'] for x in initial_stock}),'sales_end':str(today-timedelta(days=1)),'observation_days':observation_days,'change_token':initial_change_token,'horizon_days':strategy.lead_days+strategy.cycle_days+strategy.safety_days if strategy else 60,'key_sales_share':'0.80','abc_run_id':abc.pk if abc else None,'strategy_id':strategy.pk if strategy else None,'strategy_version':strategy.version if strategy else None,'inventory_signature':initial_signature,'unmapped_stock_records':sum(1 for x in initial_stock if not x['internal_sku_id'] and ((x['available_qty'] or 0)>0 or (x['on_hand_qty'] or 0)>0))}
    with transaction.atomic():
        type(country).objects.select_for_update().get(pk=country.pk)
        if InventoryWarningRun.objects.filter(tenant_id=actor.tenant_id,country=country,status='building').exists():
            raise RuntimeError('country_warning_build_already_running')
        run=InventoryWarningRun.objects.select_for_update().get(pk=run.pk) if run else InventoryWarningRun.objects.create(tenant_id=actor.tenant_id,country=country,status='queued')
        if run.status != 'queued':
            raise RuntimeError('warning_run_not_queued')
        run.status='building';run.config={**run.config,**config};run.save(update_fields=['status','config'])
    payloads=[];issues=set(); sku_by_id={s.pk:s for s in skus}
    try:
        from apps.sales_management.inventory_batches import latest_complete_inventory_runs
        if not strategy:raise RuntimeError('replenishment_strategy_missing')
        if not latest_complete_inventory_runs(actor.tenant_id,country.country_code):raise RuntimeError('complete_inventory_batch_missing')
        sales_data=domain.sales_windows(actor,country,[sku.pk for sku in skus],(7,15,30,90),end_date=today-timedelta(days=1)) if skus else {}
        from apps.commerce.supply_pipeline import pipeline_for
        pipelines=pipeline_for(actor,country,[sku.pk for sku in skus],today=today,target_days=config['horizon_days']) if skus else {}
        relevant_ids=set(stock_ids)
        for observed in sales_data.values():relevant_ids.update(k for k,v in observed['units_by_sku'].items() if v>0)
        relevant_ids.update(k for k,pipe in pipelines.items() if any(Decimal(str(pipe.get(field) or 0))>0 for field in ('production_unshipped','effective_incoming','unknown_eta')))
        relevant_spu_ids={sku.spu_id for sku in skus if sku.pk in relevant_ids}
        skus=[sku for sku in skus if sku.spu_id in relevant_spu_ids]
        inventory_context=domain.inventory_context_for(actor,country)
        size=max(1,min(int(batch_size),200))
        for start in range(0,len(skus),size):
            batch=skus[start:start+size]
            rows=domain.decision_rows(actor,country,batch,target_days=config['horizon_days'],window_days=30,windows=(7,15,30,90),end_date=today - timedelta(days=1),include_in_transit=True,sales_observations=sales_data,pipeline_observations=pipelines,inventory_context=inventory_context,compact_product_details=True)
            for row in rows:
                pipe=row.get('pipeline') or {}; shipments=pipe.get('shipment_outstanding',pipe.get('eta_rows',[])) or []
                arrivals=[{'quantity':x.get('quantity',x.get('remaining_quantity',0)),'expected_date':x.get('expected_date',x.get('eta'))} for x in shipments]
                sales_complete=not bool(set(row.get('blocking_issues',[])) & {'no_sales_facts','unmapped_sales_lines','collection_coverage_unproven','unfinished_store_day','no_authorized_sales_store'})
                calculated=evaluate_replenishment_row(row,strategy,sales_end=today,today=today) if strategy else None
                policy=calculated['policy'] if calculated else {}
                if calculated:row['daily_sales']=str(calculated['daily']) if calculated['daily'] is not None else None
                else:issues.add('replenishment_strategy_missing')
                supply_complete=bool(pipe.get('authorized')) and not bool(set(pipe.get('issues',[])) & {'warehouse_supply_scope_incomplete','unassigned_warehouse_supply','wms_receipt_overlap_unresolved','shipment_receipt_overallocated'})
                sales_complete &= not bool(set(row.get('blocking_issues',[])) & {'invalid_store_timezone','bundle_composition_unverified'})
                reference_sales=not sales_complete and row.get('total_demand_quantity') is not None and row['total_demand_quantity']>0 and row.get('daily_sales') is not None and not bool(set(row.get('blocking_issues',[])) & {'invalid_store_timezone','unfinished_store_day','bundle_composition_unverified','no_authorized_sales_store'})
                warning=assess_sku(stock=row.get('available_stock'),daily_sales=row.get('daily_sales'),arrivals=arrivals,today=today,horizon_days=calculated['target_days'] if calculated else 60,production_unshipped=pipe.get('production_unshipped',0),supply_authorized=bool(pipe.get('authorized')),supply_complete=supply_complete,sales_complete=(sales_complete or reference_sales) and bool(strategy),inventory_complete=bool(row.get('inventory_complete')),first_sale_date=first_dates.get(row['sku_id']),observation_days=observation_days,activity_start=policy.get('activity_start'),activity_end=policy.get('activity_end'),activity_factor=policy.get('activity_factor',1),daily_ratio=calculated.get('daily_ratio') if calculated else None)
                warning['confidence']='reference' if reference_sales else 'complete' if sales_complete else 'unavailable'
                row['spu_id']=sku_by_id[row['sku_id']].spu_id
                row['warning']=warning
                if warning['state']=='unavailable' or row.get('issues'):issues.update(row.get('issues') or ['source_data_incomplete'])
                # Page payloads do not need repeated country-wide source-run
                # arrays, store manifests or monetary data. Keep provenance once
                # on the run, and quantities/dates on each SKU.
                row.pop('source_run_ids',None);row.pop('source_snapshot_ids',None);row.pop('operations',None)
                row['sales_windows']=[{k:window.get(k) for k in ('days','start_date','end_date','units','recognized_units','coverage_complete','daily_units')} for window in row.get('sales_windows',[])]
                payloads.append(row)
            run.config={**run.config,'processed_skus':min(start+size,len(skus)),'total_skus':len(skus)}
            run.save(update_fields=['config'])
        if signature(source_rows()) != initial_signature:
            raise RuntimeError('inventory_batch_changed_during_calculation')
        if change_token(actor.tenant_id,country) != initial_change_token:
            raise RuntimeError('sales_or_supply_changed_during_calculation')
        if strategy and not ReplenishmentStrategy.objects.filter(pk=strategy.pk,version=strategy.version,active=True).exists():
            raise RuntimeError('replenishment_strategy_changed_during_calculation')
        relevant_spus={sku_by_id[row['sku_id']].spu_id for row in payloads if Decimal(str(row.get('available_stock') or 0))>0 or (row.get('total_demand_quantity') or 0)>0 or any(Decimal(str((row.get('pipeline') or {}).get(k) or 0))>0 for k in ('production_unshipped','effective_incoming','unknown_eta'))}
        payloads=[row for row in payloads if sku_by_id[row['sku_id']].spu_id in relevant_spus]
        key_short=spu_key_shortage_ids(payloads)
        objects=[]
        for row in payloads:
            sku=sku_by_id[row['sku_id']];warning=row['warning'];flags=set(warning['warnings'])
            detail=row.get('product_details') or {}
            payload={'sku_id':sku.pk,'sku_code':row.get('sku'),'legacy_sku_code':row.get('legacy_sku_code'),'spu_id':sku.spu_id,'spu_name':sku.spu.product_name if sku.spu_id else '', 'spu_code':getattr(sku.spu,'spu_code','') if sku.spu_id else '', 'legacy_spu_code':getattr(sku.spu,'legacy_spu_code','') if sku.spu_id else '', 'product_name':row.get('product_name'),'image_preview_url':row.get('image_preview_url'),'image_url':detail.get('image_url'),'warning':warning,'pipeline':row.get('pipeline'),'sales_windows':row.get('sales_windows'),'available_stock':row.get('available_stock'),'stock':row.get('available_stock'),'daily_sales':row.get('daily_sales'),'first_sale_date':str(first_dates.get(sku.pk)) if first_dates.get(sku.pk) else None,'abc_run_id':abc.pk if abc else None}
            objects.append(InventoryWarningRow(run=run,sku=sku,spu_id=sku.spu_id,payload=payload,forecast_stockout='forecast_stockout' in flags,key_variant_shortage=sku.pk in key_short,supply_risk=bool({'supply_overdue','arrival_unconfirmed','arrival_after_shortage'}&flags),excess_stock=bool({'excess_stock','stock_without_sales'}&flags),new_product='new_product_observation' in flags))
        payloads.clear()
        from .warning_presentation import summarize_spus, FLAGS
        run.config={**run.config,'spu_summaries':summarize_spus([{'spu_id':item.spu_id,'payload':item.payload,**{f:getattr(item,f) for f in FLAGS}} for item in objects])}
        with transaction.atomic():
            for item in objects:item.payload=json.loads(json.dumps(item.payload,cls=DjangoJSONEncoder))
            InventoryWarningRow.objects.bulk_create(objects,batch_size=200)
            run.issues=sorted(issues);run.status='partial' if issues else 'ready';run.completed_at=timezone.now();run.save(update_fields=['issues','status','completed_at','config'])
        return run
    except Exception as exc:
        run.status='failed';run.issues=[type(exc).__name__];run.completed_at=timezone.now();run.save(update_fields=['status','issues','completed_at']);raise
