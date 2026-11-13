from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.influencers.services import _purchase_cost_for_sample_payload, _current_sample_item_costs
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def data():
    tenant = Tenant.objects.create(name="Ambiguous sample", code="ambiguous-cost")
    user = CustomUser.objects.create_user(username="cost-author", tenant=tenant)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU", product_name="Same product")
    skus = [ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"NEW-{i}", legacy_sku_code="OLD-SKU") for i in range(2)]
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code="PH1", name="PH1", country_code="PH")
    return SimpleNamespace(tenant=tenant, user=user, spu=spu, skus=skus, warehouse=warehouse)


def cost(data, sku, *, warehouse=None, number=1, amount="12.34", status="confirmed", currency="CNY", future=False):
    return ProductCostVersion.objects.create(
        tenant=data.tenant, sku=sku, warehouse=warehouse or data.warehouse, version_no=number,
        status=status, confirmed_cost=Decimal(amount), currency=currency, created_by=data.user,
        effective_from=timezone.now() + timedelta(days=1) if future else timezone.now() - timedelta(days=1),
    )


def resolve(data, **overrides):
    payload = {"requested_sku": "OLD-SKU", "warehouse": data.warehouse, **overrides}
    return _purchase_cost_for_sample_payload(data.tenant, payload)


def test_one_confirmed_candidate_is_selected_and_total_stays_cny(data):
    version = cost(data, data.skus[1])
    assert resolve(data)[1] == data.skus[1]
    fields = _current_sample_item_costs(tenant=data.tenant,
        fulfillment=SimpleNamespace(store=SimpleNamespace(country_code="PH", code="STORE", tenant_id=data.tenant.pk)),
        payload={"requested_sku": "OLD-SKU", "warehouse": data.warehouse, "quantity": 3})
    assert fields["sku_id"] == data.skus[1].pk
    assert fields["cost_version_id"] == version.pk
    assert fields["cost_amount"] == Decimal("37.02")
    assert fields["currency"] == "CNY"


def test_latest_confirmation_wins_not_unrelated_sku_version_counter(data):
    older = cost(data, data.skus[0], number=99, amount="88")
    ProductCostVersion.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=2))
    cost(data, data.skus[1], number=1, amount="20")
    assert resolve(data)[1] == data.skus[1]


@pytest.mark.parametrize("unusable", ["pending", "future", "foreign_currency", "other_warehouse"])
def test_unusable_cost_does_not_break_ambiguity(data, unusable):
    kwargs = {}
    if unusable == "pending": kwargs["status"] = "pending"
    if unusable == "future": kwargs["future"] = True
    if unusable == "foreign_currency": kwargs["currency"] = "PHP"
    if unusable == "other_warehouse":
        kwargs["warehouse"] = WarehouseMaster.objects.create(tenant=data.tenant, code="PH2", name="PH2", country_code="PH")
    cost(data, data.skus[0], **kwargs)
    assert resolve(data)[1:] == (None, "ambiguous")


def test_cross_spu_candidates_are_never_selected_by_cost(data):
    other = ProductSPU.objects.create(tenant=data.tenant, spu_code="OTHER", product_name="Different product")
    data.skus[1].spu = other
    data.skus[1].save(update_fields=["spu"])
    cost(data, data.skus[1])
    assert resolve(data)[1:] == (None, "ambiguous")


def test_explicit_selection_is_not_replaced_by_newer_candidate(data):
    cost(data, data.skus[0]); cost(data, data.skus[1])
    assert resolve(data, sku=data.skus[0])[1] == data.skus[0]


def test_no_cost_keeps_unknown_and_inactive_zero_is_not_borrowed(data):
    assert resolve(data)[1:] == (None, "ambiguous")
    cost(data, data.skus[0], amount="0")
    data.skus[0].is_active = False
    data.skus[0].save(update_fields=["is_active"])
    fields = _current_sample_item_costs(tenant=data.tenant,
        fulfillment=SimpleNamespace(store=SimpleNamespace(country_code="PH", code="STORE", tenant_id=data.tenant.pk)),
        payload={"requested_sku": "OLD-SKU", "warehouse": data.warehouse, "quantity": 1})
    assert fields["sku_id"] == data.skus[1].pk
    assert fields["cost_match_status"] == "cost_unmatched"
    assert fields["unit_cost"] is None and fields["cost_amount"] is None


def test_confirmed_zero_is_real_cost_not_a_missing_value(data):
    cost(data, data.skus[1], amount="0")
    assert resolve(data)[1] == data.skus[1]


def test_warehouse_specific_resolution_and_country_rejection(data):
    second = WarehouseMaster.objects.create(tenant=data.tenant, code="TH1", name="TH1", country_code="TH")
    cost(data, data.skus[0]); cost(data, data.skus[1], warehouse=second)
    assert resolve(data)[1] == data.skus[0]
    assert resolve(data, warehouse=second)[1] == data.skus[1]
    fields = _current_sample_item_costs(tenant=data.tenant,
        fulfillment=SimpleNamespace(store=SimpleNamespace(country_code="PH", code="STORE", tenant_id=data.tenant.pk)),
        payload={"requested_sku": "OLD-SKU", "warehouse": second, "quantity": 1})
    assert fields["sku_id"] is None and fields["cost_amount"] is None


def test_foreign_tenant_and_inactive_warehouse_are_not_used(data):
    foreign = Tenant.objects.create(name="Foreign", code="foreign-cost")
    warehouse = WarehouseMaster.objects.create(tenant=foreign, code="PH1", name="PH1", country_code="PH")
    cost(data, data.skus[1])
    assert resolve(data, warehouse=warehouse)[1:] == (None, "ambiguous")
    data.warehouse.status = "inactive"
    assert resolve(data)[1:] == (None, "ambiguous")


def test_normalized_similar_codes_are_not_auto_selected(data):
    cost(data, data.skus[1])
    assert resolve(data, requested_sku="old_sku")[1:] == (None, "ambiguous")
