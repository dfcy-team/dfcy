from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.listings.models import (
    ListingAttributeMapping,
    ListingProfile,
    ListingTask,
    ListingTaskStepLog,
    ListingVariant,
    PlatformCategoryMapping,
)
from apps.listings.services import (
    approve_listing,
    generate_listing_drafts,
    queue_listing_publication,
    submit_listing_for_approval,
    validate_listing,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.rpa.models import RPATask
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _tenant_user(code):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(username=f"{code}-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    return tenant, user


def _product_fixture(tenant, code="A"):
    platform = PlatformMaster.objects.create(tenant=tenant, code=f"shopee-{code}", name="Shopee", platform_type="shopee")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code=f"store-{code}", name="TH", country_code="TH", currency="THB")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{code}", legacy_spu_code=f"OLD-SPU-{code}", product_name="Travel bag", brand="Brand")
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code=f"SKU-{code}",
        legacy_sku_code=f"OLD-SKU-{code}",
        color_code="BLK",
        specification="M",
        purchase_price=Decimal("5.00"),
    )
    return platform, store, spu, sku


def test_batch_drafts_are_tenant_scoped_and_keep_spu_sku_links():
    tenant, user = _tenant_user("listing-a")
    other_tenant, other_user = _tenant_user("listing-b")
    _, store, spu, sku = _product_fixture(tenant)
    _, other_store, other_spu, _ = _product_fixture(other_tenant, "B")

    profiles = generate_listing_drafts(tenant=tenant, actor=user, spu_ids=[spu.id], store_ids=[store.id], sku_ids=[sku.id])
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.product_id == spu.id
    assert list(profile.variants.values_list("sku_id", flat=True)) == [sku.id]
    with pytest.raises(ValidationError):
        generate_listing_drafts(tenant=tenant, actor=user, spu_ids=[other_spu.id], store_ids=[other_store.id])
    assert ListingProfile.objects.filter(tenant=other_tenant).count() == 0


def test_validation_approval_and_production_confirmation_are_gated():
    tenant, user = _tenant_user("listing-gates")
    _, store, spu, sku = _product_fixture(tenant, "G")
    profile = ListingProfile.objects.create(tenant=tenant, profile_no="G-1", product=spu, store=store, title="Bag", currency="THB", created_by=user)
    ListingVariant.objects.create(profile=profile, sku=sku, seller_sku=sku.sku_code, price=Decimal("19.00"))
    checked, errors = validate_listing(profile_id=profile.id, actor=user)
    assert errors and checked.status == ListingProfile.Status.DRAFT
    profile.price = Decimal("19.00")
    profile.media = ["https://example.invalid/bag.jpg"]
    profile.save(update_fields=["price", "media"])
    checked, errors = validate_listing(profile_id=profile.id, actor=user)
    assert not errors and checked.status == ListingProfile.Status.READY
    submit_listing_for_approval(profile_id=profile.id, actor=user)
    approve_listing(profile_id=profile.id, actor=user)
    with pytest.raises(ValidationError):
        queue_listing_publication(profile_id=profile.id, actor=user, idempotency_key="gate-1", execution_mode="production")


def test_publish_is_idempotent_and_creates_rpa_task_and_steps():
    tenant, user = _tenant_user("listing-publish")
    _, store, spu, sku = _product_fixture(tenant, "P")
    profile = ListingProfile.objects.create(
        tenant=tenant,
        profile_no="P-1",
        product=spu,
        store=store,
        title="Bag",
        currency="THB",
        price=Decimal("19.00"),
        media=["https://example.invalid/bag.jpg"],
        status=ListingProfile.Status.APPROVED,
        created_by=user,
    )
    ListingVariant.objects.create(profile=profile, sku=sku, seller_sku=sku.sku_code, price=Decimal("19.00"))
    job, replayed = queue_listing_publication(profile_id=profile.id, actor=user, idempotency_key="publish-1")
    replay, replayed_again = queue_listing_publication(profile_id=profile.id, actor=user, idempotency_key="publish-1")
    assert replayed is False and replayed_again is True and replay.id == job.id
    assert RPATask.objects.filter(tenant=tenant, business_type="listing").count() == 1
    task = ListingTask.objects.get(publication_job=job)
    assert task.execution_mode == ListingTask.ExecutionMode.DRY_RUN
    assert ListingTaskStepLog.objects.filter(task=task, step_name="queued").exists()


def test_mapping_models_are_tenant_owned():
    tenant, user = _tenant_user("listing-map")
    platform, store, spu, sku = _product_fixture(tenant, "M")
    category = PlatformCategoryMapping.objects.create(
        tenant=tenant,
        platform=platform,
        country_code=store.country_code,
        source_category_code="12",
        target_category_code="cat-12",
        created_by=user,
    )
    attribute = ListingAttributeMapping.objects.create(
        tenant=tenant,
        platform=platform,
        country_code=store.country_code,
        source_attribute_code="color_code",
        target_attribute_code="colour",
        created_by=user,
    )
    assert category.tenant_id == attribute.tenant_id == tenant.id
