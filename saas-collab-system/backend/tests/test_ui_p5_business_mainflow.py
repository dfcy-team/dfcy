import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductResearch, ProductSPU
from apps.purchasing.models import PurchaseOrder
from apps.suppliers.models import SupplierTask
from apps.tenants.models import Tenant


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def internal_user(tenant, username):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def grant(user, codes, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, code=f"{user.username}-role", name="UI P5 role")
    role.permissions.add(*Permission.objects.filter(code__in=codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


@pytest.mark.django_db
def test_product_routes_require_declared_permission_and_scope():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p5-product-permission")
    user = internal_user(tenant, "product-no-role")
    response = client_for(user).get("/api/internal/products/research/")

    assert response.status_code == 403
    assert response.json()["success"] is False
    assert response.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_product_research_custom_scope_and_pagination_are_enforced():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p5-product-scope")
    creator = internal_user(tenant, "creator")
    viewer = internal_user(tenant, "viewer")
    visible = ProductResearch.objects.create(tenant=tenant, research_no="VISIBLE", product_name="Visible", created_by=creator)
    ProductResearch.objects.create(tenant=tenant, research_no="HIDDEN", product_name="Hidden", created_by=creator)
    grant(viewer, ["products.research.view"], DataScope.ScopeType.CUSTOM, {"research_ids": [visible.id]})

    response = client_for(viewer).get("/api/internal/products/research/?page=1&page_size=1")

    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1
    assert [item["research_no"] for item in response.json()["data"]["results"]] == ["VISIBLE"]


@pytest.mark.django_db
def test_product_freeze_requires_action_permission_and_is_idempotent():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p5-freeze")
    viewer = internal_user(tenant, "freeze-viewer")
    freezer = internal_user(tenant, "freezer")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-P5", product_name="Product")
    grant(viewer, ["products.master.view"])
    grant(freezer, ["products.master.freeze"], DataScope.ScopeType.CUSTOM, {"spu_ids": [spu.id]})

    denied = client_for(viewer).post(f"/api/internal/products/spus/{spu.id}/freeze-code/", {}, format="json")
    first = client_for(freezer).post(f"/api/internal/products/spus/{spu.id}/freeze-code/", {}, format="json")
    second = client_for(freezer).post(f"/api/internal/products/spus/{spu.id}/freeze-code/", {}, format="json")

    assert denied.status_code == 403
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["is_code_frozen"] is True


@pytest.mark.django_db
def test_product_generic_patch_rejects_workflow_controlled_status_fields():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p5-product-controlled-fields")
    manager = internal_user(tenant, "product-manager")
    research = ProductResearch.objects.create(
        tenant=tenant,
        research_no="RESEARCH-CONTROLLED",
        product_name="Controlled research",
        created_by=manager,
    )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-CONTROLLED", product_name="Controlled SPU")
    grant(manager, ["products.research.manage", "products.master.manage"])
    client = client_for(manager)

    created_research_response = client.post(
        "/api/internal/products/research/",
        {
            "research_no": "RESEARCH-CREATE-CONTROLLED",
            "product_name": "Controlled create research",
            "approval_status": ProductResearch.ApprovalStatus.APPROVED,
        },
        format="json",
    )
    created_spu_response = client.post(
        "/api/internal/products/spus/",
        {
            "spu_code": "SPU-CREATE-CONTROLLED",
            "product_name": "Controlled create SPU",
            "lifecycle_status": ProductSPU.LifecycleStatus.DISCONTINUED,
            "sales_status": ProductSPU.SalesStatus.STOPPED,
        },
        format="json",
    )
    research_response = client.patch(
        f"/api/internal/products/research/{research.id}/",
        {"approval_status": ProductResearch.ApprovalStatus.APPROVED},
        format="json",
    )
    spu_response = client.patch(
        f"/api/internal/products/spus/{spu.id}/",
        {
            "lifecycle_status": ProductSPU.LifecycleStatus.DISCONTINUED,
            "sales_status": ProductSPU.SalesStatus.STOPPED,
        },
        format="json",
    )

    research.refresh_from_db()
    spu.refresh_from_db()
    assert created_research_response.status_code == 201
    assert created_research_response.json()["data"]["approval_status"] == ProductResearch.ApprovalStatus.DRAFT
    assert created_spu_response.status_code == 201
    assert created_spu_response.json()["data"]["lifecycle_status"] == ProductSPU.LifecycleStatus.DRAFT
    assert created_spu_response.json()["data"]["sales_status"] == ProductSPU.SalesStatus.NOT_LISTED
    assert research_response.status_code == 400
    assert research_response.json()["code"] == "VALIDATION_ERROR"
    assert research.approval_status == ProductResearch.ApprovalStatus.DRAFT
    assert spu_response.status_code == 400
    assert spu_response.json()["code"] == "VALIDATION_ERROR"
    assert spu.lifecycle_status == ProductSPU.LifecycleStatus.DRAFT
    assert spu.sales_status == ProductSPU.SalesStatus.NOT_LISTED


@pytest.mark.django_db
def test_ui_p5_pagination_allows_page_numbers_above_100_and_caps_page_size():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p5-pagination-page-number")
    creator = internal_user(tenant, "pagination-creator")
    viewer = internal_user(tenant, "pagination-viewer")
    ProductResearch.objects.bulk_create(
        [
            ProductResearch(
                tenant=tenant,
                research_no=f"PAGE-{index:03d}",
                product_name=f"Page item {index}",
                created_by=creator,
            )
            for index in range(1, 102)
        ]
    )
    grant(viewer, ["products.research.view"])
    client = client_for(viewer)

    page_response = client.get("/api/internal/products/research/?page=101&page_size=1")
    oversized_response = client.get("/api/internal/products/research/?page=1&page_size=101")

    assert page_response.status_code == 200
    assert page_response.json()["data"]["count"] == 101
    assert len(page_response.json()["data"]["results"]) == 1
    assert oversized_response.status_code == 400
    assert oversized_response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_purchase_order_scope_filters_supplier_and_blocks_unscoped_write():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p5-purchase-scope")
    creator = internal_user(tenant, "po-creator")
    viewer = internal_user(tenant, "po-viewer")
    PurchaseOrder.objects.create(tenant=tenant, po_no="PO-1001", sku_code="SKU-A", supplier_id=1001, quantity=1, unit_price="1.00", created_by=creator)
    PurchaseOrder.objects.create(tenant=tenant, po_no="PO-2002", sku_code="SKU-B", supplier_id=2002, quantity=1, unit_price="1.00", created_by=creator)
    grant(viewer, ["purchasing.orders.view", "purchasing.orders.manage"], DataScope.ScopeType.CUSTOM, {"supplier_ids": [1001]})

    listing = client_for(viewer).get("/api/internal/purchasing/orders/")
    create = client_for(viewer).post("/api/internal/purchasing/orders/", {}, format="json")

    assert [item["po_no"] for item in listing.json()["data"]["results"]] == ["PO-1001"]
    assert create.status_code == 403


@pytest.mark.django_db
def test_external_supplier_cannot_override_supplier_identity_and_gets_pagination():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p5-supplier")
    supplier = CustomUser.objects.create_user(username="supplier", tenant=tenant, user_type=CustomUser.UserType.EXTERNAL)
    ExternalUserProfile.objects.create(user=supplier, tenant=tenant, supplier_id=1001, company_name="Demo supplier")
    SupplierTask.objects.create(tenant=tenant, supplier_id=1001, task_no="OWN", sku_code="SKU", production_quantity=1)
    SupplierTask.objects.create(tenant=tenant, supplier_id=2002, task_no="OTHER", sku_code="SKU", production_quantity=1)

    client = client_for(supplier)
    own = client.get("/api/external/supplier/tasks/?page=1&page_size=20")
    override = client.get("/api/external/supplier/tasks/?supplier_id=2002")

    assert own.status_code == 200
    assert own.json()["data"]["count"] == 1
    assert own.json()["data"]["results"][0]["task_no"] == "OWN"
    assert override.status_code == 403
