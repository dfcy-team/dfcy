import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.audit.models import OperationLog
from apps.masterdata.models import SupplierMaster
from apps.packing.models import (
    PackingApiIdempotencyRecord,
    PackingBatch,
    PackingEvent,
)
from apps.packing.services import set_supplier_packing_capability
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderLine
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db

PACKING_PERMISSIONS = (
    "supply.packing.view",
    "supply.packing.create",
    "supply.packing.manage",
    "supply.packing.complete",
    "supply.packing.change.review",
)


def create_internal(
    tenant,
    username,
    *,
    permissions=PACKING_PERMISSIONS,
    scope_type=DataScope.ScopeType.ALL,
    config=None,
    with_scope=True,
):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name=f"{username} role")
    for code in permissions:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={
                "name": code,
                "module": "supply",
                "action": code.rsplit(".", 1)[-1],
                "description": "SC-F2 API test permission",
            },
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    if with_scope:
        DataScope.objects.create(
            tenant=tenant,
            role=role,
            scope_type=scope_type,
            config=config if config is not None else {},
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


def create_order(tenant, supplier, actor, suffix, quantity=10):
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"API-SPU-{suffix}",
        product_name=f"API product {suffix}",
    )
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code=f"API-SKU-{suffix}",
    )
    order = SupplyPurchaseOrder.objects.create(
        tenant=tenant,
        supplier=supplier,
        order_no=f"API-PO-{suffix}",
        order_date=timezone.localdate(),
        status=SupplyPurchaseOrder.Status.PENDING,
        created_by=actor,
    )
    line = SupplyPurchaseOrderLine.objects.create(
        tenant=tenant,
        order=order,
        line_no=1,
        sku=sku,
        sku_code_snapshot=sku.sku_code,
        product_name_snapshot=spu.product_name,
        quantity=quantity,
        unit_price="1.0000",
    )
    order.status = SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED
    order.completed_quantity = quantity
    order.production_completed_at = timezone.now()
    order._action_service_write = True
    order.save(
        update_fields=[
            "status",
            "completed_quantity",
            "production_completed_at",
            "updated_at",
        ]
    )
    return order, line


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


def create_batch(client, order, key="api-create"):
    return client.post(
        "/api/internal/packing/batches/",
        {"order_ids": [order.id], "note": "local API"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def add_box(client, batch_data, line, key="api-box"):
    return client.post(
        f"/api/internal/packing/batches/{batch_data['id']}/boxes/",
        {
            "expected_version": batch_data["version"],
            "weight": "2.500",
            "volume": "0.125000",
            "note": "",
            "items": [{"order_line_id": line.id, "quantity": line.quantity}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_internal_create_has_atomic_frozen_replay_and_strict_fields():
    tenant = Tenant.objects.create(name="F2 API create", code="f2-api-create")
    user = create_internal(tenant, "f2-api-create-user")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-API-S1", name="Supplier 1")
    order, _ = create_order(tenant, supplier, user, "CREATE")
    client = internal_client(user)

    first = create_batch(client, order, "create-frozen")
    replay = create_batch(client, order, "create-frozen")
    conflict = client.post(
        "/api/internal/packing/batches/",
        {"order_ids": [order.id], "note": "different"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="create-frozen",
    )
    unknown = client.post(
        "/api/internal/packing/batches/",
        {"order_ids": [order.id], "tenant_id": tenant.id},
        format="json",
        HTTP_IDEMPOTENCY_KEY="create-unknown",
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert first["Idempotency-Replayed"] == "false"
    assert replay["Idempotency-Replayed"] == "true"
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert unknown.status_code == 400
    assert PackingBatch.objects.filter(tenant=tenant).count() == 1
    assert PackingApiIdempotencyRecord.objects.filter(tenant=tenant).count() == 1


def test_permission_missing_scope_missing_and_invalid_scope_are_distinct():
    tenant = Tenant.objects.create(name="F2 API permission", code="f2-api-permission")
    no_permission = create_internal(tenant, "no-permission", permissions=(), with_scope=False)
    no_scope = create_internal(
        tenant,
        "no-scope",
        permissions=("supply.packing.view",),
        with_scope=False,
    )
    invalid = create_internal(
        tenant,
        "invalid-scope",
        permissions=("supply.packing.view",),
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supplier_ids": []},
    )

    responses = [
        internal_client(no_permission).get("/api/internal/packing/batches/"),
        internal_client(no_scope).get("/api/internal/packing/batches/"),
        internal_client(invalid).get("/api/internal/packing/batches/"),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert [response.json()["code"] for response in responses] == [
        "PERMISSION_DENIED",
        "DATA_SCOPE_MISSING",
        "DATA_SCOPE_INVALID",
    ]


def test_cancelled_batch_uses_all_historical_orders_for_custom_scope():
    tenant = Tenant.objects.create(name="F2 historical scope", code="f2-history-scope")
    creator = create_internal(tenant, "history-creator")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-HIST", name="History")
    order_a, _ = create_order(tenant, supplier, creator, "HIST-A")
    order_b, _ = create_order(tenant, supplier, creator, "HIST-B")
    batch = create_batch(internal_client(creator), order_a, "history-create").json()["data"]
    cancelled = internal_client(creator).post(
        f"/api/internal/packing/batches/{batch['id']}/actions/cancel/",
        {"expected_version": batch["version"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="history-cancel",
    )
    scoped_a = create_internal(
        tenant,
        "history-a",
        permissions=("supply.packing.view",),
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supply_purchase_order_ids": [order_a.id]},
    )
    scoped_b = create_internal(
        tenant,
        "history-b",
        permissions=("supply.packing.view",),
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"supply_purchase_order_ids": [order_b.id]},
    )

    visible = internal_client(scoped_a).get(f"/api/internal/packing/batches/{batch['id']}/")
    hidden = internal_client(scoped_b).get(f"/api/internal/packing/batches/{batch['id']}/")

    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert visible.status_code == 200
    assert hidden.status_code == 404


def test_remove_action_replays_frozen_body_and_delete_is_unavailable():
    tenant = Tenant.objects.create(name="F2 remove", code="f2-remove")
    user = create_internal(tenant, "remove-user")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-REMOVE", name="Remove")
    order, line = create_order(tenant, supplier, user, "REMOVE")
    client = internal_client(user)
    batch = create_batch(client, order, "remove-create").json()["data"]
    with_box = add_box(client, batch, line, "remove-add").json()["data"]
    box_id = with_box["boxes"][0]["id"]
    payload = {"expected_version": with_box["version"]}
    url = f"/api/internal/packing/batches/{batch['id']}/boxes/{box_id}/actions/remove/"

    first = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="remove-action")
    replay = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="remove-action")
    legacy = client.delete(
        f"/api/internal/packing/batches/{batch['id']}/boxes/{box_id}/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="legacy-delete",
    )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["data"]["boxes"] == []
    assert replay["Idempotency-Replayed"] == "true"
    assert legacy.status_code == 405
    assert PackingEvent.objects.filter(
        batch_id=batch["id"],
        action=PackingEvent.Action.REMOVE_BOX,
    ).count() == 1


def test_stale_version_uses_version_conflict():
    tenant = Tenant.objects.create(name="F2 version", code="f2-version")
    user = create_internal(tenant, "version-user")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-VERSION", name="Version")
    order, line = create_order(tenant, supplier, user, "VERSION")
    client = internal_client(user)
    batch = create_batch(client, order, "version-create").json()["data"]

    response = client.post(
        f"/api/internal/packing/batches/{batch['id']}/boxes/",
        {
            "expected_version": batch["version"] + 1,
            "items": [{"order_line_id": line.id, "quantity": line.quantity}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="version-stale",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert PackingApiIdempotencyRecord.objects.filter(
        tenant=tenant,
        idempotency_key="version-stale",
    ).count() == 0


def test_current_standard_scope_gate_and_external_channels():
    tenant = Tenant.objects.create(name="F2 standard", code="f2-standard")
    own = create_internal(
        tenant,
        "standard-own",
        permissions=("supply.packing.view",),
        scope_type=DataScope.ScopeType.OWN,
    )
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-STD", name="Standard")
    external = create_supplier_user(tenant, supplier, "standard-external")

    internal_response = internal_client(own).get("/api/internal/packing/standards/current/")
    supplier_response = supplier_client(external).get(
        "/api/external/supplier/packing/standards/current/"
    )
    miniapp_response = miniapp_client(external).get(
        "/api/miniapp/supply-chain/packing/standards/current/"
    )
    wrong_channel = miniapp_client(external).get(
        "/api/external/supplier/packing/standards/current/"
    )

    assert [internal_response.status_code, supplier_response.status_code, miniapp_response.status_code] == [
        200,
        200,
        200,
    ]
    assert set(internal_response.json()["data"]["rules"]) == {
        "empty_box_forbidden",
        "exact_completion_required",
        "mixed_box_label_items_required",
        "single_order_single_sku_recommended",
    }
    assert wrong_channel.status_code == 403


def test_supplier_and_miniapp_write_capability_and_safe_dto():
    tenant = Tenant.objects.create(name="F2 supplier", code="f2-supplier")
    internal = create_internal(tenant, "supplier-admin")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-SUP", name="Supplier")
    order, _ = create_order(tenant, supplier, internal, "SUP")
    external = create_supplier_user(tenant, supplier, "supplier-user")

    denied = supplier_client(external).post(
        "/api/external/supplier/packing/batches/",
        {"order_ids": [order.id]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="supplier-denied",
    )
    set_supplier_packing_capability(
        supplier_id=supplier.id,
        actor=internal,
        can_self_pack=True,
    )
    web = supplier_client(external).post(
        "/api/external/supplier/packing/batches/",
        {"order_ids": [order.id]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="supplier-create",
    )
    mini_wrong_channel = supplier_client(external).get(
        "/api/miniapp/supply-chain/packing/batches/"
    )

    assert denied.status_code == 403
    assert web.status_code == 201
    assert "created_by" not in web.json()["data"]
    assert "tenant" not in str(web.json()["data"]).lower()
    assert mini_wrong_channel.status_code == 403


def test_label_pdf_is_byte_deterministic_and_snapshot_is_minimal():
    tenant = Tenant.objects.create(name="F2 label", code="f2-label")
    user = create_internal(tenant, "label-user")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-LABEL", name="Label")
    order, line = create_order(tenant, supplier, user, "LABEL")
    client = internal_client(user)
    batch = create_batch(client, order, "label-create").json()["data"]
    with_box = add_box(client, batch, line, "label-add").json()["data"]
    url = f"/api/internal/packing/batches/{batch['id']}/actions/generate-label/"
    payload = {"expected_version": with_box["version"]}

    first = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="label-pdf")
    replay = client.post(url, payload, format="json", HTTP_IDEMPOTENCY_KEY="label-pdf")
    record = PackingApiIdempotencyRecord.objects.get(
        tenant=tenant,
        idempotency_key="label-pdf",
    )
    serialized_snapshot = str(record.label_snapshot).lower()

    assert first.status_code == replay.status_code == 200
    assert first["Content-Type"] == "application/pdf"
    assert first.content == replay.content
    assert first["ETag"] == replay["ETag"]
    assert replay["Idempotency-Replayed"] == "true"
    assert record.response_kind == PackingApiIdempotencyRecord.ResponseKind.LABEL
    assert record.response_body is None
    assert "sc-f2-packing-qr-v1" in serialized_snapshot
    assert "tenant_id" not in serialized_snapshot
    assert "http://" not in serialized_snapshot
    assert "https://" not in serialized_snapshot
    assert PackingEvent.objects.filter(
        batch_id=batch["id"],
        action=PackingEvent.Action.GENERATE_LABEL,
    ).count() == 1


def test_box_label_replays_after_box_is_removed():
    tenant = Tenant.objects.create(name="F2 box label replay", code="f2-box-label-replay")
    user = create_internal(tenant, "box-label-user")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-BOX-LABEL", name="Box label")
    order, line = create_order(tenant, supplier, user, "BOX-LABEL")
    client = internal_client(user)
    batch = create_batch(client, order, "box-label-create").json()["data"]
    with_box = add_box(client, batch, line, "box-label-add").json()["data"]
    box_id = with_box["boxes"][0]["id"]
    label_url = f"/api/internal/packing/boxes/{box_id}/actions/generate-label/"
    label_payload = {"expected_version": with_box["version"]}
    first = client.post(
        label_url,
        label_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="box-label-frozen",
    )
    removed = client.post(
        f"/api/internal/packing/batches/{batch['id']}/boxes/{box_id}/actions/remove/",
        {"expected_version": with_box["version"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="box-label-remove",
    )
    replay = client.post(
        label_url,
        label_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="box-label-frozen",
    )

    assert first.status_code == 200
    assert removed.status_code == 200
    assert replay.status_code == 200
    assert replay.content == first.content
    assert replay["ETag"] == first["ETag"]
    assert replay["Idempotency-Replayed"] == "true"


def test_completed_change_review_uses_review_permission_scope():
    tenant = Tenant.objects.create(name="F2 review", code="f2-review")
    submitter = create_internal(tenant, "review-submitter")
    reviewer = create_internal(
        tenant,
        "review-reviewer",
        permissions=("supply.packing.change.review",),
    )
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-REVIEW", name="Review")
    order, line = create_order(tenant, supplier, submitter, "REVIEW")
    client = internal_client(submitter)
    batch = create_batch(client, order, "review-create").json()["data"]
    with_box = add_box(client, batch, line, "review-add").json()["data"]
    completed = client.post(
        f"/api/internal/packing/batches/{batch['id']}/actions/complete/",
        {"expected_version": with_box["version"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="review-complete",
    ).json()["data"]
    submitted = client.post(
        f"/api/internal/packing/batches/{batch['id']}/change-requests/",
        {
            "expected_version": completed["version"],
            "reason": "Repack locally",
            "proposed_boxes": [
                {
                    "weight": "3.000",
                    "items": [{"order_line_id": line.id, "quantity": line.quantity}],
                }
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="review-submit",
    )
    change_id = submitted.json()["data"]["id"]
    review_client = internal_client(reviewer)
    queue = review_client.get("/api/internal/packing/change-requests/")
    approved = review_client.post(
        f"/api/internal/packing/change-requests/{change_id}/actions/approve/",
        {"review_note": "Approved locally"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="review-approve",
    )
    approved_replay = review_client.post(
        f"/api/internal/packing/change-requests/{change_id}/actions/approve/",
        {"review_note": "Approved locally"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="review-approve",
    )

    assert submitted.status_code == 201
    assert [item["id"] for item in queue.json()["data"]["results"]] == [change_id]
    assert approved.status_code == approved_replay.status_code == 200
    assert approved.json() == approved_replay.json()
    assert approved.json()["data"]["status"] == "approved"
    assert approved_replay["Idempotency-Replayed"] == "true"


def test_api_record_failure_rolls_back_domain_write(monkeypatch):
    tenant = Tenant.objects.create(name="F2 rollback", code="f2-rollback")
    user = create_internal(tenant, "rollback-user")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="F2-ROLL", name="Rollback")
    order, _ = create_order(tenant, supplier, user, "ROLL")
    client = internal_client(user)

    def fail_record(*args, **kwargs):
        raise RuntimeError("simulated API snapshot persistence failure")

    monkeypatch.setattr(PackingApiIdempotencyRecord.objects, "create", fail_record)
    with pytest.raises(RuntimeError):
        create_batch(client, order, "rollback-create")

    assert PackingBatch.objects.filter(tenant=tenant).count() == 0
    assert PackingEvent.objects.filter(tenant=tenant).count() == 0
    assert OperationLog.objects.filter(
        tenant=tenant,
        action="packing.create_batch",
    ).count() == 0
