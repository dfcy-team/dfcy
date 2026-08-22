from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.common.exceptions import StateConflict
from apps.development.models import (
    DevelopmentCostEstimate,
    DevelopmentProductArchive,
    DevelopmentProductArchiveEvent,
    DevelopmentProject,
    DevelopmentSample,
)
from apps.development.services import (
    calculate_cost_summary,
    confirm_product_archive,
    create_product_archive,
    formalize_product_archive,
    generate_trial_product,
)
from apps.masterdata.models import PlatformMaster, StoreMaster, SupplierMaster
from apps.products.models import ProductCategory, ProductColor
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant
from rest_framework.exceptions import ValidationError


pytestmark = pytest.mark.django_db


def _user(tenant, username="archive-owner"):
    return CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def _grant(user, *codes):
    role = Role.objects.create(tenant=user.tenant, code=f"archive-role-{user.id}", name="Archive role")
    permissions = []
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "development", "action": code.rsplit(".", 1)[-1]},
        )
        permissions.append(permission)
    role.permissions.set(permissions)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)


def _project(tenant, user, with_category=True):
    ProductColor.objects.create(tenant=tenant, code="red", name="Red")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="archive-supplier", name="Archive supplier")
    category = None
    if with_category:
        l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
        l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Storage")
        category = ProductCategory.objects.create(tenant=tenant, parent=l2, level=3, code="01", name="Boxes")
    project = DevelopmentProject.objects.create(
        tenant=tenant,
        project_no="DPA-PROJECT-1",
        development_source=DevelopmentProject.Source.INTERNAL,
        product_name="Archive product",
        category="Storage",
        category_node=category,
        target_sites=["TH"],
        stage=DevelopmentProject.Stage.REVIEW,
        assigned_to=user,
        supplier=supplier,
        created_by=user,
    )
    DevelopmentSample.objects.create(
        project=project,
        supplier=supplier,
        sample_no="DPA-SAMPLE-1",
        evaluation_result=DevelopmentSample.Evaluation.PASS,
    )
    estimate = DevelopmentCostEstimate.objects.create(
        project=project,
        site="TH",
        material_cost=Decimal("10"),
        target_selling_price=Decimal("30"),
    )
    calculate_cost_summary(estimate_id=estimate.id, actor=user, approve=True)
    return project


def test_archive_creation_rejects_missing_category_when_no_source_can_be_traced():
    tenant = Tenant.objects.create(name="Archive category required", code="archive-category-required")
    user = _user(tenant, "archive-category-required-user")
    project = _project(tenant, user, with_category=False)

    with pytest.raises(ValidationError):
        create_product_archive(project_id=project.id, actor=user)


def test_virtual_archive_creation_is_idempotent_and_does_not_create_spu():
    tenant = Tenant.objects.create(name="Archive tenant", code="archive-tenant")
    user = _user(tenant)
    project = _project(tenant, user)

    archive, created = create_product_archive(
        project_id=project.id,
        actor=user,
        data={"platform": "shopee", "site": "TH", "virtual_inventory_qty": 2},
    )
    replay, replay_created = create_product_archive(
        project_id=project.id,
        actor=user,
        data={"platform": "shopee", "site": "TH", "virtual_inventory_qty": 2},
    )

    assert created is True
    assert replay_created is False
    assert replay.id == archive.id
    assert archive.status == DevelopmentProductArchive.Status.TRIAL
    assert archive.inventory_mode == "virtual"
    assert archive.formal_product_id is None
    assert archive.events.count() == 1


def test_archive_requires_confirmation_before_formalization_and_replays_safely():
    tenant = Tenant.objects.create(name="Archive lifecycle", code="archive-lifecycle")
    user = _user(tenant)
    project = _project(tenant, user)
    archive, _ = create_product_archive(project_id=project.id, actor=user)

    with pytest.raises(StateConflict):
        formalize_product_archive(archive_id=archive.id, actor=user)

    confirmed, changed = confirm_product_archive(
        archive_id=archive.id,
        actor=user,
        test_result="pass",
        test_notes="The virtual test passed.",
        idempotency_key="confirm-1",
    )
    replay_confirmed, replay_changed = confirm_product_archive(
        archive_id=archive.id,
        actor=user,
        test_result="pass",
        idempotency_key="confirm-1",
    )
    assert changed is True and replay_changed is False
    assert replay_confirmed.id == confirmed.id
    assert confirmed.status == DevelopmentProductArchive.Status.CONFIRMED
    assert confirmed.formal_product_id is None

    generate_trial_product(archive_id=archive.id, actor=user, data={"development_spu_code": "DEVARCHIVE", "color_code": "red"})
    product, product_created = formalize_product_archive(
        archive_id=archive.id,
        actor=user,
        idempotency_key="formalize-1",
    )
    replay_product, replay_created = formalize_product_archive(
        archive_id=archive.id,
        actor=user,
        idempotency_key="formalize-1",
    )
    archive.refresh_from_db()
    project.refresh_from_db()
    assert product_created is True and replay_created is False
    assert replay_product.id == product.id
    assert archive.status == DevelopmentProductArchive.Status.FORMALIZED
    assert archive.formal_product_id == product.id
    assert project.finalized_product_id == product.id
    assert list(DevelopmentProductArchiveEvent.objects.filter(archive=archive).values_list("action", flat=True)) == [
        "created",
        "trial_confirmed",
        "trial_product_generated",
        "formalized",
    ]


def test_archive_api_is_tenant_scoped_and_has_explicit_actions():
    tenant = Tenant.objects.create(name="Archive API", code="archive-api")
    user = _user(tenant, "archive-api-user")
    _grant(
        user,
        "development.product_archive.view",
        "development.product_archive.manage",
        "development.product_archive.confirm",
    )
    project = _project(tenant, user)
    client = APIClient()
    client.force_authenticate(user=user)

    project_number_payload = client.post(
        "/api/internal/development/product-archives/",
        {"project": project.project_no, "category_node": project.category_node_id},
        format="json",
    )
    assert project_number_payload.status_code == 400, project_number_payload.json()
    assert "project" in project_number_payload.json()["data"]

    created = client.post(
        "/api/internal/development/product-archives/",
        {"project": project.id, "platform": "lazada", "site": "MY", "virtual_inventory_qty": 1},
        format="json",
    )
    assert created.status_code == 201, created.json()
    archive_id = created.json()["data"]["id"]
    assert created.json()["data"]["inventory_mode"] == "virtual"
    assert created.json()["data"]["status"] == "trial"

    blocked = client.post(f"/api/internal/development/product-archives/{archive_id}/formalize/", {}, format="json")
    assert blocked.status_code == 409

    confirmed = client.post(
        f"/api/internal/development/product-archives/{archive_id}/confirm-trial/",
        {"test_result": "pass"},
        format="json",
    )
    assert confirmed.status_code == 200
    generated = client.post(
        f"/api/internal/development/product-archives/{archive_id}/generate-trial/",
        {"development_spu_code": "DEVAPI", "color_code": "red", "spec_values": {}},
        format="json",
    )
    assert generated.status_code == 200, generated.json()
    formalized = client.post(
        f"/api/internal/development/product-archives/{archive_id}/formalize/",
        {},
        format="json",
    )
    assert formalized.status_code == 200
    assert formalized.json()["data"]["archive"]["status"] == "formalized"
    assert formalized.json()["data"]["spu_code"].isdigit()


def test_archive_api_accepts_complete_dropdown_payload_and_normalizes_nullable_market_fields():
    tenant = Tenant.objects.create(name="Archive dropdown API", code="archive-dropdown-api")
    user = _user(tenant, "archive-dropdown-user")
    _grant(user, "development.product_archive.view", "development.product_archive.manage")
    project = _project(tenant, user)
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type=PlatformMaster.PlatformType.SHOPEE,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="shopee-ph",
        name="Shopee PH",
        country_code="PH",
        currency="PHP",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    created = client.post(
        "/api/internal/development/product-archives/",
        {
            "project": project.id,
            "product_name": "PH archive product",
            "category_node": project.category_node_id,
            "platform_master": platform.id,
            "store_master": store.id,
            "platform": "shopee",
            "site": "PH",
            "virtual_inventory_qty": 7,
            "test_notes": "dropdown payload",
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    archive_id = created.json()["data"]["id"]
    assert created.json()["data"]["project_id"] == project.id
    assert created.json()["data"]["platform_master"] == platform.id
    assert created.json()["data"]["store_master"] == store.id
    assert created.json()["data"]["site"] == "PH"

    cleared = client.patch(
        f"/api/internal/development/product-archives/{archive_id}/",
        {"platform_master": None, "store_master": None, "platform": None, "site": None},
        format="json",
    )
    assert cleared.status_code == 200, cleared.json()
    assert cleared.json()["data"]["platform_master"] is None
    assert cleared.json()["data"]["store_master"] is None
    assert cleared.json()["data"]["platform"] == "internal"
    assert cleared.json()["data"]["site"] == "internal"
