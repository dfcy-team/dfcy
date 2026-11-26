from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import CustomUser
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.products.monthly_cost_models import MonthlyCostAdjustment
from apps.tenants.models import Tenant
from apps.finance.monthly_adjustment_views import historical_sold_adjustments

pytestmark = pytest.mark.django_db


def setup_rows():
    tenant = Tenant.objects.create(name="Adjustment Finance", code="adjustment-finance")
    user = CustomUser.objects.create_user(username="adjustment-finance", tenant=tenant, user_type="internal")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="AF-SPU", product_name="AF")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="AF-SKU", product_name="AF")
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code="AF-WH", name="AF warehouse", country_code="MY", warehouse_type="owned")
    return user, warehouse, sku


def invoke(user, **params):
    request = APIRequestFactory().get("/api/finance/monthly-adjustments/", params)
    force_authenticate(request, user=user)
    with patch("apps.finance.monthly_adjustment_views.check_user_permission", return_value=True):
        return historical_sold_adjustments(request)


def add_adjustment(user, wh, sku, *, key="late-1", sold="3.2500", inventory="1.7500"):
    return MonthlyCostAdjustment.objects.create(tenant=user.tenant, sku=sku, warehouse=wh,
        original_month=date(2026, 10, 1), effective_month=date(2026, 11, 1), receipt_line_id=1,
        source_key=key, delta_amount=Decimal(sold) + Decimal(inventory), sold_amount=Decimal(sold),
        inventory_amount=Decimal(inventory), status="allocated", evidence={"ref": key})


@override_settings(MONTHLY_PRODUCT_COST_FINANCE_ENABLED=False)
def test_disabled_returns_disabled_payload():
    user, _, _ = setup_rows()
    response = invoke(user, month="2026-11")
    assert response.data["data"] == {"enabled": False, "month": None, "rows": []}


@override_settings(MONTHLY_PRODUCT_COST_FINANCE_ENABLED=True)
def test_requires_finance_view_permission():
    user, _, _ = setup_rows()
    request = APIRequestFactory().get("/", {"month": "2026-11"}); force_authenticate(request, user=user)
    with patch("apps.finance.monthly_adjustment_views.check_user_permission", return_value=False):
        assert historical_sold_adjustments(request).status_code == 403


@override_settings(MONTHLY_PRODUCT_COST_FINANCE_ENABLED=True)
def test_rejects_non_internal_user():
    user, _, _ = setup_rows(); user.user_type = CustomUser.UserType.EXTERNAL; user.save()
    request = APIRequestFactory().get("/", {"month": "2026-11"}); force_authenticate(request, user=user)
    with patch("apps.finance.monthly_adjustment_views.check_user_permission", return_value=True):
        assert historical_sold_adjustments(request).status_code == 403


@override_settings(MONTHLY_PRODUCT_COST_FINANCE_ENABLED=True)
def test_store_only_scope_is_rejected():
    user, _, _ = setup_rows()
    with patch("apps.finance.monthly_adjustment_views.permission_scope_configs", return_value=[{"store_ids": [4]}]):
        assert invoke(user, month="2026-11").status_code == 403


@override_settings(MONTHLY_PRODUCT_COST_FINANCE_ENABLED=True)
def test_warehouse_scope_and_negative_gross_profit_impact():
    user, wh, sku = setup_rows(); add_adjustment(user, wh, sku)
    with patch("apps.finance.monthly_adjustment_views.permission_scope_configs", return_value=[{"warehouse_ids": [wh.pk]}]):
        row = invoke(user, month="2026-11").data["data"]["rows"][0]
    assert row["sold_amount"] == "3.2500" and row["inventory_amount"] == "1.7500"
    assert row["gross_profit_impact"] == "-3.2500"


@override_settings(MONTHLY_PRODUCT_COST_FINANCE_ENABLED=True)
def test_denied_warehouse_scope_hides_adjustment():
    user, wh, sku = setup_rows(); add_adjustment(user, wh, sku)
    with patch("apps.finance.monthly_adjustment_views.permission_scope_configs", return_value=[{"warehouse_ids": [wh.pk + 100]}]):
        assert invoke(user, month="2026-11").data["data"]["rows"] == []


@override_settings(MONTHLY_PRODUCT_COST_FINANCE_ENABLED=True)
def test_repeat_request_is_read_only_and_does_not_duplicate_adjustments():
    user, wh, sku = setup_rows(); add_adjustment(user, wh, sku)
    with patch("apps.finance.monthly_adjustment_views.permission_scope_configs", return_value=None):
        first = invoke(user, month="2026-11").data["data"]
        second = invoke(user, month="2026-11").data["data"]
    assert first == second and MonthlyCostAdjustment.objects.count() == 1
