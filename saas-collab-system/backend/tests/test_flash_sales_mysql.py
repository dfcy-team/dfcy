from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.flash_sales.engine import claim
from apps.flash_sales.models import Batch, StoreTask, TenantControl
from apps.flash_sales.services import save_plan, submit
from apps.flash_sales.tasks import dispatch_plans
from apps.masterdata.models import StoreMaster
from tests.test_flash_sales import configured, shop

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != "mysql", reason="Real row-lock tests require isolated MySQL")]


def concurrent(count, work):
    barrier = Barrier(count)

    def invoke(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return work(index)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(invoke, range(count)))


def test_first_use_shared_app_pacer_does_not_deadlock(shop, monkeypatch):
    from apps.flash_sales.provider import Deferred, ShopeeAdapter
    from apps.flash_sales.models import AppPacer
    monkeypatch.setattr("apps.flash_sales.provider.time.sleep", lambda delay: None)
    def pace(index):
        try:
            ShopeeAdapter(shop[1])._pace("synthetic-shared-app")
            return "paced"
        except Deferred:
            return "deferred"
    results = concurrent(6, pace)
    assert set(results) <= {"paced", "deferred"} and "paced" in results
    assert AppPacer.objects.count() == 1


def test_concurrent_same_request_creates_only_one_batch(shop):
    configured(shop)
    user, store, _ = shop

    def create(index):
        actor = CustomUser.objects.get(pk=user.id)
        return str(submit(actor, request_id="same-http-request", store_ids=[store.id]).id)

    ids = concurrent(4, create)
    assert len(set(ids)) == 1
    assert Batch.objects.count() == 1 and StoreTask.objects.count() == 1


def test_six_store_claims_admit_at_most_three_and_duplicate_delivery_has_one_owner(shop):
    configured(shop)
    user, store, _ = shop
    first = submit(user, request_id="six-stores", store_ids=[store.id]).tasks.get()
    ids = [first.id]
    for number in range(2, 7):
        other = StoreMaster.objects.create(tenant=user.tenant, platform=store.platform, code=f"S{number}", name=f"Shop {number}", country_code="PH", currency="PHP", timezone="Asia/Manila")
        ids.append(StoreTask.objects.create(tenant=user.tenant, batch=first.batch, store=other).id)
    admitted = concurrent(6, lambda index: bool(claim(ids[index])))
    assert sum(admitted) == 3
    StoreTask.objects.update(lease_until=None)
    duplicate = concurrent(6, lambda index: bool(claim(first.id)))
    assert sum(duplicate) == 1


def test_two_schedulers_dispatch_one_occurrence(shop):
    configured(shop)
    user, store, _ = shop
    now = timezone.now()
    TenantControl.objects.create(tenant=user.tenant, scheduler_owner="saas", last_dispatch_at=now-timedelta(seconds=5))
    plan = save_plan(user, {"kind":"daily", "time":"09:00", "store_ids":[store.id]})
    plan.enabled, plan.next_due = True, now-timedelta(seconds=1)
    plan.save()
    concurrent(2, lambda index: dispatch_plans(now=now))
    assert Batch.objects.count() == 1 and StoreTask.objects.count() == 1


def test_competing_batches_for_same_store_keep_one_lock_and_fence_old_worker(shop):
    from apps.flash_sales.engine import fence, LeaseLost
    from apps.flash_sales.models import StoreLock
    configured(shop)
    user, store, _ = shop
    ids = concurrent(4, lambda index: submit(CustomUser.objects.get(pk=user.id),
        request_id=f"competing-{index}", store_ids=[store.id]).tasks.get().id)
    assert len(set(ids)) == 4
    owners = [task for task in concurrent(4, lambda index: claim(ids[index])) if task]
    assert len(owners) == 1 and StoreLock.objects.get(store=store).task_id == owners[0].id
    old = owners[0]
    StoreTask.objects.filter(pk=old.id).update(lease_until=timezone.now()-timedelta(seconds=1))
    recovered = [task for task in concurrent(4, lambda index: claim(old.id)) if task]
    assert len(recovered) == 1 and recovered[0].fence != old.fence
    with pytest.raises(LeaseLost):
        fence(old)
    assert StoreTask.objects.filter(lease_until__gt=timezone.now()).count() == 1
