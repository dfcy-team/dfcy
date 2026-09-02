from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.development.models import DevelopmentCostEstimate, DevelopmentProductArchive, DevelopmentProject, DevelopmentSample
from apps.development.services import (
    calculate_cost_summary,
    confirm_product_archive,
    create_product_archive,
    formalize_product_archive,
    generate_trial_product,
)
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
from apps.products.models import ProductCategory, ProductColor, ProductSPU
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _fixture(prefix="trial"):
    tenant = Tenant.objects.create(name=f"{prefix} tenant", code=f"{prefix}-tenant")
    user = CustomUser.objects.create_user(
        username=f"{prefix}-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL
    )
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Storage")
    category = ProductCategory.objects.create(
        tenant=tenant,
        parent=l2,
        level=3,
        code="01",
        name="Boxes",
        spec_dimensions=[{"code": "size", "name": "Size", "values": ["10cm"]}],
    )
    project = DevelopmentProject.objects.create(
        tenant=tenant,
        project_no=f"{prefix}-project",
        development_source=DevelopmentProject.Source.INTERNAL,
        product_name="Trial box",
        category_node=category,
        category=category.name,
        assigned_to=user,
        created_by=user,
    )
    archive, _ = create_product_archive(project_id=project.id, actor=user)
    color = ProductColor.objects.create(tenant=tenant, code="red", name="Red")
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type=PlatformMaster.PlatformType.SHOPEE,
        status=StatusChoices.ACTIVE,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="shopee-th",
        name="Shopee TH",
        country_code="TH",
        currency="THB",
        status=StatusChoices.ACTIVE,
    )
    return tenant, user, project, archive, color, platform, store


def test_development_product_generation_is_idempotent_and_uses_manual_coding_rules():
    _tenant, user, _project, archive, _color, _platform, _store = _fixture("trial-idempotent")

    first, created = generate_trial_product(
        archive_id=archive.id,
        actor=user,
        data={"development_spu_code": "DEVIDEMP", "color_code": "red", "spec_values": {"size": "10cm"}, "season_code": "0"},
    )
    replay, replay_created = generate_trial_product(
        archive_id=archive.id,
        actor=user,
        data={"development_spu_code": "DEVIDEMP", "color_code": "red", "spec_values": {"size": "10cm"}, "season_code": "0"},
    )

    assert created is True and replay_created is False
    assert replay.trial_product_id == first.trial_product_id
    assert replay.trial_sku_id == first.trial_sku_id
    assert replay.trial_product.lifecycle_status == "draft"
    assert replay.trial_product.sales_status == "not_listed"
    assert replay.development_spu_code == "DEVIDEMP"
    assert replay.trial_product.spu_code == "DEVIDEMP"
    assert replay.trial_sku.sku_code == "DEVIDEMP-RED-10CM"
    assert replay.trial_sku.sku_code.count("-") == 2
    assert replay.trial_sku.specification == "10CM"
    assert replay.events.filter(action="trial_product_generated").count() == 1


def test_development_codes_require_manual_namespace_and_use_std_without_specification():
    tenant, user, _project, archive, _color, _platform, _store = _fixture("trial-code-rules")

    with pytest.raises(ValidationError, match="at least one letter"):
        generate_trial_product(
            archive_id=archive.id,
            actor=user,
            data={"development_spu_code": "123456", "color_code": "red"},
        )
    with pytest.raises(ValidationError, match="separators and whitespace"):
        generate_trial_product(
            archive_id=archive.id,
            actor=user,
            data={"development_spu_code": "DEV-BAD", "color_code": "red"},
        )

    ProductSPU.objects.create(
        tenant=tenant,
        spu_code="DEVTAKEN",
        product_name="Existing development product",
        lifecycle_status=ProductSPU.LifecycleStatus.DRAFT,
        sales_status=ProductSPU.SalesStatus.NOT_LISTED,
    )
    with pytest.raises(ValidationError, match="already used"):
        generate_trial_product(
            archive_id=archive.id,
            actor=user,
            data={"development_spu_code": "devtaken", "color_code": "red"},
        )

    generated, created = generate_trial_product(
        archive_id=archive.id,
        actor=user,
        data={"development_spu_code": "devstd", "color_code": "red", "spec_values": {}},
    )
    assert created is True
    assert generated.development_spu_code == "DEVSTD"
    assert generated.trial_sku.sku_code == "DEVSTD-RED-STD"
    assert generated.trial_sku.sku_code.count("-") == 2


def test_formalization_creates_distinct_formal_product_and_links_project():
    _tenant, user, project, archive, _color, _platform, _store = _fixture("trial-formalize")
    generate_trial_product(archive_id=archive.id, actor=user, data={"development_spu_code": "DEVFORMAL", "color_code": "red"})
    confirm_product_archive(archive_id=archive.id, actor=user)

    product, created = formalize_product_archive(archive_id=archive.id, actor=user)
    archive.refresh_from_db()
    project.refresh_from_db()
    assert created is True
    assert archive.formal_product_id == product.id
    assert archive.formal_product_id != archive.trial_product_id
    assert archive.formal_sku_id is not None
    assert archive.formal_sku.spu_id == product.id
    assert archive.formal_sku.sku_code != archive.trial_sku.sku_code
    assert archive.formal_sku.sku_code.startswith(product.spu_code + "-")
    assert project.finalized_product_id == product.id


def test_archive_market_records_require_tenant_and_consistent_platform_store():
    tenant, user, _project, archive, _color, platform, store = _fixture("trial-market")
    other_tenant = Tenant.objects.create(name="Other", code="trial-market-other")
    foreign_platform = PlatformMaster.objects.create(
        tenant=other_tenant,
        code="other",
        name="Other",
        platform_type=PlatformMaster.PlatformType.OTHER,
    )
    with pytest.raises(ValidationError):
        create_product_archive(
            project_id=archive.project_id,
            actor=user,
            data={"platform_master": foreign_platform.id, "store_master": store.id, "site": "TH"},
        )
    other_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="shopee-sg",
        name="Shopee SG",
        country_code="SG",
        currency="SGD",
    )
    with pytest.raises(ValidationError):
        create_product_archive(
            project_id=archive.project_id,
            actor=user,
            data={"platform_master": platform.id, "store_master": other_store.id, "site": "TH"},
        )


def test_api_generates_trial_products_with_exact_manage_permission():
    _tenant, user, _project, archive, _color, platform, store = _fixture("trial-api")
    role = Role.objects.create(tenant=user.tenant, code="trial-api-role", name="Trial API role")
    permission, _ = Permission.objects.get_or_create(
        code="development.product_archive.manage",
        defaults={"name": "Archive manage", "module": "development", "action": "manage"},
    )
    role.permissions.add(permission)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    client = APIClient()
    client.force_authenticate(user=user)

    updated = client.patch(
        f"/api/internal/development/product-archives/{archive.id}/",
        {"platform_master": platform.id, "store_master": store.id, "site": "TH"},
        format="json",
    )
    assert updated.status_code == 200, updated.json()
    assert updated.json()["data"]["platform_master"] == platform.id
    assert updated.json()["data"]["store_master"] == store.id

    generated = client.post(
        f"/api/internal/development/product-archives/{archive.id}/generate-trial/",
        {"development_spu_code": "DEVAPI", "color_code": "red", "spec_values": {}},
        format="json",
    )
    assert generated.status_code == 200, generated.json()
    assert generated.json()["data"]["trial_spu_code"]
    replay = client.post(
        f"/api/internal/development/product-archives/{archive.id}/generate-trial/",
        {"development_spu_code": "DEVAPI", "color_code": "red", "spec_values": {}},
        format="json",
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["changed"] is False
