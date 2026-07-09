import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.purchasing.models import PurchaseOrder
from apps.suppliers.models import SupplierShipment, SupplierTask
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type, supplier_id=None):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=user_type,
    )
    if user_type == CustomUser.UserType.EXTERNAL:
        ExternalUserProfile.objects.create(
            user=user,
            tenant=tenant,
            supplier_id=supplier_id,
            company_name=f"Supplier {supplier_id}",
        )
    return user


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_internal_user_can_manage_purchase_orders_with_unified_response():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "internal-po", CustomUser.UserType.INTERNAL)
    client = authenticated_client(user)

    create_response = client.post(
        "/api/internal/purchasing/orders/",
        data={
            "po_no": "PO-001",
            "sku_code": "SKU-001",
            "supplier_id": 1001,
            "quantity": 50,
            "unit_price": "12.50",
            "delivery_date": "2026-08-01",
            "payment_terms": "Net 30 placeholder",
            "status": "draft",
            "approval_status": "draft",
        },
        format="json",
    )
    order_id = create_response.json()["data"]["id"]
    detail_response = client.get(f"/api/internal/purchasing/orders/{order_id}/")
    patch_response = client.patch(
        f"/api/internal/purchasing/orders/{order_id}/",
        data={"status": "confirmed"},
        format="json",
    )

    assert create_response.status_code == 201
    assert create_response.json()["success"] is True
    assert create_response.json()["code"] == "OK"
    assert create_response.json()["message"] == "success"
    assert create_response.json()["data"]["tenant_id"] == tenant.id
    assert create_response.json()["data"]["created_by_id"] == user.id
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["po_no"] == "PO-001"
    assert patch_response.status_code == 200
    assert patch_response.json()["data"]["status"] == "confirmed"


@pytest.mark.django_db
def test_external_user_cannot_access_internal_purchase_api():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "external-po-denied", CustomUser.UserType.EXTERNAL, supplier_id=1001)
    client = authenticated_client(user)

    list_response = client.get("/api/internal/purchasing/orders/")
    create_response = client.post("/api/internal/purchasing/orders/", data={}, format="json")

    assert list_response.status_code == 403
    assert create_response.status_code == 403


@pytest.mark.django_db
def test_supplier_can_only_see_own_tasks_and_shipments():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    supplier_user = create_user(tenant, "supplier-1001", CustomUser.UserType.EXTERNAL, supplier_id=1001)
    own_task = SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=1001,
        task_no="TASK-OWN",
        sku_code="SKU-OWN",
        production_quantity=100,
    )
    other_task = SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=2002,
        task_no="TASK-OTHER",
        sku_code="SKU-OTHER",
        production_quantity=200,
    )
    own_shipment = SupplierShipment.objects.create(
        tenant=tenant,
        supplier_id=1001,
        shipment_no="SHIP-OWN",
        sku_code="SKU-OWN",
        ship_quantity=20,
    )
    other_shipment = SupplierShipment.objects.create(
        tenant=tenant,
        supplier_id=2002,
        shipment_no="SHIP-OTHER",
        sku_code="SKU-OTHER",
        ship_quantity=30,
    )
    client = authenticated_client(supplier_user)

    tasks_response = client.get("/api/external/supplier/tasks/")
    own_task_response = client.get(f"/api/external/supplier/tasks/{own_task.id}/")
    other_task_response = client.get(f"/api/external/supplier/tasks/{other_task.id}/")
    shipments_response = client.get("/api/external/supplier/shipments/")
    own_shipment_response = client.get(f"/api/external/supplier/shipments/{own_shipment.id}/")
    other_shipment_response = client.get(f"/api/external/supplier/shipments/{other_shipment.id}/")

    assert tasks_response.status_code == 200
    assert [item["task_no"] for item in tasks_response.json()["data"]] == ["TASK-OWN"]
    assert own_task_response.status_code == 200
    assert other_task_response.status_code == 404
    assert shipments_response.status_code == 200
    assert [item["shipment_no"] for item in shipments_response.json()["data"]] == ["SHIP-OWN"]
    assert own_shipment_response.status_code == 200
    assert other_shipment_response.status_code == 404


@pytest.mark.django_db
def test_supplier_can_submit_feedback_and_shipment_without_finance_data():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    supplier_user = create_user(tenant, "supplier-feedback", CustomUser.UserType.EXTERNAL, supplier_id=1001)
    task = SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=1001,
        task_no="TASK-FEEDBACK",
        sku_code="SKU-FEEDBACK",
        production_quantity=100,
    )
    client = authenticated_client(supplier_user)

    feedback_response = client.patch(
        f"/api/external/supplier/tasks/{task.id}/feedback/",
        data={
            "completed_quantity": 40,
            "status": "in_progress",
            "feedback_note": "Production in progress",
            "exception_note": "",
        },
        format="json",
    )
    shipment_response = client.post(
        "/api/external/supplier/shipments/",
        data={
            "shipment_no": "SHIP-001",
            "sku_code": "SKU-FEEDBACK",
            "ship_quantity": 40,
            "carton_count": 4,
            "weight": "12.300",
            "volume": "0.800",
            "shipping_mark": "MARK-001",
            "tracking_no": "TRACK-001",
            "attachment_placeholder": "local-placeholder-only",
        },
        format="json",
    )

    assert feedback_response.status_code == 200
    assert feedback_response.json()["data"]["completed_quantity"] == 40
    assert shipment_response.status_code == 201
    data = shipment_response.json()["data"]
    assert data["supplier_id"] == 1001
    assert "unit_price" not in data
    assert "payment_terms" not in data


@pytest.mark.django_db
def test_supplier_feedback_rejects_unsafe_status_and_over_quantity():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    supplier_user = create_user(tenant, "supplier-invalid-feedback", CustomUser.UserType.EXTERNAL, supplier_id=1001)
    task = SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=1001,
        task_no="TASK-INVALID-FEEDBACK",
        sku_code="SKU-INVALID-FEEDBACK",
        production_quantity=100,
    )
    client = authenticated_client(supplier_user)

    unsafe_status_response = client.patch(
        f"/api/external/supplier/tasks/{task.id}/feedback/",
        data={"status": "cancelled"},
        format="json",
    )
    over_quantity_response = client.patch(
        f"/api/external/supplier/tasks/{task.id}/feedback/",
        data={"completed_quantity": 101, "status": "partial"},
        format="json",
    )

    assert unsafe_status_response.status_code == 400
    assert unsafe_status_response.json()["code"] == "VALIDATION_ERROR"
    assert over_quantity_response.status_code == 400
    assert over_quantity_response.json()["code"] == "VALIDATION_ERROR"
    task.refresh_from_db()
    assert task.status == SupplierTask.Status.PENDING
    assert task.completed_quantity == 0


@pytest.mark.django_db
def test_internal_user_cannot_use_external_supplier_api():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "internal-external-denied", CustomUser.UserType.INTERNAL)
    client = authenticated_client(user)

    response = client.get("/api/external/supplier/tasks/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_rpa_user_cannot_access_supplier_business_api():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa-supplier-denied", CustomUser.UserType.RPA)
    client = authenticated_client(user)

    task_response = client.get("/api/external/supplier/tasks/")
    shipment_response = client.post("/api/external/supplier/shipments/", data={}, format="json")

    assert task_response.status_code == 403
    assert shipment_response.status_code == 403


@pytest.mark.django_db
def test_purchase_and_supplier_apis_are_tenant_isolated():
    tenant_a = Tenant.objects.create(name="Tenant A", code="tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="tenant-b")
    internal_a = create_user(tenant_a, "internal-a", CustomUser.UserType.INTERNAL)
    internal_b = create_user(tenant_b, "internal-b", CustomUser.UserType.INTERNAL)
    supplier_a = create_user(tenant_a, "supplier-a", CustomUser.UserType.EXTERNAL, supplier_id=1001)
    PurchaseOrder.objects.create(
        tenant=tenant_a,
        po_no="PO-A",
        sku_code="SKU-A",
        supplier_id=1001,
        quantity=10,
        unit_price="10.00",
        created_by=internal_a,
    )
    hidden_po = PurchaseOrder.objects.create(
        tenant=tenant_b,
        po_no="PO-B",
        sku_code="SKU-B",
        supplier_id=1001,
        quantity=10,
        unit_price="10.00",
        created_by=internal_b,
    )
    hidden_task = SupplierTask.objects.create(
        tenant=tenant_b,
        supplier_id=1001,
        task_no="TASK-B",
        sku_code="SKU-B",
        production_quantity=10,
    )

    internal_client = authenticated_client(internal_a)
    supplier_client = authenticated_client(supplier_a)
    po_list_response = internal_client.get("/api/internal/purchasing/orders/")
    hidden_po_response = internal_client.get(f"/api/internal/purchasing/orders/{hidden_po.id}/")
    hidden_task_response = supplier_client.get(f"/api/external/supplier/tasks/{hidden_task.id}/")

    assert po_list_response.status_code == 200
    assert [item["po_no"] for item in po_list_response.json()["data"]] == ["PO-A"]
    assert hidden_po_response.status_code == 404
    assert hidden_task_response.status_code == 404
