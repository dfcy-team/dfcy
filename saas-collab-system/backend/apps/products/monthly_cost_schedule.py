"""Opt-in daily orchestration; deployment supplies tenant-bound service actors."""
from celery import shared_task
from django.conf import settings
from django.utils import timezone


@shared_task(name="apps.products.monthly_cost_schedule.dispatch_daily", ignore_result=False)
def dispatch_daily():
    if getattr(settings, "MONTHLY_PRODUCT_COST_ENABLED", False) is not True:
        return {"status":"disabled","queued":0}
    from apps.accounts.models import CustomUser
    from .tasks import aggregate_monthly_product_cost_sources
    from apps.supply_chain.tasks import refresh_daily_batch_costs
    actor_ids=getattr(settings,"MONTHLY_PRODUCT_COST_ACTOR_IDS",[])
    queued=0
    # No implicit choice of superuser and no production credentials discovered.
    for actor in CustomUser.objects.filter(pk__in=actor_ids,is_active=True,user_type="internal",tenant__isnull=False).order_by("pk"):
        prepare_actor.delay(actor.pk)
        queued+=1
    return {"status":"queued","queued":queued}


@shared_task(name="apps.products.monthly_cost_schedule.prepare_actor", ignore_result=False)
def prepare_actor(actor_id, after_id=0):
    if getattr(settings,"MONTHLY_PRODUCT_COST_ENABLED",False) is not True:
        return {"status":"disabled"}
    from apps.accounts.models import CustomUser
    actor=CustomUser.objects.get(pk=actor_id,is_active=True,user_type="internal",tenant__isnull=False)
    from apps.supply_chain.monthly_cost_jobs import run_daily_batch_costs
    if getattr(settings,"SUPPLY_MONTHLY_COST_JOBS_ENABLED",False) is True:
        result=run_daily_batch_costs(actor,limit=100,after_id=after_id)
        if result.get("has_more"):
            prepare_actor.delay(actor.pk,result["next_cursor"])
            return {"status":"continuing","next_cursor":result["next_cursor"]}
        if result.get("errors"):
            return {"status":"pending_review","errors":result["errors"]}
    from .tasks import aggregate_monthly_product_cost_sources
    aggregate_monthly_product_cost_sources.delay(actor.tenant_id,timezone.localdate().replace(day=1).isoformat())
    return {"status":"aggregation_queued"}


@shared_task(name="apps.products.monthly_cost_schedule.finalize_ready_months", ignore_result=False)
def finalize_ready_months(tenant_id, limit=100):
    """Consume verified reconciliation evidence; never manufacture complete watermarks."""
    if getattr(settings,"MONTHLY_PRODUCT_COST_ENABLED",False) is not True:
        return {"status":"disabled","finalized":0}
    from .monthly_cost_models import MonthlyProductCost
    from .monthly_cost_services import finalize_month
    from django.core.exceptions import ValidationError
    finalized,pending=0,[]
    rows=MonthlyProductCost.objects.filter(tenant_id=tenant_id,month__lt=timezone.localdate().replace(day=1)).exclude(status="finalized").order_by("month","pk")[:min(500,max(1,int(limit)))]
    for row in rows:
        try:
            finalize_month(row,row.watermark)
            finalized+=1
        except ValidationError as exc:
            pending.append({"id":row.pk,"reason":str(exc)})
    return {"status":"completed","finalized":finalized,"pending":pending}
