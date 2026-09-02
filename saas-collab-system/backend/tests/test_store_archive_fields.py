import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCategory
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _manager(tenant):
    user = CustomUser.objects.create_user("store-archive-manager", password="not-a-real-password", tenant=tenant, user_type="internal")
    role = Role.objects.create(tenant=tenant, code="store-archive-manager-role", name="Store archive manager")
    permission, _ = Permission.objects.get_or_create(code="masterdata.manage", defaults={"name": "masterdata.manage", "module": "masterdata", "action": "manage"})
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def test_store_archive_fields_and_import_are_tenant_scoped_and_idempotent():
    tenant = Tenant.objects.create(name="Store archive tenant", code="store-archive")
    manager = _manager(tenant)
    operator = CustomUser.objects.create_user("store-operator", password="not-a-real-password", tenant=tenant, user_type="internal", full_name="运营")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    category = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="服装")
    client = APIClient(); client.force_authenticate(manager)

    response = client.post("/api/internal/master-data/stores/", {
        "platform_id": platform.pk, "code": "store-ph", "name": "菲律宾店铺", "platform_store_name": "Shopee PH",
        "category_id": category.pk, "operator_id": operator.pk, "is_connected": True, "tactical_client": "战斧-01",
        "country_code": "PH", "currency": "PHP", "timezone": "Asia/Manila",
    }, format="json")
    assert response.status_code == 201
    assert response.data["data"]["operator_name"] == "运营"
    assert response.data["data"]["is_connected"] is True

    csv = "店铺档案编码,店铺名称,平台,平台店铺名,类目,负责运营,是否建联,战斧客户端,国家代码,币种,时区\nstore-ph,菲律宾店铺更新,Shopee,Shopee PH Updated,1,store-operator,是,战斧-02,PH,PHP,Asia/Manila\n".encode("utf-8-sig")
    imported = client.post("/api/internal/master-data/stores/", {"file": SimpleUploadedFile("stores.csv", csv, content_type="text/csv")})
    assert imported.status_code == 200
    assert imported.data["data"]["created"] == 0
    assert imported.data["data"]["updated"] == 1
    store = StoreMaster.objects.get(tenant=tenant, code="store-ph")
    assert store.name == "菲律宾店铺更新"
    assert store.tactical_client == "战斧-02"
