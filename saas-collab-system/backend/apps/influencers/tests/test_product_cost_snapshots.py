from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.influencers.models import Influencer, SampleFulfillment, SampleItem
from apps.influencers.services import _recalculate_sample_costs
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _records(code, sampled_at=None):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(
        username=f"{code}-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"platform-{code}",
        name="TikTok Shop",
        platform_type=PlatformMaster.PlatformType.TIKTOK,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name="Creator store",
        country_code="PH",
        currency="PHP",
    )
    influencer = Influencer.objects.create(
        tenant=tenant,
        code=f"creator-{code}",
        name="Creator",
        platform="tiktok",
    )
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"SPU-{code}",
        product_name="Snapshot product",
    )
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code=f"SKU-{code}",
        purchase_price=Decimal("99.0000"),
    )
    sampled_at = sampled_at or timezone.now() - timedelta(days=2)
    fulfillment = SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no=f"FUL-{code}",
        request_key=f"REQ-{code}",
        request_hash=f"HASH-{code}",
        influencer=influencer,
        store=store,
        owner=user,
        sample_sent_at=sampled_at,
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant, code=f"wh-{code}", name="PH warehouse",
        country_code="PH", warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    return tenant, user, sku, fulfillment, sampled_at, warehouse


def test_sample_item_snapshots_effective_confirmed_cost_version():
    tenant, user, sku, fulfillment, sampled_at, warehouse = _records("cost-snapshot")
    version = ProductCostVersion.objects.create(
        tenant=tenant,
        sku=sku,
        warehouse=warehouse,
        version_no=1,
        status=ProductCostVersion.Status.CONFIRMED,
        source=ProductCostVersion.Source.MANUAL,
        currency="CNY",
        confirmed_cost=Decimal("12.5000"),
        effective_from=sampled_at - timedelta(days=1),
        created_by=user,
    )

    _recalculate_sample_costs(
        user=user,
        fulfillment=fulfillment,
        item_payloads=[{"sku": sku, "warehouse": warehouse, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 2}],
    )

    item = fulfillment.items.get()
    assert item.cost_version == version
    assert item.unit_cost == Decimal("12.5000")
    assert item.cost_amount == Decimal("25.0000")
    assert item.currency == "CNY"
    assert item.cost_source == "product_cost_version"

    ProductCostVersion.objects.create(
        tenant=tenant,
        sku=sku,
        warehouse=warehouse,
        version_no=2,
        status=ProductCostVersion.Status.CONFIRMED,
        source=ProductCostVersion.Source.MANUAL,
        currency="CNY",
        confirmed_cost=Decimal("18.0000"),
        effective_from=sampled_at + timedelta(days=1),
        created_by=user,
    )
    item.refresh_from_db()
    assert item.cost_version == version
    assert item.unit_cost == Decimal("12.5000")
    assert item.cost_amount == Decimal("25.0000")


def test_sample_item_without_effective_version_is_explicitly_unmatched():
    _tenant, user, sku, fulfillment, _sampled_at, warehouse = _records("cost-unmatched")

    _recalculate_sample_costs(
        user=user,
        fulfillment=fulfillment,
        item_payloads=[{"sku": sku, "warehouse": warehouse, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 1}],
    )

    item = fulfillment.items.get()
    assert item.cost_version is None
    assert item.unit_cost is None
    assert item.cost_amount is None
    assert item.cost_match_status == "cost_unmatched"
    assert item.cost_source == "product_cost_version_unmatched"
    assert item.cost_snapshot_at is not None
    fulfillment.refresh_from_db()
    assert fulfillment.calculated_cost is None


def test_sample_item_falls_back_to_latest_confirmed_version_in_previous_calendar_month():
    sent_at = timezone.make_aware(datetime(2026, 9, 15, 12))
    tenant, user, sku, fulfillment, _, warehouse = _records("cost-previous-month", sent_at)
    for number, day, status, amount in (
        (1, 5, ProductCostVersion.Status.CONFIRMED, "10.0000"),
        (2, 20, ProductCostVersion.Status.CONFIRMED, "12.0000"),
        (3, 25, ProductCostVersion.Status.PENDING, "99.0000"),
    ):
        ProductCostVersion.objects.create(
            tenant=tenant, sku=sku, warehouse=warehouse, version_no=number,
            status=status, source=ProductCostVersion.Source.MANUAL,
            currency="CNY", confirmed_cost=Decimal(amount),
            effective_from=timezone.make_aware(datetime(2026, 8, day, 12)), created_by=user,
            effective_to=timezone.make_aware(datetime(2026, 9, 1)),
        )

    _recalculate_sample_costs(
        user=user, fulfillment=fulfillment,
        item_payloads=[{"sku": sku, "warehouse": warehouse, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 2}],
    )

    item = fulfillment.items.get()
    assert item.cost_version.version_no == 2
    assert item.cost_amount == Decimal("24.0000")
    assert item.cost_source == "product_cost_version_previous_month"


def test_sample_item_does_not_fall_back_beyond_previous_month():
    tenant, user, sku, fulfillment, _, warehouse = _records(
        "cost-old-month", timezone.make_aware(datetime(2026, 9, 15, 12)),
    )
    ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=warehouse, version_no=1,
        status=ProductCostVersion.Status.CONFIRMED,
        source=ProductCostVersion.Source.MANUAL, currency="CNY",
        confirmed_cost=Decimal("10.0000"),
        effective_from=timezone.make_aware(datetime(2026, 7, 20, 12)),
        effective_to=timezone.make_aware(datetime(2026, 8, 1)), created_by=user,
    )

    _recalculate_sample_costs(
        user=user, fulfillment=fulfillment,
        item_payloads=[{"sku": sku, "warehouse": warehouse, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 1}],
    )
    assert fulfillment.items.get().cost_match_status == "cost_unmatched"


def test_backfill_dry_run_then_apply_only_unmatched_sample():
    tenant, user, sku, fulfillment, sampled_at, warehouse = _records("cost-backfill")
    _recalculate_sample_costs(
        user=user, fulfillment=fulfillment,
        item_payloads=[{"sku": sku, "warehouse": warehouse, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 2}],
    )
    item = fulfillment.items.get()
    version = ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=warehouse, version_no=1,
        status=ProductCostVersion.Status.CONFIRMED,
        source=ProductCostVersion.Source.MANUAL, currency="CNY",
        confirmed_cost=Decimal("8.0000"), effective_from=sampled_at - timedelta(days=1), created_by=user,
    )
    output = StringIO()
    call_command("backfill_sample_confirmed_costs", tenant_id=tenant.pk, actor_id=user.pk, stdout=output)
    assert "matched=1 applied=0" in output.getvalue()
    item.refresh_from_db()
    assert item.cost_amount is None

    output = StringIO()
    call_command("backfill_sample_confirmed_costs", tenant_id=tenant.pk, actor_id=user.pk, apply=True, stdout=output)
    assert "matched=1 applied=1" in output.getvalue()
    item.refresh_from_db()
    fulfillment.refresh_from_db()
    assert item.cost_version_id == version.pk
    assert item.cost_amount == Decimal("16.0000")
    assert fulfillment.calculated_cost == Decimal("16.0000")

    output = StringIO()
    call_command("backfill_sample_confirmed_costs", tenant_id=tenant.pk, actor_id=user.pk, apply=True, stdout=output)
    assert "scanned=0" in output.getvalue()


def test_backfill_skips_ambiguous_warehouse_without_writing():
    tenant, user, sku, fulfillment, sampled_at, _warehouse = _records("cost-backfill-ambiguous")
    item = SampleItem.objects.create(
        tenant=tenant, fulfillment=fulfillment, requested_sku=sku.sku_code,
        site_code="PH", cost_match_status="cost_unmatched",
        cost_source="product_cost_version_unmatched",
    )
    second = WarehouseMaster.objects.create(
        tenant=tenant, code="wh-second-ambiguous", name="Other PH warehouse",
        country_code="PH", warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=second, version_no=1,
        status=ProductCostVersion.Status.CONFIRMED,
        source=ProductCostVersion.Source.MANUAL, currency="CNY",
        confirmed_cost=Decimal("8.0000"), effective_from=sampled_at - timedelta(days=1), created_by=user,
    )
    output = StringIO()
    call_command("backfill_sample_confirmed_costs", tenant_id=tenant.pk, actor_id=user.pk, apply=True, stdout=output)
    assert "warehouse_ambiguous=1" in output.getvalue()
    item.refresh_from_db()
    assert item.cost_amount is None


def test_sample_item_requires_explicit_warehouse_even_with_same_country_candidates():
    tenant, user, sku, fulfillment, sampled_at, warehouse = _records("cost-explicit")
    other = WarehouseMaster.objects.create(
        tenant=tenant, code="wh-second", name="Second PH warehouse",
        country_code="PH", warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=warehouse, version_no=1,
        status=ProductCostVersion.Status.CONFIRMED,
        source=ProductCostVersion.Source.MANUAL, currency="PHP",
        confirmed_cost=Decimal("4.0000"), effective_from=sampled_at - timedelta(days=1), created_by=user,
    )
    second_cost = ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=other, version_no=2,
        status=ProductCostVersion.Status.CONFIRMED,
        source=ProductCostVersion.Source.MANUAL, currency="PHP",
        confirmed_cost=Decimal("8.0000"), effective_from=sampled_at - timedelta(days=1), created_by=user,
    )
    with pytest.raises(ValidationError, match="explicit warehouse"):
        _recalculate_sample_costs(
            user=user, fulfillment=fulfillment,
            item_payloads=[{"sku": sku, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 1}],
        )
    assert fulfillment.items.count() == 0
    _recalculate_sample_costs(
        user=user, fulfillment=fulfillment,
        item_payloads=[{"sku": sku, "warehouse": other, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 1}],
    )
    assert fulfillment.items.get().cost_version_id == second_cost.id


def test_sample_item_rejects_warehouse_country_mismatch_and_cross_tenant():
    tenant, user, sku, fulfillment, _, warehouse = _records("cost-country")
    warehouse.country_code = "US"
    warehouse.save(update_fields=["country_code"])
    with pytest.raises(ValidationError, match="country"):
        _recalculate_sample_costs(
            user=user, fulfillment=fulfillment,
            item_payloads=[{"sku": sku, "warehouse": warehouse, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 1}],
        )
    other_tenant = Tenant.objects.create(name="Other", code="other-cost-country")
    cross_tenant = WarehouseMaster.objects.create(
        tenant=other_tenant, code="foreign", name="Foreign warehouse", country_code="PH",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    with pytest.raises(ValidationError, match="active warehouse"):
        _recalculate_sample_costs(
            user=user, fulfillment=fulfillment,
            item_payloads=[{"sku": sku, "warehouse": cross_tenant, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 1}],
        )
