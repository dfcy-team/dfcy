from datetime import date
from decimal import Decimal
from unittest.mock import patch
import pytest
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.products.monthly_cost_views import monthly_cost_collection, monthly_cost_missing
from apps.products.monthly_cost_models import MonthlyProductCost, MonthlyCostAdjustment
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from apps.products.models import ProductSPU, ProductSKU
from apps.masterdata.models import WarehouseMaster
pytestmark=pytest.mark.django_db

def setup_rows():
    tenant=Tenant.objects.create(name="Monthly API",code="monthly-api")
    user=CustomUser.objects.create_user(username="monthly-api",tenant=tenant,user_type="internal")
    spu=ProductSPU.objects.create(tenant=tenant,spu_code="M-SPU",product_name="Monthly")
    sku=ProductSKU.objects.create(tenant=tenant,spu=spu,sku_code="=formula",product_name="Product")
    warehouse=WarehouseMaster.objects.create(tenant=tenant,code="M-WH",name="Warehouse",country_code="MY",warehouse_type="owned")
    record=MonthlyProductCost.objects.create(tenant=tenant,sku=sku,warehouse=warehouse,month=date(2026,11,1),missing_reason="Missing opening cost")
    return user,record

def invoke(view,user,params):
    request=APIRequestFactory().get("/",params);force_authenticate(request,user=user)
    with patch("apps.products.permissions.check_user_permission",return_value=True),patch("apps.products.permissions.get_permission_data_scopes",return_value=[{"scope_type":"all"}]),patch("apps.products.monthly_cost_views.permission_scope_configs",return_value=None):
        return view(request)

def test_missing_export_quotes_formula():
    user,_=setup_rows();response=invoke(monthly_cost_missing,user,{"month":"2026-11"})
    assert response.status_code==200
    assert "'=formula" in response.data["data"]["csv"]
    assert response.data["data"]["rows"]==1

def test_valid_zero_not_missing():
    user,r=setup_rows();r.opening_amount=Decimal("0");r.receipt_amount=Decimal("0");r.adjustment_amount=Decimal("0");r.is_complete=True;r.unit_cost=Decimal("0");r.missing_reason="";r.save()
    assert invoke(monthly_cost_missing,user,{"month":"2026-11"}).data["data"]["rows"]==0
    assert invoke(monthly_cost_collection,user,{"month":"2026-11"}).data["data"]["items"][0]["unit_cost"] is not None

def test_ledger_exposes_sales_cost_adjustment_and_unknown_as_null():
    user,r=setup_rows()
    r.sales_cost_amount=Decimal("0");r.historical_sold_adjustment=Decimal("2.5000");r.save()
    row=invoke(monthly_cost_collection,user,{"month":"2026-11"}).data["data"]["items"][0]
    assert row["sales_cost_amount"]=="0.0000"
    assert row["historical_sold_adjustment"]=="2.5000"
    assert row["receipt_amount"] is None
    assert row["status_label"]=="暂估"

def test_adjustment_summary_is_warehouse_scoped_not_store_allocated():
    user,r=setup_rows()
    MonthlyCostAdjustment.objects.create(tenant=user.tenant,sku=r.sku,warehouse=r.warehouse,
        original_month=date(2026,10,1),effective_month=date(2026,11,1),receipt_line_id=7,
        source_key="late-7",delta_amount=Decimal("5"),inventory_amount=Decimal("2"),
        sold_amount=Decimal("3"),status="allocated",evidence={"ref":"fixture"})
    data=invoke(monthly_cost_collection,user,{"month":"2026-11"}).data["data"]
    assert data["historical_adjustments"]["sold_amount"]=="3"
    assert "no store allocation" in data["historical_adjustments"]["warehouse_scope"]

def test_invalid_month():
    user,_=setup_rows();assert invoke(monthly_cost_collection,user,{"month":"invalid"}).status_code==400

def test_cross_tenant_hidden():
    user,_=setup_rows();user.tenant=Tenant.objects.create(name="Other",code="other-monthly");user.save()
    assert invoke(monthly_cost_collection,user,{"month":"2026-11"}).data["data"]["total"]==0


@pytest.mark.django_db
def test_warehouse_scope_applies_to_download_and_list():
    user,record=setup_rows()
    request=APIRequestFactory().get("/",{"month":"2026-11"});force_authenticate(request,user=user)
    with patch("apps.products.permissions.check_user_permission",return_value=True),patch("apps.products.permissions.get_permission_data_scopes",return_value=[{"scope_type":"custom","config":{"warehouse_ids":[999999]}}]),patch("apps.products.monthly_cost_views.permission_scope_configs",return_value=[{"warehouse_ids":[999999]}]):
        assert monthly_cost_collection(request).data["data"]["total"]==0
    request=APIRequestFactory().get("/",{"month":"2026-11"});force_authenticate(request,user=user)
    with patch("apps.products.permissions.check_user_permission",return_value=True),patch("apps.products.permissions.get_permission_data_scopes",return_value=[{"scope_type":"custom","config":{"warehouse_ids":[999999]}}]),patch("apps.products.monthly_cost_views.permission_scope_configs",return_value=[{"warehouse_ids":[999999]}]):
        assert monthly_cost_missing(request).data["data"]["rows"]==0
