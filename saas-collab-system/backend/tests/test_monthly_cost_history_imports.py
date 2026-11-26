from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from apps.accounts.models import CustomUser
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.products.monthly_cost_imports import preview_monthly_cost_csv
from apps.tenants.models import Tenant


@pytest.fixture
def ctx(db):
    tenant = Tenant.objects.create(name="History", code="history")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="H-SPU", product_name="History")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="XUNI001")
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code="WH6", name="Warehouse 6", country_code="CN", warehouse_type="owned")
    actor = CustomUser.objects.create_user(username="history-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    return tenant, sku, warehouse, actor


def csvrow(tenant, warehouse, sku="XUNI001", month="2025-06", cost="0"):
    return f"tenant_id,warehouse_id,sku_code,month,unit_cost\n{tenant.pk},{warehouse.pk},{sku},{month},{cost}\n"


def test_dry_run_zero_cost_and_business_month_bounds(ctx):
    t, s, w, u = ctx
    out = preview_monthly_cost_csv(content=csvrow(t, w), tenant=t, actor=u)
    assert out["valid"] and out["applied"] == 0 and ProductCostVersion.objects.count() == 0
    out = preview_monthly_cost_csv(content=csvrow(t, w), tenant=t, actor=u, apply=True)
    v = ProductCostVersion.objects.get()
    assert out["applied"] == 1 and v.confirmed_cost == Decimal("0")
    assert v.effective_from == datetime(2025, 6, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert v.effective_to == datetime(2025, 7, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    again = preview_monthly_cost_csv(content=csvrow(t, w), tenant=t, actor=u, apply=True)
    assert again["valid"] and again["applied"] == 0 and ProductCostVersion.objects.count() == 1


@pytest.mark.parametrize("sku,month,cost", [
    ("MISSING", "2025-06", "1"), ("XUNI001", "2025-13", "1"),
    ("XUNI001", "2025-06", "1.00001"), ("XUNI001", "2025-06", "-1"),
    ("XUNI001", "2025-06", "NaN"),
])
def test_invalid_rows_rejected(ctx, sku, month, cost):
    t, _, w, u = ctx
    out = preview_monthly_cost_csv(content=csvrow(t, w, sku, month, cost), tenant=t, actor=u, apply=True)
    assert not out["valid"] and ProductCostVersion.objects.count() == 0


def test_duplicate_and_overlap_rejected(ctx):
    t, s, w, u = ctx
    body = csvrow(t, w) + f"{t.pk},{w.pk},XUNI001,2025-06,2\n"
    assert not preview_monthly_cost_csv(content=body, tenant=t, actor=u)["valid"]
    preview_monthly_cost_csv(content=csvrow(t, w), tenant=t, actor=u, apply=True)
    again = preview_monthly_cost_csv(content=csvrow(t, w), tenant=t, actor=u, apply=True)
    assert again["valid"] and again["applied"] == 0 and ProductCostVersion.objects.count() == 1


def test_tenant_authorization(ctx):
    t, s, w, u = ctx
    other = Tenant.objects.create(name="Other", code="other")
    out = preview_monthly_cost_csv(content=csvrow(other, w), tenant=t, actor=u)
    assert not out["valid"]
