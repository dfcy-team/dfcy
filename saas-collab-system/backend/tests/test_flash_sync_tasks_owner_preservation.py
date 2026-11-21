"""Two schedulers share one outbox; deployment never transfers ownership."""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command, CommandError
from django.utils import timezone

from apps.flash_sales.models import Batch, Plan, StoreTask, TenantControl
from apps.flash_sales.services import save_plan
from apps.flash_sales.tasks import dispatch_plans
from apps.integrations.models import APISyncTask
from apps.integrations.tasks import dispatch_due_flash_sales_plans
from tests.test_flash_sales import configured, shop

pytestmark=pytest.mark.django_db


def due_plan(shop,owner,now):
    configured(shop)
    actor,store,_=shop
    control=TenantControl.objects.create(tenant=actor.tenant,scheduler_owner=owner,
        last_dispatch_at=now-timedelta(seconds=5),cutover_watermark=now-timedelta(days=1))
    plan=save_plan(actor,{'kind':'daily','time':'09:00','store_ids':[store.pk]})
    plan.enabled=True
    plan.next_due=now-timedelta(seconds=1)
    plan.save()
    return control,plan


@pytest.mark.parametrize('owner',['saas','sync_tasks'])
def test_each_owner_is_claimed_once_without_creating_api_sync_tasks(shop,settings,monkeypatch,owner):
    settings.FLASH_SALES_WORKERS_ENABLED=True
    now=timezone.now()
    monkeypatch.setattr(timezone,'now',lambda:now)
    due_plan(shop,owner,now)
    if owner=='saas':
        assert dispatch_due_flash_sales_plans.run()=={'plans_processed':0}
        assert not Batch.objects.exists()
        assert dispatch_plans(now=now)==1
    else:
        assert dispatch_plans(now=now)==0
        assert not Batch.objects.exists()
        assert dispatch_due_flash_sales_plans.run()=={'plans_processed':1}
    assert dispatch_plans(now=now)==0
    assert dispatch_due_flash_sales_plans.run()=={'plans_processed':0}
    assert Batch.objects.count()==1
    assert StoreTask.objects.count()==1
    assert StoreTask.objects.get().status=='queued'
    assert not APISyncTask.objects.exists()


def test_explicit_handoff_preserves_due_time_and_does_not_dispatch(shop):
    actor,_,_=shop
    now=timezone.now()
    control,plan=due_plan(shop,'saas',now)
    before=(plan.enabled,plan.next_due,plan.version,control.last_dispatch_at,control.cutover_watermark)
    call_command('flash_sales_owner',tenant_code=actor.tenant.code,actor=actor.username,
                 owner='sync_tasks',expected_version=control.version,stdout=StringIO())
    control.refresh_from_db();plan.refresh_from_db()
    assert control.scheduler_owner=='sync_tasks'
    assert (plan.enabled,plan.next_due,plan.version,control.last_dispatch_at,control.cutover_watermark)==before
    assert not Batch.objects.exists() and not StoreTask.objects.exists()
    assert not APISyncTask.objects.exists()


def test_stale_handoff_is_rejected_without_mutating_owner_or_plan(shop):
    actor,_,_=shop
    control,plan=due_plan(shop,'saas',timezone.now())
    with pytest.raises(CommandError,match='版本'):
        call_command('flash_sales_owner',tenant_code=actor.tenant.code,actor=actor.username,
                     owner='sync_tasks',expected_version=control.version+1,stdout=StringIO())
    control.refresh_from_db();plan.refresh_from_db()
    assert control.scheduler_owner=='saas' and plan.enabled
    assert not Batch.objects.exists()


@pytest.mark.parametrize('owner',['paused','manual','legacy'])
def test_new_scheduler_does_not_take_over_other_owners(shop,settings,owner):
    settings.FLASH_SALES_WORKERS_ENABLED=True
    actor,_,_=shop
    TenantControl.objects.create(tenant=actor.tenant,scheduler_owner=owner)
    assert dispatch_due_flash_sales_plans.run()=={'plans_processed':0}
    assert not Batch.objects.exists() and not StoreTask.objects.exists()
    assert not APISyncTask.objects.exists()
