import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.audit.models import OperationLog
from apps.masterdata.models import StatusChoices, SupplierMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import (
    SupplyProductionProgress,
    SupplyPurchaseOrder,
    SupplyPurchaseOrderEvent,
    SupplyPurchaseOrderLine,
)
from apps.tenants.models import Tenant


SUPPLY_PERMISSION_CODES = (
    "supply.purchase_order.view",
    "supply.purchase_order.create",
    "supply.purchase_order.accept",
    "supply.production.start",
    "supply.production.update",
    "supply.production.complete",
)


def ensure_supply_permissions():
    permissions = []
    for code in SUPPLY_PERMISSION_CODES:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": code,
                "module": "supply",
                "action": code.rsplit(".", 1)[-1],
                "description": "SC-F1 test permission.",
            },
        )
        permissions.append(permission)
    return permissions


def create_internal_user(tenant, username="supply-internal", scope_type=DataScope.ScopeType.ALL, config=None):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(
        tenant=tenant,
        code=f"{username}-role",
        name="Supply role",
    )
    role.permissions.add(*ensure_supply_permissions())
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=scope_type,
        config=config or {},
    )
    return user


def create_supplier_user(tenant, supplier, username):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.EXTERNAL,
    )
    ExternalUserProfile.objects.create(
        user=user,
        tenant=tenant,
        supplier_id=supplier.id,
        company_name=supplier.name,
    )
    return user


def create_catalog(tenant, suffix="A"):
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code=f"supplier-{suffix.lower()}",
        name=f"Supplier {suffix}",
    )
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"SPU-{suffix}",
        product_name=f"Product {suffix}",
    )
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code=f"SKU-{suffix}",
    )
    return supplier, sku


def internal_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def supplier_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def miniapp_client(user):
    refresh = RefreshToken.for_user(user)
    refresh["channel"] = "miniapp"
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def create_order(client, supplier, sku, order_no="SC-PO-001"):
    return client.post(
        "/api/internal/purchasing/supply-orders/",
        data={
            "order_no": order_no,
            "supplier_id": supplier.id,
            "order_date": "2026-07-25",
            "expected_delivery_date": "2026-08-25",
            "currency": "cny",
            "notes": "Local SC-F1 test only",
            "source_system": "supabase-legacy",
            "source_table": "purchase_orders",
            "source_record_id": f"source-{order_no}",
            "source_payload_hash": "a" * 64,
            "lines": [
                {
                    "line_no": 1,
                    "sku_id": sku.id,
                    "quantity": 100,
                    "unit_price": "12.5000",
                    "expected_delivery_date": "2026-08-25",
                    "source_record_id": f"source-{order_no}-line-1",
                }
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"create-{order_no}",
    )


@pytest.mark.django_db
def test_internal_user_creates_header_lines_without_changing_legacy_model():
    tenant = Tenant.objects.create(name="SC-F1 Tenant", code="sc-f1")
    user = create_internal_user(tenant)
    supplier, sku = create_catalog(tenant)

    response = create_order(internal_client(user), supplier, sku)

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["order_no"] == "SC-PO-001"
    assert data["supplier_id"] == supplier.id
    assert data["status"] == SupplyPurchaseOrder.Status.PENDING
    assert data["total_quantity"] == 100
    assert data["currency"] == "CNY"
    assert data["lines"][0]["sku_id"] == sku.id
    assert data["lines"][0]["sku_code_snapshot"] == sku.sku_code
    assert OperationLog.objects.filter(
        tenant=tenant,
        module="supply_chain",
        action="purchase_order.create",
    ).count() == 1


@pytest.mark.django_db
def test_create_rejects_cross_tenant_supplier_and_sku():
    tenant_a = Tenant.objects.create(name="Tenant A", code="sc-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="sc-b")
    user = create_internal_user(tenant_a)
    supplier_b, sku_b = create_catalog(tenant_b, "B")

    response = create_order(internal_client(user), supplier_b, sku_b)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert SupplyPurchaseOrder.objects.count() == 0


@pytest.mark.django_db
def test_create_rejects_inactive_supplier():
    tenant = Tenant.objects.create(name="Inactive Supplier Create", code="inactive-supplier-create")
    user = create_internal_user(tenant)
    supplier, sku = create_catalog(tenant, "INACTIVE-CREATE")
    supplier.status = StatusChoices.INACTIVE
    supplier.save(update_fields=["status"])

    response = create_order(internal_client(user), supplier, sku, "SC-INACTIVE-CREATE")

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert SupplyPurchaseOrder.objects.filter(tenant=tenant).count() == 0


@pytest.mark.django_db
def test_create_is_idempotent_and_rejects_key_reuse_with_different_payload():
    tenant = Tenant.objects.create(name="Create Idempotency", code="create-idempotency")
    user = create_internal_user(tenant)
    supplier, sku = create_catalog(tenant)
    client = internal_client(user)

    first = create_order(client, supplier, sku, "SC-IDEMPOTENT")
    replay = create_order(client, supplier, sku, "SC-IDEMPOTENT")
    conflict = client.post(
        "/api/internal/purchasing/supply-orders/",
        data={
            "order_no": "SC-DIFFERENT",
            "supplier_id": supplier.id,
            "order_date": "2026-07-25",
            "lines": [
                {
                    "line_no": 1,
                    "sku_id": sku.id,
                    "quantity": 1,
                    "unit_price": "1.0000",
                }
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="create-SC-IDEMPOTENT",
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["data"]["id"] == first.json()["data"]["id"]
    assert conflict.status_code == 409
    assert SupplyPurchaseOrder.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
def test_supplier_only_sees_own_orders_and_financial_fields_are_not_exposed():
    tenant = Tenant.objects.create(name="Supplier Scope", code="supplier-scope")
    internal = create_internal_user(tenant)
    supplier_a, sku_a = create_catalog(tenant, "A")
    supplier_b, sku_b = create_catalog(tenant, "B")
    client = internal_client(internal)
    own = create_order(client, supplier_a, sku_a, "SC-OWN").json()["data"]
    hidden = create_order(client, supplier_b, sku_b, "SC-HIDDEN").json()["data"]
    supplier_user = create_supplier_user(tenant, supplier_a, "supplier-a")

    list_response = supplier_client(supplier_user).get("/api/external/supplier/purchase-orders/")
    hidden_response = supplier_client(supplier_user).get(
        f"/api/external/supplier/purchase-orders/{hidden['id']}/"
    )

    assert list_response.status_code == 200
    results = list_response.json()["data"]["results"]
    assert [item["id"] for item in results] == [own["id"]]
    serialized = str(results)
    assert "unit_price" not in serialized
    assert "source_payload_hash" not in serialized
    assert "request_id" not in serialized
    assert "actor_id" not in serialized
    assert hidden_response.status_code == 404


@pytest.mark.django_db
def test_inactive_supplier_is_denied_on_web_and_miniapp_channels():
    tenant = Tenant.objects.create(name="Inactive Supplier Access", code="inactive-supplier-access")
    internal = create_internal_user(tenant)
    supplier, sku = create_catalog(tenant, "INACTIVE-ACCESS")
    order_id = create_order(
        internal_client(internal),
        supplier,
        sku,
        "SC-INACTIVE-ACCESS",
    ).json()["data"]["id"]
    supplier_user = create_supplier_user(tenant, supplier, "inactive-supplier")
    supplier.status = StatusChoices.INACTIVE
    supplier.save(update_fields=["status"])

    web = supplier_client(supplier_user)
    miniapp = miniapp_client(supplier_user)
    responses = [
        web.get("/api/external/supplier/purchase-orders/"),
        web.get(f"/api/external/supplier/purchase-orders/{order_id}/"),
        web.post(
            f"/api/external/supplier/purchase-orders/{order_id}/actions/accept/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="inactive-web-accept",
        ),
        miniapp.get("/api/miniapp/supply-chain/orders/"),
        miniapp.get(f"/api/miniapp/supply-chain/orders/{order_id}/"),
        miniapp.post(
            f"/api/miniapp/supply-chain/orders/{order_id}/actions/accept/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="inactive-miniapp-accept",
        ),
    ]

    assert [response.status_code for response in responses] == [403] * len(responses)
    order = SupplyPurchaseOrder.objects.get(pk=order_id)
    assert order.status == SupplyPurchaseOrder.Status.PENDING
    assert order.events.count() == 0


@pytest.mark.django_db
def test_supplier_profile_tenant_mismatch_is_denied():
    tenant = Tenant.objects.create(name="Supplier Profile Tenant", code="supplier-profile-tenant")
    other_tenant = Tenant.objects.create(name="Other Profile Tenant", code="other-profile-tenant")
    supplier, _ = create_catalog(tenant, "PROFILE-TENANT")
    supplier_user = create_supplier_user(tenant, supplier, "mismatched-profile-supplier")
    profile = supplier_user.external_profile
    profile.tenant = other_tenant
    profile.save(update_fields=["tenant"])

    web_response = supplier_client(supplier_user).get("/api/external/supplier/purchase-orders/")
    miniapp_response = miniapp_client(supplier_user).get("/api/miniapp/supply-chain/orders/")

    assert web_response.status_code == 403
    assert miniapp_response.status_code == 403


@pytest.mark.django_db
def test_miniapp_supplier_completes_idempotent_sc_f1_state_machine():
    tenant = Tenant.objects.create(name="Miniapp Supply", code="miniapp-supply")
    internal = create_internal_user(tenant)
    supplier, sku = create_catalog(tenant)
    order_id = create_order(internal_client(internal), supplier, sku).json()["data"]["id"]
    supplier_user = create_supplier_user(tenant, supplier, "miniapp-supplier")
    client = miniapp_client(supplier_user)
    base = f"/api/miniapp/supply-chain/orders/{order_id}/actions"

    accepted = client.post(
        f"{base}/accept/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="accept-001",
    )
    started = client.post(
        f"{base}/start-production/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="start-001",
    )
    accepted_replay = client.post(
        f"{base}/accept/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="accept-001",
    )
    progress = client.post(
        f"{base}/update-progress/",
        {"completed_quantity": 40, "note": "Local progress"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="progress-040",
    )
    progress_key_conflict = client.post(
        f"{base}/update-progress/",
        {"completed_quantity": 41, "note": "Different payload"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="progress-040",
    )
    backwards = client.post(
        f"{base}/update-progress/",
        {"completed_quantity": 39},
        format="json",
        HTTP_IDEMPOTENCY_KEY="progress-backwards",
    )
    premature_complete = client.post(
        f"{base}/complete-production/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="complete-too-soon",
    )
    full_progress = client.post(
        f"{base}/update-progress/",
        {"completed_quantity": 100, "note": "Ready"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="progress-100",
    )
    completed = client.post(
        f"{base}/complete-production/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="complete-001",
    )

    assert accepted.status_code == 200
    assert accepted.json()["data"]["order"]["status"] == SupplyPurchaseOrder.Status.ACCEPTED
    assert accepted_replay.status_code == 200
    assert accepted_replay.json()["data"]["replayed"] is True
    assert accepted_replay.json()["data"]["order"] == accepted.json()["data"]["order"]
    assert started.json()["data"]["order"]["status"] == SupplyPurchaseOrder.Status.IN_PRODUCTION
    assert progress.json()["data"]["order"]["completed_quantity"] == 40
    assert progress_key_conflict.status_code == 409
    assert backwards.status_code == 409
    assert premature_complete.status_code == 409
    assert full_progress.status_code == 200
    assert completed.status_code == 200
    assert completed.json()["data"]["order"]["status"] == SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED
    assert SupplyPurchaseOrderEvent.objects.filter(order_id=order_id).count() == 5
    assert SupplyProductionProgress.objects.filter(order_id=order_id).count() == 2
    assert OperationLog.objects.filter(
        tenant=tenant,
        module="supply_chain",
        object_id=str(order_id),
    ).count() == 6


@pytest.mark.django_db
def test_miniapp_rejects_normal_channel_token_and_other_supplier():
    tenant = Tenant.objects.create(name="Miniapp Isolation", code="miniapp-isolation")
    internal = create_internal_user(tenant)
    supplier_a, sku = create_catalog(tenant, "A")
    supplier_b, _ = create_catalog(tenant, "B")
    order_id = create_order(internal_client(internal), supplier_a, sku).json()["data"]["id"]
    supplier_a_user = create_supplier_user(tenant, supplier_a, "supplier-a")
    supplier_b_user = create_supplier_user(tenant, supplier_b, "supplier-b")

    normal_token = str(RefreshToken.for_user(supplier_b_user).access_token)
    normal_client = APIClient()
    normal_client.credentials(HTTP_AUTHORIZATION=f"Bearer {normal_token}")
    channel_response = normal_client.get("/api/miniapp/supply-chain/orders/")
    other_supplier_response = miniapp_client(supplier_b_user).get(
        f"/api/miniapp/supply-chain/orders/{order_id}/"
    )
    internal_channel_response = miniapp_client(internal).get(
        "/api/internal/purchasing/supply-orders/"
    )
    external_channel_response = miniapp_client(supplier_b_user).get(
        "/api/external/supplier/purchase-orders/"
    )
    internal_accept = internal_client(internal).post(
        f"/api/internal/purchasing/supply-orders/{order_id}/actions/accept/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="cross-actor-action-key",
    )
    cross_actor_replay = miniapp_client(supplier_a_user).post(
        f"/api/miniapp/supply-chain/orders/{order_id}/actions/accept/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="cross-actor-action-key",
    )

    assert channel_response.status_code == 403
    assert other_supplier_response.status_code == 404
    assert internal_channel_response.status_code == 403
    assert external_channel_response.status_code == 403
    assert internal_accept.status_code == 200
    assert cross_actor_replay.status_code == 409


@pytest.mark.django_db
def test_internal_custom_scope_filters_supply_orders():
    tenant = Tenant.objects.create(name="Internal Scope", code="internal-scope")
    creator = create_internal_user(tenant, "creator")
    supplier_a, sku_a = create_catalog(tenant, "A")
    supplier_b, sku_b = create_catalog(tenant, "B")
    create_order(internal_client(creator), supplier_a, sku_a, "SC-A")
    create_order(internal_client(creator), supplier_b, sku_b, "SC-B")
    scoped = create_internal_user(
        tenant,
        "scoped",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supplier_ids": [supplier_a.id]},
    )

    response = internal_client(scoped).get("/api/internal/purchasing/supply-orders/")

    assert response.status_code == 200
    assert [item["order_no"] for item in response.json()["data"]["results"]] == ["SC-A"]


@pytest.mark.django_db
def test_direct_state_mutation_is_rejected():
    tenant = Tenant.objects.create(name="State Guard", code="state-guard")
    internal = create_internal_user(tenant)
    supplier, sku = create_catalog(tenant)
    order_id = create_order(internal_client(internal), supplier, sku).json()["data"]["id"]
    order = SupplyPurchaseOrder.objects.get(pk=order_id)

    order.status = SupplyPurchaseOrder.Status.ACCEPTED
    with pytest.raises(DjangoValidationError):
        order.save()
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrder.objects.filter(pk=order_id).update(
            status=SupplyPurchaseOrder.Status.ACCEPTED
        )

    accepted = internal_client(internal).post(
        f"/api/internal/purchasing/supply-orders/{order_id}/actions/accept/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="internal-accept-line-guard",
    )
    assert accepted.status_code == 200
    line = SupplyPurchaseOrder.objects.get(pk=order_id).lines.get()
    line.quantity = 101
    with pytest.raises(DjangoValidationError):
        line.save()
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.create(
            tenant=tenant,
            order=order,
            line_no=2,
            sku=sku,
            sku_code_snapshot=sku.sku_code,
            product_name_snapshot=sku.spu.product_name,
            quantity=1,
            unit_price="1.0000",
        )
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.filter(pk=line.pk).update(quantity=101)
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.filter(pk=line.pk).delete()
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.bulk_update([line], ["quantity"])
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderLine.objects.bulk_create([])

    event = SupplyPurchaseOrderEvent.objects.get(
        order_id=order_id,
        action=SupplyPurchaseOrderEvent.Action.ACCEPT,
    )
    event.payload = {"tampered": True}
    with pytest.raises(DjangoValidationError):
        event.save()
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderEvent.objects.filter(pk=event.pk).update(payload={"tampered": True})
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderEvent.objects.bulk_update([event], ["payload"])
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrderEvent.objects.bulk_create([])

    progress = SupplyProductionProgress.objects.create(
        tenant=tenant,
        order=order,
        completed_quantity=0,
        progress_percent="0.00",
        note="append-only guard",
        actor=internal,
        request_id="orm-guard-progress",
    )
    progress.note = "tampered"
    with pytest.raises(DjangoValidationError):
        progress.save()
    with pytest.raises(DjangoValidationError):
        SupplyProductionProgress.objects.filter(pk=progress.pk).update(note="tampered")
    with pytest.raises(DjangoValidationError):
        SupplyProductionProgress.objects.filter(pk=progress.pk).delete()
    with pytest.raises(DjangoValidationError):
        SupplyProductionProgress.objects.bulk_update([progress], ["note"])
    with pytest.raises(DjangoValidationError):
        SupplyProductionProgress.objects.bulk_create([])
    with pytest.raises(DjangoValidationError):
        SupplyPurchaseOrder.objects.filter(pk=order_id).delete()
