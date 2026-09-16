import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


def _client(tenant, suffix="manager"):
    user = CustomUser.objects.create_user(username=f"recode-{tenant.code}-{suffix}", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"recode-{suffix}", name="Recode manager")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _spu(tenant, code="10101A001", **overrides):
    values = {"tenant": tenant, "spu_code": code, "product_name": "Recode product", "season_code": code[-4:-3], "lifecycle_status": ProductSPU.LifecycleStatus.DRAFT, "sales_status": ProductSPU.SalesStatus.NOT_LISTED}
    values.update(overrides)
    return ProductSPU.objects.create(**values)


def test_recode_preview_and_execute_updates_spu_skus_and_legacy_mappings():
    tenant = Tenant.objects.create(name="Recode tenant", code="recode-one")
    client = _client(tenant)
    spu = _spu(tenant)
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="10101A001-blue-20cm", product_name="Blue SKU")
    rows = [{"row_number": 7, "source_spu_code": spu.spu_code, "product_name": "Renamed SPU", "attribute_code": "b", "serial_number": "012"}]
    preview = client.post("/api/internal/products/spus/recode/", {"dry_run": True, "atomic": True, "rows": rows}, format="json")
    assert preview.status_code == 200, preview.content
    result = preview.json()["data"]["results"][0]
    assert result["target_spu_code"] == "10101B012" and result["status"] == "ready" and result["conflicts"] == []
    assert result["sku_mappings"] == [{"source_sku_code": "10101A001-blue-20cm", "target_sku_code": "10101B012-blue-20cm", "conflicts": []}]
    spu.refresh_from_db(); sku.refresh_from_db()
    assert spu.spu_code == "10101A001" and sku.sku_code == "10101A001-blue-20cm"
    applied = client.post("/api/internal/products/spus/recode/", {"dry_run": False, "atomic": True, "rows": rows}, format="json")
    assert applied.status_code == 200, applied.content
    spu.refresh_from_db(); sku.refresh_from_db()
    assert (spu.spu_code, spu.legacy_spu_code, spu.season_code, spu.product_name) == ("10101B012", "10101A001", "B", "Renamed SPU")
    assert (sku.sku_code, sku.legacy_sku_code) == ("10101B012-blue-20cm", "10101A001-blue-20cm")
    assert client.get("/api/internal/products/spus/", {"search": "10101A001"}).json()["data"]["count"] == 1


def test_recode_returns_all_conflicts_without_writing_atomic_batch():
    tenant = Tenant.objects.create(name="Conflict tenant", code="recode-conflict")
    client = _client(tenant)
    frozen = _spu(tenant, "10101A001", is_code_frozen=True)
    valid = _spu(tenant, "10101A002", product_name="Valid")
    _spu(tenant, "10101B009", product_name="Occupied")
    frozen_sku = ProductSKU.objects.create(tenant=tenant, spu=frozen, sku_code="10101A001-red", is_code_frozen=True)
    valid_sku = ProductSKU.objects.create(tenant=tenant, spu=valid, sku_code="10101A002-blue")
    response = client.post("/api/internal/products/spus/recode/", {"dry_run": False, "atomic": True, "rows": [{"row_number": 2, "source_spu_code": frozen.spu_code, "attribute_code": "C", "serial_number": "003"}, {"row_number": 3, "source_spu_code": valid.spu_code, "attribute_code": "B", "serial_number": "009"}]}, format="json")
    assert response.status_code == 409
    results = response.json()["data"]["results"]
    assert {item["code"] for item in results[0]["conflicts"]} >= {"state_not_allowed", "sku_frozen"}
    assert {item["code"] for item in results[1]["conflicts"]} == {"spu_target_exists"}
    frozen.refresh_from_db(); valid.refresh_from_db(); frozen_sku.refresh_from_db(); valid_sku.refresh_from_db()
    assert frozen.spu_code == "10101A001" and valid.spu_code == "10101A002" and frozen_sku.sku_code == "10101A001-red" and valid_sku.sku_code == "10101A002-blue"


def test_recode_reports_format_missing_source_and_duplicate_conflicts():
    tenant = Tenant.objects.create(name="Validation tenant", code="recode-validation")
    client = _client(tenant)
    first = _spu(tenant, "10101A001")
    second = _spu(tenant, "10101A002", product_name="Second")
    response = client.post("/api/internal/products/spus/recode/", {"dry_run": True, "rows": [{"row_number": 2, "source_spu_code": "MISSING", "attribute_code": "?", "serial_number": "12"}, {"row_number": 3, "source_spu_code": first.spu_code, "attribute_code": "D", "serial_number": "010"}, {"row_number": 4, "source_spu_code": second.spu_code, "attribute_code": "D", "serial_number": "010"}]}, format="json")
    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert {item["code"] for item in results[0]["conflicts"]} >= {"source_not_unique", "invalid_attribute", "invalid_sequence"}
    assert results[1]["status"] == "ready"
    assert {item["code"] for item in results[2]["conflicts"]} == {"duplicate_target"}
