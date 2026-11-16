import hashlib
import json
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.flash_sales.models import Batch, StoreTask, TenantControl
from apps.flash_sales.provider import ShopeeAdapter
from apps.flash_sales.services import save_plan
from apps.flash_sales.tasks import dispatch_plans
from tests.test_flash_sales import shop
from tests.test_flash_sales import FakeShopee, configured, drain
from apps.flash_sales.services import submit

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("owner,source,operation,status,bound,allowed", [
    ("manual", "manual", "run", "running", True, True),
    ("paused", "manual", "run", "running", True, False),
    ("legacy", "manual", "run", "running", True, False),
    ("manual", "scheduled", "run", "running", True, False),
    ("manual", "copy", "copy", "running", True, False),
    ("manual", "manual", "delete", "running", True, False),
    ("manual", "manual", "run", "stopped", True, False),
    ("manual", "manual", "run", "running", False, False),
    ("saas", "scheduled", "run", "running", True, True),
])
def test_write_scope(shop, settings, owner, source, operation, status, bound, allowed):
    settings.FLASH_SALES_LIVE_ENABLED = True
    user, store, _ = shop
    TenantControl.objects.create(tenant=user.tenant, scheduler_owner=owner)
    batch = Batch.objects.create(tenant=user.tenant, actor=user, request_id="scope", payload_hash="test",
                                 source=source, operation=operation)
    task = StoreTask.objects.create(tenant=user.tenant, store=store, batch=batch, status=status)
    adapter = ShopeeAdapter(store)
    adapter.task_id = task.pk if bound else None
    # Stop before credentials/network: reaching authorization proves only the ownership gate passed.
    with patch("apps.flash_sales.provider.authorized_store", side_effect=RuntimeError("authorization reached")) as auth:
        if allowed:
            with pytest.raises(RuntimeError, match="authorization reached"):
                adapter.call("create_shop_flash_sale", body={})
            auth.assert_called_once_with(store)
        else:
            with pytest.raises(ValidationError, match="未提交平台写入"):
                adapter.call("create_shop_flash_sale", body={})
            auth.assert_not_called()


def test_manual_cutover_requires_evidence_and_never_dispatches_plans(shop, tmp_path):
    user, store, _ = shop
    plan = save_plan(user, {"kind": "daily", "time": "09:00", "store_ids": [store.id]})
    common = {"tenant_code": user.tenant.code, "actor": user.username, "stdout": StringIO()}
    with pytest.raises(CommandError):
        call_command("flash_sales_owner", owner="manual", **common)
    raw = json.dumps({"tenant_code": user.tenant.code, "target_owner": "manual",
        "previous_source_stopped": True, "writes_reconciled": True, "verified_by": "synthetic-test",
        "verified_at": timezone.now().isoformat(), "imported_record_count": 0}).encode()
    path = tmp_path / "evidence.json"
    path.write_bytes(raw)
    call_command("flash_sales_owner", owner="manual", evidence=str(path),
                 sha256=hashlib.sha256(raw).hexdigest(), **common)
    control = TenantControl.objects.get(tenant=user.tenant)
    plan.refresh_from_db()
    assert control.scheduler_owner == "manual" and control.last_dispatch_at is None
    assert not plan.enabled
    # Even a previously enabled, due plan cannot dispatch under manual ownership.
    plan.enabled, plan.next_due = True, timezone.now()
    plan.save()
    dispatch_plans()
    assert not Batch.objects.exists()


def test_engine_binds_manual_task_and_keeps_single_creation(shop):
    configured(shop)
    user, store, _ = shop
    TenantControl.objects.create(tenant=user.tenant, scheduler_owner="manual")

    class BoundAdapter(FakeShopee, ShopeeAdapter):
        def call(self, endpoint, *, body):
            assert self.task_id == task.pk
            self.write_guard()
            return super().call(endpoint, body=body)

    adapter = BoundAdapter()
    batch = submit(user, request_id="manual-once", store_ids=[store.pk])
    task = batch.tasks.get()
    drain(task, adapter)
    assert task.status == "succeeded" and task.completed == 1
    assert submit(user, request_id="manual-once", store_ids=[store.pk]).pk == batch.pk
    assert sum(endpoint == "create_shop_flash_sale" for endpoint, _ in adapter.calls) == 1
