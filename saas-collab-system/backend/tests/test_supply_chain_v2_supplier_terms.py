from datetime import date
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import CustomUser
from apps.masterdata.models import SupplierMaster
from apps.masterdata.serializers import SupplierMasterSerializer
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.supply_chain.archives import save_supplier, supplier_data
from apps.supply_chain.models import BusinessEvent
from apps.supply_chain.serializers import SupplierInput
from apps.tenants.models import Tenant


@pytest.fixture
def supplier_world(db):
    tenant = Tenant.objects.create(name="Terms tenant", code="terms-tenant")
    user = CustomUser.objects.create_user(username="terms-owner", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code="terms-role", name="Terms manager")
    for code in ("supply.v2.view", "supply.v2.manage"):
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": code, "module": "supply", "action": "manage", "description": "test"},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL)
    return SimpleNamespace(tenant=tenant, user=user)


def test_supplier_terms_validate_nullable_zero_and_choices(supplier_world):
    valid = SupplierInput(data={
        "code": "terms-supplier", "name": "Terms supplier", "first_cooperation_date": "2026-10-01",
        "payment_term_days": 0, "payment_term_start": "shipment_date",
    })
    assert valid.is_valid(), valid.errors
    assert valid.validated_data["payment_term_days"] == 0
    assert valid.validated_data["first_cooperation_date"] == date(2026, 10, 1)

    for bad in ({"payment_term_days": -1}, {"payment_term_days": 3651}, {"payment_term_days": "1.5"},
                {"payment_term_start": "invoice_date"}, {"first_cooperation_date": "not-a-date"}):
        serializer = SupplierInput(data={"code": "s", "name": "Supplier", **bad})
        assert not serializer.is_valid(), bad

    nullable = SupplierInput(data={
        "code": "terms-supplier", "name": "Terms supplier", "first_cooperation_date": None,
        "payment_term_days": None, "payment_term_start": "unspecified",
    })
    assert nullable.is_valid(), nullable.errors
    assert nullable.validated_data["payment_term_days"] is None


def test_both_supplier_archive_paths_preserve_omitted_terms_and_audit_iso_date(supplier_world):
    supplier = SupplierMaster.objects.create(tenant=supplier_world.tenant, code="terms-supplier", name="Terms supplier")
    request = SimpleNamespace(user=supplier_world.user)
    basic = SupplierMasterSerializer(
        supplier,
        data={"first_cooperation_date": "2026-10-01", "payment_term_days": "0", "payment_term_start": "shipment_date"},
        partial=True,
        context={"request": request},
    )
    assert basic.is_valid(), basic.errors
    basic.save()
    supplier.refresh_from_db()
    assert supplier.first_cooperation_date == date(2026, 10, 1)
    assert supplier.payment_term_days == 0
    assert supplier.supply_version == 2

    old_client = SupplierInput(data={"code": supplier.code, "name": "Updated name", "expected_version": supplier.supply_version})
    assert old_client.is_valid(), old_client.errors
    supplier = save_supplier(supplier_world.user, old_client.validated_data, pk=supplier.pk, idempotency_key="old-client-update")
    response = supplier_data(supplier)
    assert response["first_cooperation_date"] == "2026-10-01"
    assert response["payment_term_days"] == 0
    assert response["payment_term_start"] == "shipment_date"
    event = BusinessEvent.objects.get(aggregate_type="suppliermaster", aggregate_id=supplier.pk, action="archive_saved")
    assert event.payload["after"]["first_cooperation_date"] == "2026-10-01"
    assert event.aggregate_version == supplier.supply_version


def test_supplier_term_service_rejects_external_and_cross_tenant_updates(supplier_world):
    supplier = SupplierMaster.objects.create(tenant=supplier_world.tenant, code="terms-supplier", name="Terms supplier")
    external = CustomUser.objects.create_user(username="terms-external", tenant=supplier_world.tenant, user_type=CustomUser.UserType.EXTERNAL)
    with pytest.raises(PermissionDenied):
        save_supplier(external, {"code": supplier.code, "name": supplier.name}, pk=supplier.pk, idempotency_key="external")

    other_tenant = Tenant.objects.create(name="Other terms tenant", code="other-terms-tenant")
    other_user = CustomUser.objects.create_user(username="other-terms", tenant=other_tenant, user_type=CustomUser.UserType.INTERNAL)
    other_role = Role.objects.create(tenant=other_tenant, code="other-terms-role", name="Other manager")
    for code in ("supply.v2.view", "supply.v2.manage"):
        permission = Permission.objects.get(code=code)
        other_role.permissions.add(permission)
    UserRole.objects.create(tenant=other_tenant, user=other_user, role=other_role)
    DataScope.objects.create(tenant=other_tenant, role=other_role, scope_type=DataScope.ScopeType.ALL)
    with pytest.raises(NotFound):
        save_supplier(other_user, {"code": supplier.code, "name": supplier.name}, pk=supplier.pk, idempotency_key="cross-tenant")
