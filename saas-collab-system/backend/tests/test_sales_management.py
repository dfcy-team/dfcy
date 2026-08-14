from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.catalog import PERMISSION_DEFINITIONS
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.integrations.sales_order_contract import SALES_ORDER_CONTRACT_VERSION, normalize_sales_order_record
from apps.sales_management.models import (
    DataQualityIssue,
    SalesExportRequest,
    SalesOrder,
    SalesOrderLine,
    SalesReturn,
    StoreSalesFact,
    SyncRerunRequest,
    SyncSource,
)
from apps.sales_management.services import create_export_request, upsert_normalized_order
from apps.tenants.models import Tenant


PERMISSION_CODES = {
    "sales_management.view",
    "sales_management.orders.view",
    "sales_management.returns.view",
    "sales_management.stores.view",
    "sales_management.skus.view",
    "sales_management.export",
    "sales_management.data_quality.view",
    "sales_management.sync.view",
    "sales_management.sync.rerun",
}


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, code, scope_type=DataScope.ScopeType.ALL, config=None):
    permission, _ = Permission.objects.get_or_create(
        code=code,
        defaults={"name": code, "module": "sales_management", "action": code.rsplit(".", 1)[-1]},
    )
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.id}")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_order(tenant, *, store_id="store-a", source_order_id="order-1"):
    return SalesOrder.objects.create(
        tenant=tenant,
        platform="shopee",
        region="SG",
        store_id=store_id,
        source_order_id=source_order_id,
        system_order_no=f"SYS-{tenant.id}-{source_order_id}",
        ordered_at="2026-08-11T08:00:00Z",
        currency="SGD",
        gross_amount=Decimal("120.00"),
        net_amount=Decimal("110.00"),
        source_updated_at="2026-08-11T08:05:00Z",
    )


@pytest.mark.django_db
def test_permission_catalog_declares_sales_management_contract():
    assert PERMISSION_CODES <= {item["code"] for item in PERMISSION_DEFINITIONS}


@pytest.mark.django_db
def test_orders_are_tenant_scoped_and_platform_ids_are_idempotent():
    tenant = Tenant.objects.create(name="Tenant A", code="sales-a")
    other = Tenant.objects.create(name="Tenant B", code="sales-b")
    payload = {
        "platform": "shopee",
        "region": "SG",
        "store_id": "store-a",
        "source_order_id": "source-1",
        "system_order_no": "SYS-1",
        "ordered_at": "2026-08-11T08:00:00Z",
        "currency": "SGD",
        "gross_amount": "120.00",
        "net_amount": "110.00",
        "source_updated_at": "2026-08-11T08:05:00Z",
        "lines": [{"source_line_id": "line-1", "sku": "SKU-1", "quantity": 2, "unit_price": "60.00"}],
    }

    first = upsert_normalized_order(tenant=tenant, payload=payload, source_batch="batch-1")
    second = upsert_normalized_order(tenant=tenant, payload={**payload, "net_amount": "108.00"}, source_batch="batch-2")
    other_order = upsert_normalized_order(tenant=other, payload=payload, source_batch="batch-1")

    assert first.id == second.id
    assert other_order.id != first.id
    assert SalesOrder.objects.filter(tenant=tenant).count() == 1
    assert SalesOrderLine.objects.filter(tenant=tenant, order=first).count() == 1
    assert SalesOrder.objects.get(pk=first.pk).net_amount == Decimal("108.00")
    with pytest.raises(IntegrityError), transaction.atomic():
        create_order(tenant, source_order_id="source-1")


@pytest.mark.django_db
def test_order_line_rejects_cross_tenant_parent():
    tenant = Tenant.objects.create(name="Tenant A", code="line-a")
    other = Tenant.objects.create(name="Tenant B", code="line-b")
    order = create_order(tenant)
    line = SalesOrderLine(tenant=other, order=order, source_line_id="line-x", sku="SKU-X", quantity=1)
    with pytest.raises(ValidationError, match="tenant"):
        line.full_clean()


@pytest.mark.django_db
def test_order_api_enforces_permission_tenant_and_store_scope():
    tenant = Tenant.objects.create(name="Tenant A", code="api-a")
    other = Tenant.objects.create(name="Tenant B", code="api-b")
    visible = create_order(tenant, store_id="store-visible", source_order_id="visible")
    create_order(tenant, store_id="store-hidden", source_order_id="hidden")
    create_order(other, store_id="store-visible", source_order_id="other")
    viewer = create_user(tenant, "sales-viewer")
    grant(viewer, "sales_management.orders.view", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-visible"]})

    response = client_for(viewer).get("/api/internal/sales-management/orders/")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["results"]] == [visible.id]
    assert "buyer_name" not in response.json()["data"]["results"][0]
    assert client_for(create_user(tenant, "no-sales-permission")).get(
        "/api/internal/sales-management/orders/"
    ).status_code == 403
    external = create_user(tenant, "external-sales", CustomUser.UserType.EXTERNAL)
    grant(external, "sales_management.orders.view")
    assert client_for(external).get("/api/internal/sales-management/orders/").status_code == 403


@pytest.mark.django_db
def test_order_detail_excludes_returns_with_mismatched_tenant_or_store():
    tenant = Tenant.objects.create(name="Tenant A", code="detail-a")
    other = Tenant.objects.create(name="Tenant B", code="detail-b")
    order = create_order(tenant, store_id="store-visible")
    user = create_user(tenant, "detail-viewer")
    grant(user, "sales_management.orders.view", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-visible"]})
    return_defaults = {
        "order": order,
        "platform": "shopee",
        "region": "SG",
        "status": "completed",
        "currency": "SGD",
        "requested_at": "2026-08-11T09:00:00Z",
        "source_updated_at": "2026-08-11T09:05:00Z",
    }
    visible = SalesReturn.objects.create(
        tenant=tenant, store_id="store-visible", source_return_id="return-visible", **return_defaults
    )
    SalesReturn.objects.create(
        tenant=other, store_id="store-visible", source_return_id="return-other-tenant", **return_defaults
    )
    SalesReturn.objects.create(
        tenant=tenant, store_id="store-hidden", source_return_id="return-hidden-store", **return_defaults
    )

    response = client_for(user).get(f"/api/internal/sales-management/orders/{order.id}/")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["returns"]] == [visible.id]


@pytest.mark.django_db
def test_overview_returns_traceable_metrics_and_explicit_source_state():
    tenant = Tenant.objects.create(name="Tenant", code="overview")
    user = create_user(tenant, "overview-user")
    grant(user, "sales_management.view")
    order = create_order(tenant)
    SalesOrderLine.objects.create(
        tenant=tenant, order=order, source_line_id="line-1", sku="SKU-1", quantity=2, unit_price="60.00"
    )
    StoreSalesFact.objects.create(
        tenant=tenant,
        platform="shopee",
        region="SG",
        store_id="store-a",
        period_start=date(2026, 8, 11),
        period_end=date(2026, 8, 11),
        currency="SGD",
        gross_sales="120.00",
        net_sales="110.00",
        order_count=1,
        units_sold=2,
        source_updated_at="2026-08-11T08:05:00Z",
    )

    payload = client_for(user).get("/api/internal/sales-management/overview/").json()["data"]

    assert payload["api_status"] == "mock"
    assert payload["aggregation_status"] == "single_currency"
    assert payload["currency"] == "SGD"
    assert payload["metrics"][0]["code"] == "gross_sales"
    assert payload["source_status"] in {"pending", "stale", "partial", "ready"}
    assert payload["definition"]["currency_basis"]
    assert "access_token" not in str(payload).lower()


@pytest.mark.django_db
def test_overview_never_sums_money_across_currencies():
    tenant = Tenant.objects.create(name="Tenant", code="overview-currencies")
    user = create_user(tenant, "currency-user")
    grant(user, "sales_management.view")
    for currency, gross, net, store_id in (
        ("SGD", "120.00", "110.00", "store-sg"),
        ("GBP", "80.00", "70.00", "store-gb"),
    ):
        StoreSalesFact.objects.create(
            tenant=tenant,
            platform="shopee",
            region="SG" if currency == "SGD" else "GB",
            store_id=store_id,
            period_start=date(2026, 8, 11),
            period_end=date(2026, 8, 11),
            currency=currency,
            gross_sales=gross,
            net_sales=net,
            order_count=1,
            units_sold=1,
            source_updated_at="2026-08-11T08:05:00Z",
        )

    client = client_for(user)
    grouped = client.get("/api/internal/sales-management/overview/").json()["data"]
    selected = client.get("/api/internal/sales-management/overview/?currency=SGD").json()["data"]

    assert grouped["aggregation_status"] == "grouped_by_currency"
    assert grouped["metrics"] == []
    assert {group["currency"] for group in grouped["currency_groups"]} == {"SGD", "GBP"}
    assert selected["currency"] == "SGD"
    assert selected["metrics"][0]["value"] == "120"


@pytest.mark.django_db
def test_export_inherits_scope_and_writes_audit():
    tenant = Tenant.objects.create(name="Tenant", code="export")
    user = create_user(tenant, "export-user")
    grant(user, "sales_management.export", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    client = client_for(user)

    denied = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"store_ids": ["store-b"]}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="export-denied",
    )
    created = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"store_ids": ["store-a"]}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="export-allowed",
    )
    repeated = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"store_ids": ["store-a"]}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="export-allowed",
    )

    assert denied.status_code == 403
    assert created.status_code == 201
    assert repeated.status_code == 200
    assert created.json()["data"]["id"] == repeated.json()["data"]["id"]
    export = SalesExportRequest.objects.get(pk=created.json()["data"]["id"])
    assert export.tenant == tenant
    assert export.data_scope[0]["config"]["store_ids"] == ["store-a"]
    assert OperationLog.objects.filter(tenant=tenant, module="sales_management", action="export.requested").count() == 1


@pytest.mark.django_db
def test_export_idempotency_is_isolated_by_actor_and_rejects_payload_or_scope_reuse():
    tenant = Tenant.objects.create(name="Tenant", code="export-idempotency")
    first_user = create_user(tenant, "export-first")
    second_user = create_user(tenant, "export-second")
    grant(first_user, "sales_management.export", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    grant(second_user, "sales_management.export", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    payload = {"export_type": "orders", "filters": {"store_ids": ["store-a"]}}

    first = client_for(first_user).post(
        "/api/internal/sales-management/exports/", payload, format="json", HTTP_IDEMPOTENCY_KEY="shared-key"
    )
    second = client_for(second_user).post(
        "/api/internal/sales-management/exports/", payload, format="json", HTTP_IDEMPOTENCY_KEY="shared-key"
    )
    conflict = client_for(first_user).post(
        "/api/internal/sales-management/exports/",
        {"export_type": "order_lines", "filters": {"store_ids": ["store-a"]}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="shared-key",
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["id"] != second.json()["data"]["id"]
    assert conflict.status_code == 400
    assert SalesExportRequest.objects.filter(tenant=tenant, request_key="shared-key").count() == 2


@pytest.mark.django_db
def test_export_history_is_hidden_after_data_scope_shrinks():
    tenant = Tenant.objects.create(name="Tenant", code="export-history-scope")
    user = create_user(tenant, "export-history-user")
    grant(user, "sales_management.export", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    client = client_for(user)
    old_export = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"store_id": "store-a"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="old-scope",
    )
    scope = DataScope.objects.get(tenant=tenant)
    scope.config = {"store_ids": ["store-b"]}
    scope.save(update_fields=["config"])
    current_export = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"store_id": "store-b"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="current-scope",
    )
    safe_current_scope = [{"scope_type": "custom", "config": {"store_ids": ["store-b"]}}]
    SalesExportRequest.objects.create(
        tenant=tenant,
        requested_by=user,
        request_key="legacy-sensitive-filter",
        export_type="orders",
        filters={"access_token": "legacy-secret"},
        data_scope=safe_current_scope,
    )
    SalesExportRequest.objects.create(
        tenant=tenant,
        requested_by=user,
        request_key="legacy-sensitive-scope",
        export_type="orders",
        filters={"store_id": "store-b"},
        data_scope=[{"scope_type": "custom", "config": {"credential_ids": ["legacy-credential"]}}],
    )

    history = client.get("/api/internal/sales-management/exports/")

    assert old_export.status_code == 201
    assert current_export.status_code == 201
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["data"]["results"]] == [current_export.json()["data"]["id"]]


@pytest.mark.django_db
def test_export_filters_reject_unknown_sensitive_and_out_of_scope_fields():
    tenant = Tenant.objects.create(name="Tenant", code="export-filter-contract")
    user = create_user(tenant, "export-filter-user")
    grant(user, "sales_management.export", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    client = client_for(user)

    unknown = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"customer_email": "buyer@example.invalid"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="unknown-filter",
    )
    sensitive = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"store_id": {"access_token": "must-not-persist"}}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="sensitive-filter",
    )
    denied = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"store_id": "store-b"}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="singular-scope-bypass",
    )

    assert unknown.status_code == 400
    assert sensitive.status_code == 400
    assert denied.status_code == 403
    assert SalesExportRequest.objects.filter(tenant=tenant).count() == 0
    assert OperationLog.objects.filter(tenant=tenant, action="export.requested").count() == 0


@pytest.mark.django_db
def test_export_idempotency_key_length_is_validated_before_database_write():
    tenant = Tenant.objects.create(name="Tenant", code="export-key-length")
    user = create_user(tenant, "export-key-user")
    grant(user, "sales_management.export")
    client = client_for(user)

    accepted = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k" * 120,
    )
    rejected = client.post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k" * 121,
    )
    with pytest.raises(DRFValidationError, match="at most 120"):
        create_export_request(
            user=user,
            request_key="s" * 121,
            export_type="orders",
            filters={},
            data_scope=[{"scope_type": "all", "config": {}}],
        )

    assert accepted.status_code == 201
    assert rejected.status_code == 400
    assert SalesExportRequest.objects.filter(tenant=tenant).count() == 1
    assert OperationLog.objects.filter(tenant=tenant, action="export.requested").count() == 1


@pytest.mark.django_db
def test_data_quality_and_manual_rerun_are_scoped_idempotent_and_audited():
    tenant = Tenant.objects.create(name="Tenant", code="quality")
    user = create_user(tenant, "quality-user")
    grant(user, "sales_management.data_quality.view")
    grant(user, "sales_management.sync.view", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    grant(user, "sales_management.sync.rerun", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    source = SyncSource.objects.create(
        tenant=tenant,
        platform="tiktok_shop",
        region="GB",
        store_id="store-a",
        credential_id="credential-ref-1",
        credential_mask="授权连接 …001",
        authorization_status="active",
        run_status="partial",
        error_summary="分页读取超时",
    )
    DataQualityIssue.objects.create(
        tenant=tenant,
        issue_key="missing-sku-1",
        issue_type="sku_unmapped",
        severity="high",
        platform="tiktok_shop",
        region="GB",
        store_id="store-a",
        message="1 条订单行未匹配 SKU",
    )
    client = client_for(user)

    quality = client.get("/api/internal/sales-management/data-quality/")
    with patch.object(SyncSource.objects, "select_for_update", wraps=SyncSource.objects.select_for_update) as source_lock:
        first = client.post(
            "/api/internal/sales-management/sync-reruns/",
            {"sync_source_id": source.id, "reason": "重新拉取失败页"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="rerun-1",
        )
    source_lock.assert_called_once_with()
    source.run_status = "success"
    source.save(update_fields=["run_status"])
    second = client.post(
        "/api/internal/sales-management/sync-reruns/",
        {"sync_source_id": source.id, "reason": "重新拉取失败页"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rerun-1",
    )
    new_request_after_success = client.post(
        "/api/internal/sales-management/sync-reruns/",
        {"sync_source_id": source.id, "reason": "重新拉取失败页"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rerun-2",
    )

    assert quality.status_code == 200
    assert quality.json()["data"]["issues"][0]["issue_type"] == "sku_unmapped"
    assert first.status_code == 201
    assert second.status_code == 200
    assert new_request_after_success.status_code == 400
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert SyncRerunRequest.objects.filter(tenant=tenant).count() == 1
    assert OperationLog.objects.filter(tenant=tenant, module="sales_management", action="sync.rerun_requested").count() == 1


@pytest.mark.django_db
def test_sync_view_permission_cannot_request_rerun_and_idempotency_rejects_context_change():
    tenant = Tenant.objects.create(name="Tenant", code="rerun-permission")
    viewer = create_user(tenant, "sync-viewer")
    runner = create_user(tenant, "sync-runner")
    grant(viewer, "sales_management.sync.view", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    grant(runner, "sales_management.sync.rerun", DataScope.ScopeType.CUSTOM, {"store_ids": ["store-a"]})
    source = SyncSource.objects.create(tenant=tenant, platform="tiktok", store_id="store-a", run_status="failed")
    request_payload = {"sync_source_id": source.id, "reason": "retry failed page"}

    denied = client_for(viewer).post(
        "/api/internal/sales-management/sync-reruns/",
        request_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="rerun-key",
    )
    created = client_for(runner).post(
        "/api/internal/sales-management/sync-reruns/",
        request_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="rerun-key",
    )
    conflict = client_for(runner).post(
        "/api/internal/sales-management/sync-reruns/",
        {**request_payload, "reason": "different reason"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rerun-key",
    )

    assert denied.status_code == 403
    assert created.status_code == 201
    assert conflict.status_code == 400
    rerun = SyncRerunRequest.objects.get(pk=created.json()["data"]["id"])
    assert rerun.requested_by == runner
    assert rerun.data_scope[0]["config"]["store_ids"] == ["store-a"]


@pytest.mark.django_db
@pytest.mark.parametrize("run_status", ["pending", "running", "success", "completed"])
def test_sync_rerun_rejects_non_failed_source_states(run_status):
    tenant = Tenant.objects.create(name="Tenant", code=f"rerun-state-{run_status}")
    user = create_user(tenant, f"rerun-{run_status}")
    grant(user, "sales_management.sync.rerun")
    source = SyncSource.objects.create(tenant=tenant, platform="shopee", store_id="store-a", run_status=run_status)

    response = client_for(user).post(
        "/api/internal/sales-management/sync-reruns/",
        {"sync_source_id": source.id, "reason": "manual retry"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"rerun-{run_status}",
    )

    assert response.status_code == 400
    assert SyncRerunRequest.objects.filter(tenant=tenant).count() == 0
    assert OperationLog.objects.filter(tenant=tenant, action="sync.rerun_requested").count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("request_key", "reason"),
    [
        ("k" * 121, "manual retry"),
        ("valid-key", "r" * 241),
        ("valid-key", ["not", "a", "string"]),
    ],
)
def test_sync_rerun_rejects_invalid_fields_before_database_write(request_key, reason):
    tenant = Tenant.objects.create(name="Tenant", code=f"rerun-input-{len(request_key)}-{len(reason)}")
    user = create_user(tenant, f"rerun-input-{len(request_key)}-{len(reason)}")
    grant(user, "sales_management.sync.rerun")
    source = SyncSource.objects.create(tenant=tenant, platform="shopee", store_id="store-a", run_status="failed")

    response = client_for(user).post(
        "/api/internal/sales-management/sync-reruns/",
        {"sync_source_id": source.id, "reason": reason},
        format="json",
        HTTP_IDEMPOTENCY_KEY=request_key,
    )

    assert response.status_code == 400
    assert SyncRerunRequest.objects.filter(tenant=tenant).count() == 0
    assert OperationLog.objects.filter(tenant=tenant, action="sync.rerun_requested").count() == 0


def test_integration_contract_accepts_only_normalized_versioned_records_and_rejects_secret_material():
    normalized = normalize_sales_order_record(
        "shopee",
        {
            "contract_version": SALES_ORDER_CONTRACT_VERSION,
            "source_order_id": "SHP-1",
            "store_id": "store-a",
            "region": "SG",
            "ordered_at": "2026-08-11T08:00:00Z",
            "source_updated_at": "2026-08-11T08:05:00Z",
            "currency": "SGD",
            "gross_amount": "120.00",
            "order_status": "confirmed",
            "lines": [{"source_line_id": "line-1", "sku": "SKU-1", "quantity": 2, "unit_price": "60.00"}],
        },
    )
    assert normalized["order_status"] == "confirmed"
    assert normalized["source_order_id"] == "SHP-1"
    with pytest.raises(ValidationError, match="credential"):
        normalize_sales_order_record(
            "tiktok",
            {"contract_version": SALES_ORDER_CONTRACT_VERSION, "source_order_id": "TK-1", "access_token": "must-not-enter"},
        )
    with pytest.raises(ValidationError, match="normalized"):
        normalize_sales_order_record(
            "shopee",
            {
                "contract_version": SALES_ORDER_CONTRACT_VERSION,
                "source_order_id": "SHP-2",
                "store_id": "store-a",
                "ordered_at": "2026-08-11T08:00:00Z",
                "source_updated_at": "2026-08-11T08:05:00Z",
                "currency": "SGD",
                "gross_amount": "120.00",
                "order_status": "READY_TO_SHIP",
            },
        )
