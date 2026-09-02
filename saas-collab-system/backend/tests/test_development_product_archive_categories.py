import pytest
from rest_framework.test import APIRequestFactory

from apps.accounts.models import CustomUser
from apps.development.models import DevelopmentProductArchive, DevelopmentProject
from apps.development.serializers import DevelopmentProductArchiveSerializer
from apps.development.services import confirm_product_archive, create_product_archive, formalize_product_archive
from apps.products.models import ProductCategory, ProductResearch, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _category_tree(tenant, prefix="1"):
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code=prefix, name="Home")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Storage")
    return ProductCategory.objects.create(tenant=tenant, parent=l2, level=3, code="01", name="Boxes")


def _user(tenant):
    return CustomUser.objects.create_user(
        username=f"archive-category-{tenant.id}",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def _project(tenant, user, category=None, requirement=None):
    return DevelopmentProject.objects.create(
        tenant=tenant,
        project_no=f"CATEGORY-PROJECT-{tenant.id}",
        requirement=requirement,
        development_source=DevelopmentProject.Source.INTERNAL,
        product_name="Structured archive product",
        category_node=category,
        category=category.name if category else "",
        target_sites=["TH"],
        assigned_to=user,
        created_by=user,
    )


def test_archive_uses_active_leaf_category_and_can_be_created_without_stage_gates():
    tenant = Tenant.objects.create(name="Archive categories", code="archive-categories")
    user = _user(tenant)
    category = _category_tree(tenant)
    project = _project(tenant, user, category=category)

    archive, created = create_product_archive(project_id=project.id, actor=user)

    assert created is True
    assert archive.category_node_id == category.id
    assert archive.category == category.name
    assert archive.status == DevelopmentProductArchive.Status.TRIAL
    # Archive creation is intentionally independent of samples/cost approval.
    assert not project.samples.exists()
    assert not project.cost_estimates.exists()


def test_archive_serializer_rejects_cross_tenant_category():
    tenant = Tenant.objects.create(name="Archive owner", code="archive-owner")
    other_tenant = Tenant.objects.create(name="Other owner", code="archive-other")
    user = _user(tenant)
    project = _project(tenant, user)
    foreign_category = _category_tree(other_tenant)
    request = APIRequestFactory().post("/archives/")
    request.user = user

    serializer = DevelopmentProductArchiveSerializer(
        data={"project": project.id, "category_node": foreign_category.id},
        context={"request": request},
    )

    assert serializer.is_valid() is False
    assert "category_node" in serializer.errors


def test_formalization_copies_category_to_draft_unlisted_product():
    tenant = Tenant.objects.create(name="Archive formalize categories", code="archive-formalize-categories")
    user = _user(tenant)
    category = _category_tree(tenant)
    project = _project(tenant, user, category=category)
    archive, _ = create_product_archive(project_id=project.id, actor=user)
    confirm_product_archive(archive_id=archive.id, actor=user)

    product, created = formalize_product_archive(archive_id=archive.id, actor=user)

    assert created is True
    product.refresh_from_db()
    assert product.category_node_id == category.id
    assert product.category == category.name
    assert product.lifecycle_status == ProductSPU.LifecycleStatus.DRAFT
    assert product.sales_status == ProductSPU.SalesStatus.NOT_LISTED


def test_archive_prefers_requirement_category_when_project_has_none():
    tenant = Tenant.objects.create(name="Archive requirement category", code="archive-requirement-category")
    user = _user(tenant)
    category = _category_tree(tenant)
    requirement = ProductResearch.objects.create(
        tenant=tenant,
        research_no="REQ-CATEGORY-1",
        product_name="Requirement category product",
        category_node=category,
        created_by=user,
    )
    project = _project(tenant, user, requirement=requirement)

    archive, _ = create_product_archive(project_id=project.id, actor=user)

    assert archive.category_node_id == category.id
    assert archive.category == category.name
