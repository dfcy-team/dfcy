import pytest

from apps.accounts.models import CustomUser, ExternalUserProfile, InternalUserProfile
from apps.tenants.models import Department, Tenant


@pytest.mark.django_db
def test_tenant_can_be_created():
    tenant = Tenant.objects.create(name="Demo Tenant", code="demo")

    assert tenant.id is not None
    assert tenant.status == Tenant.Status.ACTIVE


@pytest.mark.django_db
def test_department_belongs_to_tenant():
    tenant = Tenant.objects.create(name="Demo Tenant", code="demo")
    department = Department.objects.create(tenant=tenant, name="Operations")

    assert department.tenant == tenant
    assert department.status == Department.Status.ACTIVE


@pytest.mark.django_db
def test_custom_user_can_be_created_with_tenant():
    tenant = Tenant.objects.create(name="Demo Tenant", code="demo")
    user = CustomUser.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="not-a-real-secret",
        phone="13800000000",
        user_type=CustomUser.UserType.INTERNAL,
        tenant=tenant,
    )

    assert user.id is not None
    assert user.tenant == tenant
    assert user.check_password("not-a-real-secret")
    assert user.is_active is True
    assert user.is_staff is False


@pytest.mark.django_db
def test_internal_and_external_profiles_can_be_created():
    tenant = Tenant.objects.create(name="Demo Tenant", code="demo")
    department = Department.objects.create(tenant=tenant, name="Finance")
    internal_user = CustomUser.objects.create_user(
        username="internal",
        user_type=CustomUser.UserType.INTERNAL,
        tenant=tenant,
    )
    external_user = CustomUser.objects.create_user(
        username="external",
        user_type=CustomUser.UserType.EXTERNAL,
        tenant=tenant,
    )

    internal_profile = InternalUserProfile.objects.create(
        user=internal_user,
        tenant=tenant,
        department=department,
        employee_no="E001",
    )
    external_profile = ExternalUserProfile.objects.create(
        user=external_user,
        tenant=tenant,
        supplier_id=10001,
        company_name="Example Supplier",
    )

    assert internal_profile.department == department
    assert external_profile.supplier_id == 10001
