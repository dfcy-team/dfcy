import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCategory
from apps.products.serializers import ProductCategorySerializer
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _user(tenant, username):
    return CustomUser.objects.create_user(
        username=username,
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def _client(user, *permission_codes):
    role = Role.objects.create(
        tenant=user.tenant,
        code=f"{user.username}-role",
        name=f"Role for {user.username}",
    )
    role.permissions.add(*Permission.objects.filter(code__in=permission_codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=DataScope.ScopeType.ALL,
        config={},
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _category_tree(tenant, prefix="1"):
    l1 = ProductCategory.objects.create(
        tenant=tenant,
        level=ProductCategory.Level.L1,
        code=prefix,
        name="Home",
    )
    l2 = ProductCategory.objects.create(
        tenant=tenant,
        parent=l1,
        level=ProductCategory.Level.L2,
        code="01",
        name="Storage",
    )
    l3 = ProductCategory.objects.create(
        tenant=tenant,
        parent=l2,
        level=ProductCategory.Level.L3,
        code="01",
        name="Boxes",
    )
    return l1, l2, l3


def test_category_color_model_and_serializer_validate_hex_and_l2_only():
    tenant = Tenant.objects.create(name="Category color tenant", code="foundation-color-model")
    l1, l2, l3 = _category_tree(tenant)

    l2.row_background_color = "#a1B2c3"
    l2.save()
    serializer = ProductCategorySerializer(l2)
    assert serializer.data["row_background_color"] == "#a1B2c3"

    ordinary_update = ProductCategorySerializer(
        l2,
        data={"row_background_color": "#FFFFFF"},
        partial=True,
    )
    assert ordinary_update.is_valid(), ordinary_update.errors
    assert "row_background_color" not in ordinary_update.validated_data
    assert ordinary_update.save().row_background_color == "#a1B2c3"

    for value in ("#12345", "#1234567", "123456", "#GGGGGG"):
        l2.row_background_color = value
        with pytest.raises(DjangoValidationError):
            l2.full_clean()

    for category in (l1, l3):
        category.row_background_color = "#123456"
        with pytest.raises(DjangoValidationError):
            category.full_clean()


def test_category_api_returns_updated_color_and_keeps_tenants_isolated():
    tenant = Tenant.objects.create(name="Category API tenant", code="foundation-color-api")
    foreign_tenant = Tenant.objects.create(name="Foreign category tenant", code="foundation-color-foreign")
    user = _user(tenant, "foundation-color-api-user")
    client = _client(user, "products.category.view", "products.category.manage")
    l1, l2, l3 = _category_tree(tenant)
    _, foreign_l2, _ = _category_tree(foreign_tenant, prefix="2")

    response = client.patch(
        f"/api/internal/products/categories/{l2.pk}/",
        {"name": "Storage renamed", "row_background_color": "#1122Aa"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["data"]["row_background_color"] == ""
    l2.refresh_from_db()
    assert l2.name == "Storage renamed"
    assert l2.row_background_color == ""

    for category in (l1, l3):
        response = client.patch(
            f"/api/internal/products/categories/{category.pk}/",
            {"row_background_color": "#123456"},
            format="json",
        )
        assert response.status_code == 200
        category.refresh_from_db()
        assert category.row_background_color == ""

    response = client.patch(
        f"/api/internal/products/categories/{foreign_l2.pk}/",
        {"row_background_color": "#abcdef"},
        format="json",
    )
    assert response.status_code == 404
    foreign_l2.refresh_from_db()
    assert foreign_l2.row_background_color == ""


def test_foundation_settings_endpoint_is_permissioned_and_bulk_update_is_tenant_scoped():
    tenant = Tenant.objects.create(name="Foundation settings tenant", code="foundation-settings")
    foreign_tenant = Tenant.objects.create(name="Foreign settings tenant", code="foundation-settings-foreign")
    viewer = _user(tenant, "foundation-settings-viewer")
    manager = _user(tenant, "foundation-settings-manager")
    viewer_client = _client(viewer, "masterdata.settings.view")
    manager_client = _client(manager, "masterdata.settings.view", "masterdata.settings.manage")
    _, l2, l3 = _category_tree(tenant)
    _, foreign_l2, _ = _category_tree(foreign_tenant, prefix="2")

    response = viewer_client.get("/api/internal/products/category-background-colors/")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]] == [l2.pk]
    assert response.json()["data"][0]["row_background_color"] == ""
    assert viewer_client.put(
        "/api/internal/products/category-background-colors/",
        {"items": [{"category_id": l2.pk, "row_background_color": "#123456"}]},
        format="json",
    ).status_code == 403

    response = manager_client.put(
        "/api/internal/products/category-background-colors/",
        {"items": [{"category_id": l2.pk, "row_background_color": "#aBcD12"}]},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["data"][0]["row_background_color"] == "#ABCD12"
    l2.refresh_from_db()
    assert l2.row_background_color == "#ABCD12"
    assert l3.row_background_color == ""

    response = manager_client.put(
        "/api/internal/products/category-background-colors/",
        {"items": [{"category_id": l2.pk, "row_background_color": "not-a-color"}]},
        format="json",
    )
    assert response.status_code == 400
    assert "items" in response.json()["data"]
    l2.refresh_from_db()
    assert l2.row_background_color == "#ABCD12"

    response = manager_client.put(
        "/api/internal/products/category-background-colors/",
        {"items": [{"category_id": l3.pk, "row_background_color": "#FFFFFF"}]},
        format="json",
    )
    assert response.status_code == 400
    l3.refresh_from_db()
    assert l3.row_background_color == ""

    response = manager_client.put(
        "/api/internal/products/category-background-colors/",
        {
            "items": [
                {"category_id": l2.pk, "row_background_color": "#FFFFFF"},
                {"category_id": foreign_l2.pk, "row_background_color": "#000000"},
            ]
        },
        format="json",
    )
    assert response.status_code == 400
    l2.refresh_from_db()
    foreign_l2.refresh_from_db()
    assert l2.row_background_color == "#ABCD12"
    assert foreign_l2.row_background_color == ""


def test_masterdata_settings_permissions_are_catalogued_and_sync_to_administrator():
    definitions = {item["code"]: item for item in PERMISSION_DEFINITIONS}
    expected_codes = {"masterdata.settings.view", "masterdata.settings.manage"}
    assert expected_codes <= definitions.keys()
    for code in expected_codes:
        permission = Permission.objects.get(code=code)
        for field, expected in permission_defaults(definitions[code]).items():
            assert getattr(permission, field) == expected

    tenant = Tenant.objects.create(name="Foundation permissions tenant", code="foundation-permissions")
    administrator = Role.objects.create(
        tenant=tenant,
        code="administrator",
        name="管理员",
        status=Role.Status.ACTIVE,
    )
    administrator.permissions.clear()
    call_command("sync_permissions")
    assert expected_codes <= set(administrator.permissions.values_list("code", flat=True))
