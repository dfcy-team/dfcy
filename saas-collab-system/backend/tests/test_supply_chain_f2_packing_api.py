import pytest
from django.db import IntegrityError, OperationalError
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.audit.models import OperationLog
from apps.masterdata.models import SupplierMaster
from apps.packing.api_idempotency import canonical_hash
from apps.packing.models import (
    PackingApiIdempotencyRecord,
    PackingBatch,
    PackingEvent,
    PackingStandardVersion,
    _packing_domain_write_context,
)
from apps.packing.serializers import PackingChangeSubmitSerializer
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


@pytest.mark.parametrize("mysql_code", [1205, 1213])
def test_api_idempotency_retryable_mysql_errors_map_to_state_conflict(
    monkeypatch,
    mysql_code,
):
    tenant = Tenant.objects.create(name=f"F2 API DB {mysql_code}", code=f"f2-api-db-{mysql_code}")
    user = create_internal(tenant, f"f2-api-db-user-{mysql_code}")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code=f"F2-DB-{mysql_code}",
        name="Database conflict",
    )
    order, _ = create_order(tenant, supplier, user, f"DB-{mysql_code}")

    def fail_find(*args, **kwargs):
        raise OperationalError(mysql_code, "simulated retryable MySQL conflict")

    monkeypatch.setattr("apps.packing.api_idempotency._find_record", fail_find)
    response = create_batch(internal_client(user), order, f"db-conflict-{mysql_code}")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    assert PackingBatch.objects.filter(tenant=tenant).count() == 0


def test_api_idempotency_non_retryable_database_error_is_not_hidden(monkeypatch):
    tenant = Tenant.objects.create(name="F2 API DB other", code="f2-api-db-other")
    user = create_internal(tenant, "f2-api-db-other-user")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code="F2-DB-OTHER",
        name="Database failure",
    )
    order, _ = create_order(tenant, supplier, user, "DB-OTHER")

    def fail_find(*args, **kwargs):
        raise OperationalError(2005, "simulated non-retryable database failure")

    monkeypatch.setattr("apps.packing.api_idempotency._find_record", fail_find)
    with pytest.raises(OperationalError):
        create_batch(internal_client(user), order, "db-conflict-other")


@pytest.mark.parametrize("mysql_code", [1205, 1213])
def test_api_idempotency_record_insert_retryable_error_rolls_back_and_maps(
    monkeypatch,
    mysql_code,
):
    tenant = Tenant.objects.create(
        name=f"F2 API insert {mysql_code}",
        code=f"f2-api-insert-{mysql_code}",
    )
    user = create_internal(tenant, f"f2-api-insert-user-{mysql_code}")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code=f"F2-INSERT-{mysql_code}",
        name="API record insert",
    )
    order, _ = create_order(tenant, supplier, user, f"INSERT-{mysql_code}")

    def fail_record(*args, **kwargs):
        raise OperationalError(mysql_code, "simulated API record insert conflict")

    monkeypatch.setattr(PackingApiIdempotencyRecord.objects, "create", fail_record)
    response = create_batch(internal_client(user), order, f"insert-conflict-{mysql_code}")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    assert PackingBatch.objects.filter(tenant=tenant).count() == 0
    assert PackingEvent.objects.filter(tenant=tenant).count() == 0


def test_api_idempotency_conflict_recovery_retryable_error_maps(monkeypatch):
    tenant = Tenant.objects.create(name="F2 API recovery", code="f2-api-recovery")
    user = create_internal(tenant, "f2-api-recovery-user")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code="F2-RECOVERY",
        name="API recovery",
    )
    order, _ = create_order(tenant, supplier, user, "RECOVERY")
    find_results = iter([None, OperationalError(1213, "simulated recovery deadlock")])

    def staged_find(*args, **kwargs):
        result = next(find_results)
        if isinstance(result, Exception):
            raise result
        return result

    def duplicate_record(*args, **kwargs):
        raise IntegrityError("simulated API idempotency unique race")

    monkeypatch.setattr("apps.packing.api_idempotency._find_record", staged_find)
    monkeypatch.setattr(PackingApiIdempotencyRecord.objects, "create", duplicate_record)
    response = create_batch(internal_client(user), order, "recovery-conflict")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    assert PackingBatch.objects.filter(tenant=tenant).count() == 0


def test_request_content_type_query_and_decimal_contract_is_strict():
    tenant = Tenant.objects.create(name="F2 request strict", code="f2-request-strict")
    user = create_internal(tenant, "request-strict-user")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code="F2-STRICT",
        name="Strict request",
    )
    order, line = create_order(tenant, supplier, user, "STRICT")
    client = internal_client(user)

    form_response = client.post(
        "/api/internal/packing/batches/",
        {"order_ids": [order.id]},
        HTTP_IDEMPOTENCY_KEY="strict-form",
    )
    unknown_standard_query = client.get(
        "/api/internal/packing/standards/current/?unexpected=1"
    )
    batch = create_batch(client, order, "strict-create").json()["data"]
    unknown_detail_query = client.get(
        f"/api/internal/packing/batches/{batch['id']}/?unexpected=1"
    )
    numeric_decimal = client.post(
        f"/api/internal/packing/batches/{batch['id']}/boxes/",
        {
            "expected_version": batch["version"],
            "weight": 2.5,
            "volume": 0.125,
            "items": [{"order_line_id": line.id, "quantity": line.quantity}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="strict-number",
    )
    scientific_decimal = client.post(
        f"/api/internal/packing/batches/{batch['id']}/boxes/",
        {
            "expected_version": batch["version"],
            "weight": "2.5e0",
            "items": [{"order_line_id": line.id, "quantity": line.quantity}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="strict-scientific",
    )

    assert form_response.status_code == 400
    assert unknown_standard_query.status_code == 400
    assert unknown_detail_query.status_code == 400
    assert numeric_decimal.status_code == 400
    assert scientific_decimal.status_code == 400
    assert PackingEvent.objects.filter(
        batch_id=batch["id"],
        action=PackingEvent.Action.ADD_BOX,
    ).count() == 0


def test_reordered_box_items_replay_same_normalized_payload():
    tenant = Tenant.objects.create(name="F2 normalized items", code="f2-normalized-items")
    user = create_internal(tenant, "normalized-items-user")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code="F2-NORMALIZED",
        name="Normalized items",
    )
    first_order, first_line = create_order(
        tenant,
        supplier,
        user,
        "NORMALIZED-1",
        quantity=4,
    )
    second_order, second_line = create_order(
        tenant,
        supplier,
        user,
        "NORMALIZED-2",
        quantity=6,
    )
    client = internal_client(user)
    batch = client.post(
        "/api/internal/packing/batches/",
        {"order_ids": [first_order.id, second_order.id]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="normalized-create",
    ).json()["data"]
    url = f"/api/internal/packing/batches/{batch['id']}/boxes/"
    common = {
        "expected_version": batch["version"],
        "weight": "2.500",
        "volume": "0.125000",
    }

    first = client.post(
        url,
        {
            **common,
            "items": [
                {"order_line_id": second_line.id, "quantity": 6},
                {"order_line_id": first_line.id, "quantity": 4},
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="normalized-add",
    )
    replay = client.post(
        url,
        {
            **common,
            "items": [
                {"order_line_id": first_line.id, "quantity": 4},
                {"order_line_id": second_line.id, "quantity": 6},
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="normalized-add",
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert replay["Idempotency-Replayed"] == "true"
    assert PackingEvent.objects.filter(
        batch_id=batch["id"],
        action=PackingEvent.Action.ADD_BOX,
    ).count() == 1
    first_change = PackingChangeSubmitSerializer(
        data={
            "expected_version": 2,
            "reason": "Normalize proposed items",
            "proposed_boxes": [
                {
                    "items": [
                        {"order_line_id": second_line.id, "quantity": 6},
                        {"order_line_id": first_line.id, "quantity": 4},
                    ]
                }
            ],
        }
    )
    reordered_change = PackingChangeSubmitSerializer(
        data={
            "expected_version": 2,
            "reason": "Normalize proposed items",
            "proposed_boxes": [
                {
                    "items": [
                        {"order_line_id": first_line.id, "quantity": 4},
                        {"order_line_id": second_line.id, "quantity": 6},
                    ]
                }
            ],
        }
    )
    assert first_change.is_valid(), first_change.errors
    assert reordered_change.is_valid(), reordered_change.errors
    assert canonical_hash(first_change.validated_data) == canonical_hash(
        reordered_change.validated_data
    )


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


def test_current_standard_uses_same_code_as_new_batches():
    tenant = Tenant.objects.create(name="F2 standard choice", code="f2-standard-choice")
    user = create_internal(tenant, "standard-choice-user")
    with _packing_domain_write_context():
        PackingStandardVersion.objects.create(
            code="aaa-alternate",
            version=99,
            title="Alternate standard",
            rules={"exact_completion_required": False},
            is_active=True,
        )

    response = internal_client(user).get("/api/internal/packing/standards/current/")

    assert response.status_code == 200
    assert response.json()["data"]["code"] == "packing-v1"


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


def test_supplier_existing_mixed_order_writes_only_require_self_pack():
    tenant = Tenant.objects.create(name="F2 supplier mixed", code="f2-supplier-mixed")
    internal = create_internal(tenant, "supplier-mixed-admin")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code="F2-SUP-MIXED",
        name="Supplier mixed",
    )
    first_order, first_line = create_order(tenant, supplier, internal, "SUP-MIXED-1")
    second_order, second_line = create_order(tenant, supplier, internal, "SUP-MIXED-2")
    external = create_supplier_user(tenant, supplier, "supplier-mixed-user")
    set_supplier_packing_capability(
        supplier_id=supplier.id,
        actor=internal,
        can_self_pack=True,
        can_mix_order_packing=True,
    )
    web_client = supplier_client(external)
    created = web_client.post(
        "/api/external/supplier/packing/batches/",
        {"order_ids": [first_order.id, second_order.id]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="supplier-mixed-create",
    ).json()["data"]
    set_supplier_packing_capability(
        supplier_id=supplier.id,
        actor=internal,
        can_self_pack=True,
        can_mix_order_packing=False,
    )
    added = web_client.post(
        f"/api/external/supplier/packing/batches/{created['id']}/boxes/",
        {
            "expected_version": created["version"],
            "items": [
                {"order_line_id": first_line.id, "quantity": first_line.quantity},
                {"order_line_id": second_line.id, "quantity": second_line.quantity},
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="supplier-mixed-add",
    )
    added_data = added.json()["data"]
    box_id = added_data["boxes"][0]["id"]
    miniapp_updated = miniapp_client(external).put(
        f"/api/miniapp/supply-chain/packing/batches/{created['id']}/boxes/{box_id}/",
        {
            "expected_version": added_data["version"],
            "items": [
                {"order_line_id": second_line.id, "quantity": second_line.quantity},
                {"order_line_id": first_line.id, "quantity": first_line.quantity},
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="supplier-mixed-update",
    )

    assert added.status_code == 201
    assert miniapp_updated.status_code == 200


def test_supplier_list_rejects_internal_date_filters():
    tenant = Tenant.objects.create(name="F2 supplier filters", code="f2-supplier-filters")
    internal = create_internal(tenant, "supplier-filter-admin")
    supplier = SupplierMaster.objects.create(
        tenant=tenant,
        code="F2-SUP-FILTER",
        name="Supplier filter",
    )
    external = create_supplier_user(tenant, supplier, "supplier-filter-user")

    response = supplier_client(external).get(
        "/api/external/supplier/packing/batches/?created_at_from=2026-01-01T00:00:00Z"
    )

    assert response.status_code == 400


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
