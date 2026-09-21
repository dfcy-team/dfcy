from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.influencers.models import Influencer, SampleFulfillment
from apps.influencers.services import _recalculate_sample_costs
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _records(code):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(username=f"{code}-user", tenant=tenant)
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
    sampled_at = timezone.now() - timedelta(days=2)
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
    return tenant, user, sku, fulfillment, sampled_at


def test_sample_item_snapshots_effective_confirmed_cost_version():
    tenant, user, sku, fulfillment, sampled_at = _records("cost-snapshot")
    version = ProductCostVersion.objects.create(
        tenant=tenant,
        sku=sku,
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
        item_payloads=[{"sku": sku, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 2}],
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
    _tenant, user, sku, fulfillment, _sampled_at = _records("cost-unmatched")

    _recalculate_sample_costs(
        user=user,
        fulfillment=fulfillment,
        item_payloads=[{"sku": sku, "requested_sku": sku.sku_code, "site_code": "PH", "quantity": 1}],
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
