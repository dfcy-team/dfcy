import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.products.models import (
    ProductLegacyItem,
    ProductSKU,
    ProductSPU,
    ProductStatus,
    ProductStatusSnapshot,
)
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant
from apps.products.views import _product_reverse_references


def _client_user(tenant, username, *, scope_type=DataScope.ScopeType.ALL, scope_config=None):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Product action role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config or {},
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.mark.django_db
def test_spu_delete_checks_all_reverse_references_and_returns_deactivation_hint():
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-spu")
    _user, client = _client_user(tenant, "product-action-spu-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-REF", product_name="Referenced")
    ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-REF")

    response = client.delete(f"/api/internal/products/spus/{spu.id}/")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    assert response.json()["data"]["can_deactivate"] is True
    assert response.json()["data"]["references"]
    assert ProductSPU.objects.filter(pk=spu.pk).exists()


@pytest.mark.django_db
def test_sku_delete_checks_status_and_legacy_references_and_can_deactivate():
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-sku")
    _user, client = _client_user(tenant, "product-action-sku-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-SKU-REF", product_name="SKU")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-REF-ALL")
    ProductStatusSnapshot.objects.create(
        tenant=tenant,
        sku=sku,
        source=ProductStatusSnapshot.Source.MANUAL,
        calculated_status=ProductStatus.ACTIVE,
    )

    response = client.delete(f"/api/internal/products/skus/{sku.id}/")

    assert response.status_code == 409
    assert response.json()["data"]["can_deactivate"] is True
    assert ProductSKU.objects.filter(pk=sku.pk).exists()

    # The legacy bridge is also a protected business reference.
    ProductStatusSnapshot.objects.filter(sku=sku).delete()
    ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-REF-ALL",
        product_name="Legacy",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
        generated_sku=sku,
    )
    response = client.delete(f"/api/internal/products/skus/{sku.id}/")
    assert response.status_code == 409
    assert "references" in response.json()["data"]


@pytest.mark.django_db
def test_unreferenced_sku_and_pending_legacy_can_be_deleted():
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-delete")
    _user, client = _client_user(tenant, "product-action-delete-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-DELETE", product_name="Delete")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-DELETE")
    # Remove the SKU first so the SPU itself is also left unreferenced.
    response = client.delete(f"/api/internal/products/skus/{sku.id}/")
    assert response.status_code == 200
    assert response.json()["data"] == {"deleted": True, "id": sku.id}
    assert not ProductSKU.objects.filter(pk=sku.pk).exists()

    response = client.delete(f"/api/internal/products/spus/{spu.id}/")
    assert response.status_code == 200
    assert response.json()["data"] == {"deleted": True, "id": spu.id}
    assert not ProductSPU.objects.filter(pk=spu.pk).exists()

    legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-DELETE",
        product_name="Pending",
        status=ProductLegacyItem.Status.PENDING,
    )
    response = client.delete(f"/api/internal/products/legacy-items/{legacy.id}/")
    assert response.status_code == 200
    assert response.json()["data"] == {"deleted": True, "id": legacy.id}
    assert not ProductLegacyItem.objects.filter(pk=legacy.pk).exists()


@pytest.mark.django_db
def test_spu_delete_ignores_unmanaged_read_only_reverse_projections(monkeypatch):
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-unmanaged")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-UNMANAGED", product_name="Unmanaged")
    relation = next(
        relation
        for relation in ProductSPU._meta.related_objects
        if not relation.related_model._meta.managed
    )

    class ExplodingProjectionAccessor:
        def __get__(self, _instance, _owner=None):
            raise AssertionError("unmanaged projection must not be queried during deletion")

    monkeypatch.setattr(ProductSPU, relation.get_accessor_name(), ExplodingProjectionAccessor())

    assert _product_reverse_references(spu) == []


@pytest.mark.django_db
def test_spu_delete_converts_database_fk_race_to_state_conflict(monkeypatch):
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-integrity")
    _user, client = _client_user(tenant, "product-action-integrity-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-INTEGRITY", product_name="Integrity")

    def raise_integrity_error(_self, *args, **kwargs):
        raise IntegrityError("simulated concurrent foreign-key reference")

    monkeypatch.setattr(ProductSPU, "delete", raise_integrity_error)
    response = client.delete(f"/api/internal/products/spus/{spu.id}/")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    assert response.json()["data"] == {
        "can_deactivate": True,
        "references": ["protected_relation"],
    }
    assert ProductSPU.objects.filter(pk=spu.pk).exists()


@pytest.mark.django_db
def test_spu_and_sku_status_actions_validate_values_and_are_tenant_scoped():
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-status")
    other_tenant = Tenant.objects.create(name="Other tenant", code="product-action-status-other")
    _user, client = _client_user(tenant, "product-action-status-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-STATUS-ACTION", product_name="Status")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-STATUS-ACTION")
    foreign_spu = ProductSPU.objects.create(tenant=other_tenant, spu_code="SPU-FOREIGN", product_name="Foreign")
    foreign_sku = ProductSKU.objects.create(tenant=other_tenant, spu=foreign_spu, sku_code="SKU-FOREIGN")

    response = client.post(
        f"/api/internal/products/spus/{spu.id}/status/",
        {"lifecycle_status": "active", "sales_status": "on_sale", "reason": "manual review"},
        format="json",
    )
    assert response.status_code == 200
    spu.refresh_from_db()
    assert spu.lifecycle_status == ProductSPU.LifecycleStatus.ACTIVE
    assert spu.sales_status == ProductSPU.SalesStatus.ON_SALE

    invalid = client.post(
        f"/api/internal/products/spus/{spu.id}/status/",
        {"sales_status": "invalid"},
        format="json",
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "VALIDATION_ERROR"

    response = client.post(
        f"/api/internal/products/skus/{sku.id}/status/",
        {"is_active": False, "reason": "manual off shelf"},
        format="json",
    )
    assert response.status_code == 200
    sku.refresh_from_db()
    assert sku.is_active is False

    invalid = client.post(
        f"/api/internal/products/skus/{sku.id}/status/",
        {"is_active": "maybe"},
        format="json",
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "VALIDATION_ERROR"

    assert client.post(
        f"/api/internal/products/spus/{foreign_spu.id}/status/",
        {"sales_status": "on_sale"},
        format="json",
    ).status_code == 404
    assert client.post(
        f"/api/internal/products/skus/{foreign_sku.id}/status/",
        {"is_active": False},
        format="json",
    ).status_code == 404


@pytest.mark.django_db
def test_custom_scope_allows_actions_for_declared_rows_and_hides_other_rows():
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-custom")
    allowed_spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-CUSTOM-A", product_name="Allowed")
    allowed_sku = ProductSKU.objects.create(tenant=tenant, spu=allowed_spu, sku_code="SKU-CUSTOM-A")
    blocked_spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-CUSTOM-B", product_name="Blocked")
    blocked_sku = ProductSKU.objects.create(tenant=tenant, spu=blocked_spu, sku_code="SKU-CUSTOM-B")
    allowed_legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-CUSTOM-A",
        product_name="Allowed legacy",
        status=ProductLegacyItem.Status.PENDING,
    )
    blocked_legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-CUSTOM-B",
        product_name="Blocked legacy",
        status=ProductLegacyItem.Status.PENDING,
    )
    _user, client = _client_user(
        tenant,
        "product-action-custom-user",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={
            "spu_ids": [allowed_spu.id],
            "sku_ids": [allowed_sku.id],
            "legacy_item_ids": [allowed_legacy.id],
        },
    )

    assert client.post(
        f"/api/internal/products/spus/{allowed_spu.id}/status/",
        {"sales_status": "on_sale"},
        format="json",
    ).status_code == 200
    assert client.post(
        f"/api/internal/products/spus/{blocked_spu.id}/status/",
        {"sales_status": "on_sale"},
        format="json",
    ).status_code == 404
    assert client.post(
        f"/api/internal/products/skus/{allowed_sku.id}/status/",
        {"is_active": False},
        format="json",
    ).status_code == 200
    assert client.post(
        f"/api/internal/products/skus/{blocked_sku.id}/status/",
        {"is_active": False},
        format="json",
    ).status_code == 404

    assert client.delete(f"/api/internal/products/skus/{allowed_sku.id}/").status_code == 200
    assert client.delete(f"/api/internal/products/skus/{blocked_sku.id}/").status_code == 404
    assert client.delete(f"/api/internal/products/spus/{allowed_spu.id}/").status_code == 200
    assert client.delete(f"/api/internal/products/spus/{blocked_spu.id}/").status_code == 404
    assert client.delete(f"/api/internal/products/legacy-items/{allowed_legacy.id}/").status_code == 200
    assert client.delete(f"/api/internal/products/legacy-items/{blocked_legacy.id}/").status_code == 404


@pytest.mark.django_db
def test_generated_legacy_detail_delete_is_protected_and_pending_detail_delete_works():
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-legacy")
    _user, client = _client_user(tenant, "product-action-legacy-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-LEGACY", product_name="Legacy")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-LEGACY")
    generated = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-GENERATED",
        product_name="Generated",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
        generated_sku=sku,
    )
    response = client.delete(f"/api/internal/products/legacy-items/{generated.id}/")
    assert response.status_code == 409
    assert response.json()["data"]["can_deactivate"] is True
    assert ProductLegacyItem.objects.filter(pk=generated.pk).exists()


@pytest.mark.django_db
def test_generated_legacy_with_only_spu_reference_cannot_offer_sku_deactivation():
    tenant = Tenant.objects.create(name="Product action tenant", code="product-action-legacy-spu-only")
    _user, client = _client_user(tenant, "product-action-legacy-spu-only-user")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-LEGACY-SPU", product_name="Legacy")
    legacy = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-GENERATED-SPU",
        product_name="Generated without SKU",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
    )

    response = client.delete(f"/api/internal/products/legacy-items/{legacy.id}/")

    assert response.status_code == 409
    assert response.json()["data"]["can_deactivate"] is False
    assert response.json()["data"]["sku_id"] is None
