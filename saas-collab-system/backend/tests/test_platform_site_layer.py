import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import PlatformMaster, PlatformSiteMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def make_platform(tenant, code="shopee", platform_type="shopee"):
    return PlatformMaster.objects.create(tenant=tenant, code=code, name=code.title(), platform_type=platform_type)


def make_site(tenant, platform, site_code="PH"):
    return PlatformSiteMaster.objects.create(
        tenant=tenant, platform=platform, site_code=site_code, name=f"{platform.name} {site_code}",
        country_code=site_code, currency_code="PHP", timezone="Asia/Manila", language_codes=["en"],
    )


def make_user_with_scope(tenant, username):
    user = CustomUser.objects.create_user(username=username, password="not-real", tenant=tenant, user_type="internal")
    permission, _ = Permission.objects.get_or_create(code="masterdata.view", defaults={"name": "Master view", "module": "masterdata", "action": "view"})
    role = Role.objects.create(tenant=tenant, code=f"role-{username}", name=f"Role {username}")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def test_platform_site_tenant_and_unique_boundaries():
    tenant = Tenant.objects.create(name="Tenant A", code="site-a")
    other = Tenant.objects.create(name="Tenant B", code="site-b")
    platform = make_platform(tenant)
    other_platform = make_platform(other)
    site = make_site(tenant, platform)
    site.full_clean()

    invalid = PlatformSiteMaster(tenant=tenant, platform=other_platform, site_code="PH", name="Invalid", country_code="PH")
    with pytest.raises(DjangoValidationError):
        invalid.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        make_site(tenant, platform)


def test_store_site_is_optional_and_must_match_selected_platform():
    tenant = Tenant.objects.create(name="Tenant", code="store-site")
    shopee = make_platform(tenant)
    amazon = make_platform(tenant, "amazon", "amazon")
    site = make_site(tenant, shopee)
    legacy = StoreMaster.objects.create(
        tenant=tenant, platform=shopee, code="legacy", name="Legacy", country_code="PH", currency="PHP"
    )
    assert legacy.platform_site_id is None

    invalid = StoreMaster(
        tenant=tenant, platform=amazon, platform_site=site, code="invalid", name="Invalid",
        country_code="PH", currency="PHP", fulfillment_modes=["platform_fulfillment"],
    )
    with pytest.raises(DjangoValidationError):
        invalid.full_clean()


def test_platform_site_api_is_tenant_isolated():
    tenant = Tenant.objects.create(name="Tenant A", code="api-site-a")
    other = Tenant.objects.create(name="Tenant B", code="api-site-b")
    own = make_site(tenant, make_platform(tenant))
    make_site(other, make_platform(other))
    user = make_user_with_scope(tenant, "site-viewer")
    client = APIClient(); client.force_authenticate(user)
    response = client.get("/api/internal/master-data/platform-sites/")
    assert response.status_code == 200
    assert [item["id"] for item in response.data["data"]["results"]] == [own.id]
