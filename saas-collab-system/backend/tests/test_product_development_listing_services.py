from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.audit.models import NotificationMessage
from apps.common.exceptions import StateConflict
from apps.development.models import DevelopmentCostEstimate, DevelopmentProject, DevelopmentSample, ProductSalesSnapshot
from apps.development.services import (
    calculate_cost_summary,
    advance_project_stage,
    check_duplicate_requirement,
    finalize_product,
    import_sales_csv,
    review_reminder_candidates,
)
from apps.listings.models import ListingProfile, ListingVariant
from apps.listings.services import approve_listing, queue_listing_publication, submit_listing_for_approval
from apps.masterdata.models import PlatformMaster, StoreMaster, SupplierMaster
from apps.products.models import ProductResearch, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def actor(tenant, username="developer"):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def project_fixture(tenant, user):
    supplier = SupplierMaster.objects.create(tenant=tenant, code="supplier-1", name="Supplier 1")
    project = DevelopmentProject.objects.create(
        tenant=tenant,
        project_no="DEV-001",
        development_source=DevelopmentProject.Source.INTERNAL,
        product_name="Travel organizer",
        category="Storage",
        stage=DevelopmentProject.Stage.REVIEW,
        assigned_to=user,
        supplier=supplier,
        created_by=user,
    )
    DevelopmentSample.objects.create(
        project=project,
        supplier=supplier,
        sample_no="S-1",
        evaluation_result=DevelopmentSample.Evaluation.PASS,
    )
    estimate = DevelopmentCostEstimate.objects.create(
        project=project,
        site="TH",
        material_cost=Decimal("10"),
        processing_fee=Decimal("2"),
        packaging_cost=Decimal("1"),
        first_leg_shipping=Decimal("2"),
        platform_commission_rate=Decimal("0.10"),
        tariff_rate=Decimal("0.05"),
        target_selling_price=Decimal("30"),
    )
    calculate_cost_summary(estimate_id=estimate.id, actor=user, approve=True)
    return project


def test_duplicate_check_and_finalize_are_tenant_scoped_and_idempotent():
    tenant = Tenant.objects.create(name="Development", code="development")
    user = actor(tenant)
    ProductResearch.objects.create(tenant=tenant, research_no="REQ-1", product_name="Travel Organizer", created_by=user)
    matches = check_duplicate_requirement(tenant=tenant, product_name="travel-organizer")
    assert matches[0]["similarity"] == Decimal("1.0000")

    project = project_fixture(tenant, user)
    product, created = finalize_product(project_id=project.id, actor=user)
    replay, replay_created = finalize_product(project_id=project.id, actor=user)
    assert created is True and replay_created is False
    assert replay.id == product.id
    assert product.development_project_id == project.id


def test_acceptance_main_flow_records_each_stage_product_link_and_notification():
    tenant = Tenant.objects.create(name="Acceptance", code="acceptance")
    user = actor(tenant)
    project = DevelopmentProject.objects.create(
        tenant=tenant,
        project_no="DEV-ACCEPTANCE",
        development_source=DevelopmentProject.Source.OPERATION,
        product_name="Acceptance product",
        assigned_to=user,
        created_by=user,
    )

    advance_project_stage(project_id=project.id, actor=user, target_stage=DevelopmentProject.Stage.DESIGN)
    supplier = SupplierMaster.objects.create(tenant=tenant, code="acceptance-supplier", name="Acceptance supplier")
    DevelopmentSample.objects.create(project=project, supplier=supplier, sample_no="A-1")
    advance_project_stage(project_id=project.id, actor=user, target_stage=DevelopmentProject.Stage.SAMPLING)
    project.samples.update(evaluation_result=DevelopmentSample.Evaluation.PASS)
    advance_project_stage(project_id=project.id, actor=user, target_stage=DevelopmentProject.Stage.REVIEW)
    estimate = DevelopmentCostEstimate.objects.create(
        project=project,
        site="TH",
        material_cost=Decimal("10"),
        target_selling_price=Decimal("20"),
    )
    calculate_cost_summary(estimate_id=estimate.id, actor=user, approve=True)

    product, created = finalize_product(project_id=project.id, actor=user)
    project.refresh_from_db()

    assert created is True
    assert project.stage == DevelopmentProject.Stage.FINALIZED
    assert project.finalized_product_id == product.id
    assert product.development_project_id == project.id
    assert list(project.stage_records.values_list("stage", flat=True)) == [
        DevelopmentProject.Stage.DESIGN,
        DevelopmentProject.Stage.SAMPLING,
        DevelopmentProject.Stage.REVIEW,
        DevelopmentProject.Stage.FINALIZED,
    ]
    assert project.stage_records.get(stage=DevelopmentProject.Stage.FINALIZED).approved_by == user
    assert NotificationMessage.objects.filter(
        tenant=tenant,
        user=user,
        message_type="development_product_finalized",
    ).count() == 1

    replay, replay_created = finalize_product(project_id=project.id, actor=user)
    assert replay.id == product.id and replay_created is False
    assert NotificationMessage.objects.filter(message_type="development_product_finalized").count() == 1


def test_project_stage_cannot_skip():
    tenant = Tenant.objects.create(name="Stage gate", code="stage-gate")
    user = actor(tenant)
    project = DevelopmentProject.objects.create(
        tenant=tenant,
        project_no="DEV-GATE",
        development_source=DevelopmentProject.Source.INTERNAL,
        product_name="Stage gate product",
        assigned_to=user,
        created_by=user,
    )
    with pytest.raises(StateConflict):
        advance_project_stage(project_id=project.id, actor=user, target_stage=DevelopmentProject.Stage.SAMPLING)
    advanced = advance_project_stage(project_id=project.id, actor=user, target_stage=DevelopmentProject.Stage.DESIGN)
    assert advanced.stage == DevelopmentProject.Stage.DESIGN


def test_cost_and_sales_import_are_calculated_and_idempotent():
    tenant = Tenant.objects.create(name="Sales", code="sales")
    user = actor(tenant)
    project = project_fixture(tenant, user)
    estimate = project.cost_estimates.get()
    assert estimate.total_cost == Decimal("19.50")
    assert estimate.estimated_margin == Decimal("10.50")

    product, _ = finalize_product(project_id=project.id, actor=user)
    content = "spu_code,site,platform,snapshot_date,daily_sales_qty,daily_sales_amount_usd,ad_spend\n"
    content += f"{product.spu_code},TH,shopee,{timezone.localdate():%Y-%m-%d},3,30,5\n"
    first = import_sales_csv(tenant=tenant, csv_text=content, actor=user)
    second = import_sales_csv(tenant=tenant, csv_text=content, actor=user)
    assert first == {"created": 1, "updated": 0, "total": 1}
    assert second == {"created": 0, "updated": 1, "total": 1}
    assert ProductSalesSnapshot.objects.count() == 1


def test_review_reminders_include_30_and_90_day_gates():
    tenant = Tenant.objects.create(name="Review", code="review")
    user = actor(tenant)
    project = project_fixture(tenant, user)
    product, _ = finalize_product(project_id=project.id, actor=user)
    project.actual_launch_date = timezone.localdate() - timedelta(days=95)
    project.save(update_fields=["actual_launch_date"])
    periods = {row["review_period"] for row in review_reminder_candidates(tenant=tenant)}
    assert periods == {"launch_30d", "launch_90d"}


def test_listing_requires_validation_approval_and_idempotent_publish_queue():
    tenant = Tenant.objects.create(name="Listing", code="listing")
    user = actor(tenant)
    approver = actor(tenant, "approver")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="shopee-th", name="Shopee TH", country_code="TH", currency="THB")
    product = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-LIST", product_name="Listing product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=product, sku_code="SKU-LIST")
    profile = ListingProfile.objects.create(
        tenant=tenant,
        profile_no="LIST-1",
        product=product,
        store=store,
        title="Localized title",
        media=["https://example.invalid/product.jpg"],
        price=Decimal("199"),
        currency="THB",
        created_by=user,
    )
    ListingVariant.objects.create(profile=profile, sku=sku, seller_sku="SKU-LIST-TH", price=Decimal("199"))
    submit_listing_for_approval(profile_id=profile.id, actor=user)
    approve_listing(profile_id=profile.id, actor=approver)
    job, replayed = queue_listing_publication(profile_id=profile.id, actor=approver, idempotency_key="publish-1")
    replay, replayed_again = queue_listing_publication(profile_id=profile.id, actor=approver, idempotency_key="publish-1")
    assert replayed is False and replayed_again is True and replay.id == job.id
    assert job.payload_snapshot["variants"][0]["seller_sku"] == "SKU-LIST-TH"
