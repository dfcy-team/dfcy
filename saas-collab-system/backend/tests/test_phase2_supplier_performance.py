from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.suppliers.models import SupplierPerformanceSnapshot, SupplierShipment, SupplierTask
from apps.suppliers.performance_services import calculate_supplier_performance
from apps.tenants.models import Tenant


TODAY = date.today()


def create_user(tenant, username, user_type, supplier_id=None):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)
    if user_type == CustomUser.UserType.EXTERNAL:
        ExternalUserProfile.objects.create(user=user, tenant=tenant, supplier_id=supplier_id)
    return user


def grant_performance_access(user, scope_type=DataScope.ScopeType.ALL, config=None):
    permission, _ = Permission.objects.get_or_create(
        code="suppliers.performance.view",
        defaults={"name": "View supplier performance", "module": "suppliers", "action": "view"},
    )
    role = Role.objects.create(tenant=user.tenant, name="Supplier performance", code="supplier-performance")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=scope_type,
        config=config or {},
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_snapshot(tenant, supplier_id, period_start=TODAY, period_end=TODAY):
    return SupplierPerformanceSnapshot.objects.create(
        tenant=tenant,
        supplier_id=supplier_id,
        period_start=period_start,
        period_end=period_end,
    )


@pytest.mark.django_db
def test_performance_calculation_is_correct_and_idempotent():
    tenant = Tenant.objects.create(name="Tenant", code="performance-calc")
    SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=1001,
        task_no="TASK-ON-TIME",
        sku_code="SKU-1",
        production_quantity=10,
        completed_quantity=10,
        status=SupplierTask.Status.COMPLETED,
        feedback_note="demo feedback",
    )
    SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=1001,
        task_no="TASK-OVERDUE",
        sku_code="SKU-2",
        production_quantity=10,
        status=SupplierTask.Status.IN_PROGRESS,
        is_overdue=True,
    )
    SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=1001,
        task_no="TASK-EXCEPTION",
        sku_code="SKU-3",
        production_quantity=10,
        status=SupplierTask.Status.EXCEPTION,
        feedback_note="demo exception feedback",
        exception_note="demo quality exception",
    )
    SupplierShipment.objects.create(
        tenant=tenant,
        supplier_id=1001,
        shipment_no="SHIP-ACCURATE",
        sku_code="SKU-1",
        ship_quantity=10,
        carton_count=1,
        weight="5.000",
        volume="1.000",
    )
    SupplierShipment.objects.create(
        tenant=tenant,
        supplier_id=1001,
        shipment_no="SHIP-INCOMPLETE",
        sku_code="SKU-2",
        ship_quantity=10,
        carton_count=1,
    )

    first = calculate_supplier_performance(
        tenant=tenant,
        supplier_id=1001,
        period_start=TODAY,
        period_end=TODAY,
    )
    second = calculate_supplier_performance(
        tenant=tenant,
        supplier_id=1001,
        period_start=TODAY,
        period_end=TODAY,
    )

    assert second.id == first.id
    assert SupplierPerformanceSnapshot.objects.count() == 1
    assert second.total_tasks == 3
    assert second.on_time_tasks == 1
    assert second.overdue_tasks == 1
    assert second.exception_tasks == 1
    assert second.total_shipments == 2
    assert second.accurate_shipments == 1
    assert second.feedback_on_time_count == 2
    assert second.on_time_rate == Decimal("33.33")
    assert second.shipment_accuracy_rate == Decimal("50.00")
    assert second.total_score == Decimal("51.67")


@pytest.mark.django_db
def test_empty_data_calculation_returns_zero_metrics():
    tenant = Tenant.objects.create(name="Tenant", code="performance-empty")

    snapshot = calculate_supplier_performance(
        tenant=tenant,
        supplier_id=1001,
        period_start=TODAY,
        period_end=TODAY,
    )

    assert snapshot.total_tasks == 0
    assert snapshot.total_shipments == 0
    assert snapshot.total_score == Decimal("0.00")


@pytest.mark.django_db
def test_internal_performance_access_requires_permission_and_is_tenant_isolated():
    tenant_a = Tenant.objects.create(name="Tenant A", code="performance-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="performance-b")
    authorized = create_user(tenant_a, "performance-authorized", CustomUser.UserType.INTERNAL)
    unauthorized = create_user(tenant_a, "performance-unauthorized", CustomUser.UserType.INTERNAL)
    grant_performance_access(authorized)
    own = create_snapshot(tenant_a, 1001)
    create_snapshot(tenant_b, 2002)

    response = client_for(authorized).get("/api/internal/suppliers/performance/")
    denied = client_for(unauthorized).get("/api/internal/suppliers/performance/")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == [own.id]
    assert denied.status_code == 403


@pytest.mark.django_db
def test_internal_performance_custom_data_scope_limits_suppliers():
    tenant = Tenant.objects.create(name="Tenant", code="performance-scope")
    user = create_user(tenant, "performance-scoped", CustomUser.UserType.INTERNAL)
    grant_performance_access(
        user,
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supplier_ids": [1001]},
    )
    own = create_snapshot(tenant, 1001)
    create_snapshot(tenant, 2002)
    client = client_for(user)

    collection = client.get("/api/internal/suppliers/performance/")
    denied_detail = client.get("/api/internal/suppliers/performance/2002/")

    assert [item["id"] for item in collection.json()["data"]] == [own.id]
    assert denied_detail.status_code == 403


@pytest.mark.django_db
def test_internal_can_calculate_mock_and_view_supplier_history():
    tenant = Tenant.objects.create(name="Tenant", code="performance-internal")
    user = create_user(tenant, "performance-internal", CustomUser.UserType.INTERNAL)
    grant_performance_access(user)
    client = client_for(user)

    calculate_response = client.post(
        "/api/internal/suppliers/performance/calculate-mock/",
        {"supplier_id": 1001, "period_start": TODAY.isoformat(), "period_end": TODAY.isoformat()},
        format="json",
    )
    detail_response = client.get("/api/internal/suppliers/performance/1001/")

    assert calculate_response.status_code == 200
    assert calculate_response.json()["success"] is True
    assert calculate_response.json()["code"] == "OK"
    assert detail_response.status_code == 200
    assert len(detail_response.json()["data"]) == 1


@pytest.mark.django_db
def test_supplier_can_only_view_own_performance():
    tenant = Tenant.objects.create(name="Tenant", code="performance-external")
    supplier = create_user(tenant, "supplier-performance", CustomUser.UserType.EXTERNAL, supplier_id=1001)
    own = create_snapshot(tenant, 1001)
    create_snapshot(tenant, 2002)
    client = client_for(supplier)

    current = client.get("/api/external/supplier/performance/")
    history = client.get("/api/external/supplier/performance/history/")
    impersonation = client.get("/api/external/supplier/performance/?supplier_id=2002")

    assert current.status_code == 200
    assert current.json()["data"]["id"] == own.id
    assert [item["id"] for item in history.json()["data"]] == [own.id]
    assert impersonation.status_code == 403


@pytest.mark.django_db
def test_rpa_cannot_access_internal_or_external_performance_api():
    tenant = Tenant.objects.create(name="Tenant", code="performance-rpa")
    rpa_user = create_user(tenant, "performance-rpa", CustomUser.UserType.RPA)
    client = client_for(rpa_user)

    internal_response = client.get("/api/internal/suppliers/performance/")
    external_response = client.get("/api/external/supplier/performance/")

    assert internal_response.status_code == 403
    assert external_response.status_code == 403


@pytest.mark.django_db
def test_performance_response_does_not_expose_finance_fields():
    tenant = Tenant.objects.create(name="Tenant", code="performance-safe-response")
    supplier = create_user(tenant, "supplier-safe-response", CustomUser.UserType.EXTERNAL, supplier_id=1001)
    create_snapshot(tenant, 1001)

    response = client_for(supplier).get("/api/external/supplier/performance/")
    payload = response.json()["data"]

    assert response.status_code == 200
    assert not {"unit_price", "payment_terms", "gross_amount", "net_amount", "bank_account"}.intersection(payload)
