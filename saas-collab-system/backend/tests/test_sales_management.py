from datetime import UTC, datetime
import pytest
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.commerce.models import InventorySnapshot, RefundReturn, RefundReturnItem
from apps.integrations.models import (
    APIDataQualityCheck,
    APISyncLog,
    APISyncTask,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
)
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.reports.models import ReportExportRequest
from apps.sales_management.services import upsert_normalized_order
from apps.tenants.models import Tenant
from apps.reports.export_services import create_export_request


NOW = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)


def user_for(tenant, username):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


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


def create_scope(code, currency="PHP", country="PH"):
    tenant = Tenant.objects.create(name=code, code=code)
    platform = PlatformMaster.objects.create(
        tenant=tenant, code=f"shopee-{code}", name="Shopee", platform_type="shopee"
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name=code,
        country_code=country,
        currency=currency,
        timezone="Asia/Manila" if country == "PH" else "Asia/Bangkok",
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code=f"warehouse-{code}",
        name=code,
        country_code=country,
        warehouse_type="third_party",
    )
    return tenant, platform, store, warehouse


def create_run(tenant, resource_type, suffix, platform="shopee"):
    user = user_for(tenant, f"source-{suffix}")
    authorization = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform=platform, account_alias=f"auth-{suffix}", created_by=user
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=authorization, resource_type=resource_type)
    return SyncRun.objects.create(
        tenant=tenant, sync_job=job, run_id=f"run-{suffix}", idempotency_key=f"key-{suffix}"
    )


def create_order(tenant, store, suffix, amount="100.0000"):
    run = create_run(tenant, "sales_order", f"order-{suffix}")
    return upsert_normalized_order(
        tenant=tenant,
        source_run=run,
        payload={
            "contract_version": "1.0",
            "store_id": store.id,
            "external_order_id": f"ORDER-{suffix}",
            "region": store.country_code,
            "raw_status": "COMPLETED",
            "normalized_status": "completed",
            "created_at_utc": NOW.isoformat(),
            "updated_at_utc": NOW.isoformat(),
            "currency": store.currency,
            "order_total_amount": amount,
            "lines": [
                {
                    "external_line_id": f"LINE-{suffix}",
                    "platform_product_id": f"PRODUCT-{suffix}",
                    "seller_sku": f"SKU-{suffix}",
                    "quantity": 2,
                    "sale_unit_price": str(float(amount) / 2),
                    "line_total_amount": amount,
                    "currency": store.currency,
                }
            ],
        },
    )


@pytest.mark.django_db
def test_orders_are_tenant_and_store_scope_filtered_on_both_routes():
    tenant, _, visible_store, _ = create_scope("api-visible")
    _, _, hidden_store, _ = create_scope("api-hidden")
    visible = create_order(tenant, visible_store, "visible")
    create_order(hidden_store.tenant, hidden_store, "hidden")
    viewer = user_for(tenant, "viewer")
    grant(
        viewer,
        "sales_management.orders.view",
        DataScope.ScopeType.CUSTOM,
        {"store_ids": [str(visible_store.id)]},
    )

    for path in ("/api/internal/sales-management/orders/", "/api/internal/commerce/orders/"):
        response = client_for(viewer).get(path)
        assert response.status_code == 200
        assert [row["id"] for row in response.json()["data"]["results"]] == [visible.id]
        assert "buyer_name" not in response.json()["data"]["results"][0]


@pytest.mark.django_db
def test_linkage_status_is_tenant_scoped_and_exposes_the_operating_chain():
    tenant, _, store, _ = create_scope("linkage-visible")
    hidden_tenant, _, hidden_store, _ = create_scope("linkage-hidden")
    create_order(tenant, store, "linkage-visible")
    create_order(hidden_tenant, hidden_store, "linkage-hidden")
    viewer = user_for(tenant, "linkage-viewer")
    grant(viewer, "sales_management.data_quality.view")

    response = client_for(viewer).get("/api/internal/commerce/linkage-status/")

    assert response.status_code == 200
    data = response.json()["data"]
    assert [step["key"] for step in data["steps"]] == [
        "masterdata", "authorization", "sync", "facts"
    ]
    assert data["tenant_id"] == tenant.id
    assert data["steps"][0]["label"] == "本地基础档案"
    assert data["counts"]["orders"] == 1
    assert data["counts"]["stores"] == 1


@pytest.mark.django_db
def test_order_detail_embeds_refund_header_and_multiple_items():
    tenant, platform, store, _ = create_scope("detail")
    order = create_order(tenant, store, "detail")
    refund_run = create_run(tenant, "refund_return", "detail-refund")
    refund = RefundReturn.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        sales_order=order,
        source_run=refund_run,
        external_return_id="RETURN-DETAIL",
        case_type="return_refund",
        raw_status="COMPLETED",
        normalized_status="completed",
        requested_at_utc=NOW,
        updated_at_utc=NOW,
        currency="PHP",
        refund_amount="20.0000",
        is_partial_quantity_return=True,
        is_refund_amount_adjusted=True,
        payload_hash="a" * 64,
    )
    for index in range(2):
        RefundReturnItem.objects.create(
            refund_return=refund,
            external_return_item_id=f"RETURN-LINE-{index}",
            seller_sku=f"SKU-{index}",
            quantity=1,
            currency="PHP",
            refund_amount="10.0000",
        )
    viewer = user_for(tenant, "detail-viewer")
    grant(viewer, "sales_management.orders.view")

    response = client_for(viewer).get(f"/api/internal/commerce/orders/{order.id}/")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["external_order_id"] == "ORDER-detail"
    assert data["store"]["region"] == "PH"
    assert data["refund_summary"] == {
        "has_refund_return": True,
        "case_count": 1,
        "refund_amount": "20.0000",
        "latest_status": "completed",
        "is_partial_quantity_return": True,
        "is_refund_amount_adjusted": True,
    }
    assert data["refund_returns"][0]["is_partial_quantity_return"] is True
    assert len(data["refund_returns"][0]["items"]) == 2
    assert data["items"][0]["platform_product_id"] == "PRODUCT-detail"


@pytest.mark.django_db
def test_order_list_refund_filters_use_refund_facts_not_cancelled_status():
    tenant, platform, store, _ = create_scope("refund-filter")
    refunded = create_order(tenant, store, "refunded")
    cancelled = create_order(tenant, store, "cancelled")
    cancelled.normalized_status = "cancelled"
    cancelled.save(update_fields=["normalized_status"])
    refund_run = create_run(tenant, "refund_return", "filter-refund")
    RefundReturn.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        sales_order=refunded,
        source_run=refund_run,
        external_return_id="RETURN-FILTER",
        case_type="refund_only",
        raw_status="COMPLETED",
        normalized_status="completed",
        requested_at_utc=NOW,
        updated_at_utc=NOW,
        currency="PHP",
        refund_amount="10.0000",
        payload_hash="f" * 64,
    )
    viewer = user_for(tenant, "refund-filter-viewer")
    grant(viewer, "sales_management.orders.view")
    returns_viewer = user_for(tenant, "returns-filter-viewer")
    grant(returns_viewer, "sales_management.returns.view")

    client = client_for(viewer)
    with_refund = client.get("/api/internal/commerce/orders/?has_refund_return=true")
    without_refund = client.get("/api/internal/commerce/orders/?has_refund_return=false")
    refunds = client_for(returns_viewer).get("/api/internal/commerce/refunds/")

    assert [row["id"] for row in with_refund.json()["data"]["results"]] == [refunded.id]
    assert [row["id"] for row in without_refund.json()["data"]["results"]] == [cancelled.id]
    assert refunds.status_code == 200
    assert refunds.json()["data"]["results"][0]["external_return_id"] == "RETURN-FILTER"


@pytest.mark.django_db
def test_overview_never_combines_currencies_and_refund_comes_from_refund_fact():
    tenant, _, php_store, _ = create_scope("currency-php", currency="PHP", country="PH")
    th_platform = PlatformMaster.objects.create(
        tenant=tenant, code="shopee-th", name="Shopee TH", platform_type="shopee"
    )
    th_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=th_platform,
        code="store-th",
        name="TH",
        country_code="TH",
        currency="THB",
        timezone="Asia/Bangkok",
    )
    php_order = create_order(tenant, php_store, "php", "100.0000")
    create_order(tenant, th_store, "thb", "200.0000")
    cancelled = create_order(tenant, php_store, "php-cancelled", "900.0000")
    cancelled.normalized_status = "cancelled"
    cancelled.save(update_fields=["normalized_status"])
    refund_run = create_run(tenant, "refund_return", "currency-refund")
    RefundReturn.objects.create(
        tenant=tenant,
        platform=php_order.platform,
        store=php_store,
        sales_order=php_order,
        source_run=refund_run,
        external_return_id="RETURN-PHP",
        case_type="refund_only",
        raw_status="COMPLETED",
        normalized_status="completed",
        requested_at_utc=NOW,
        updated_at_utc=NOW,
        currency="PHP",
        refund_amount="10.0000",
        payload_hash="b" * 64,
    )
    viewer = user_for(tenant, "overview-viewer")
    grant(viewer, "sales_management.view")

    grouped = client_for(viewer).get("/api/internal/commerce/overview/").json()["data"]
    selected = client_for(viewer).get("/api/internal/commerce/overview/?currency=PHP").json()["data"]
    assert grouped["aggregation_status"] == "grouped_by_currency"
    assert grouped["metrics"] == []
    assert {group["currency"] for group in grouped["currency_groups"]} == {"PHP", "THB"}
    assert selected["currency"] == "PHP"
    assert next(metric for metric in selected["metrics"] if metric["code"] == "refund_amount")["value"] == "10"
    assert next(metric for metric in selected["metrics"] if metric["code"] == "gross_sales")["value"] == "100"
    assert next(metric for metric in selected["metrics"] if metric["code"] == "cancelled_order_count")["value"] == "1"


@pytest.mark.django_db
def test_sales_overview_matches_the_handoff_display_dimensions():
    tenant, platform, store, _ = create_scope("handoff-sales")
    order = create_order(tenant, store, "handoff-sales", "100.0000")
    cancelled = create_order(tenant, store, "handoff-sales-cancelled", "900.0000")
    cancelled.normalized_status = "cancelled"
    cancelled.save(update_fields=["normalized_status"])
    refund_run = create_run(tenant, "refund_return", "handoff-sales-refund")
    refund = RefundReturn.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        sales_order=order,
        source_run=refund_run,
        external_return_id="RETURN-HANDOFF-SALES",
        case_type="refund_only",
        raw_status="PROCESSING",
        normalized_status="processing",
        requested_at_utc=NOW,
        updated_at_utc=NOW,
        currency="PHP",
        refund_amount="50.0000",
        payload_hash="d" * 64,
    )
    RefundReturnItem.objects.create(
        refund_return=refund,
        external_return_item_id="RETURN-HANDOFF-LINE",
        seller_sku="SKU-handoff-sales",
        quantity=1,
        currency="PHP",
        refund_amount="50.0000",
    )
    viewer = user_for(tenant, "handoff-sales-viewer")
    grant(viewer, "sales_management.view")

    data = client_for(viewer).get("/api/internal/commerce/overview/").json()["data"]
    metrics = {metric["code"]: metric for metric in data["summary_metrics"]}

    assert list(metrics) == [
        "gross_sales", "net_sales", "order_count", "units_sold",
        "average_order_value", "refund_rate",
    ]
    assert metrics["gross_sales"]["money"] == {"PHP": "100"}
    assert metrics["net_sales"]["money"] == {"PHP": "50"}
    assert metrics["order_count"]["value"] == 2
    assert metrics["units_sold"]["value"] == 4
    assert metrics["average_order_value"]["money"] == {"PHP": "50"}
    assert metrics["refund_rate"]["value"] == "50.0%"
    assert data["quality"]["checked_rows"] == 6
    assert data["results"][0]["source_alias"] == "auth-order-handoff-sales-cancelled"
    assert data["results"][0]["average_order_value"] == "50"


@pytest.mark.django_db
def test_inventory_endpoint_reads_inventory_snapshot_only():
    tenant, _, _, warehouse = create_scope("inventory")
    run = create_run(tenant, "inventory_snapshot", "inventory", platform="jifeng_wms")
    snapshot = InventorySnapshot.objects.create(
        tenant=tenant,
        site_code="PH",
        warehouse=warehouse,
        source_run=run,
        source_sku="WMS-SKU-1",
        available_qty=8,
        snapshot_at_utc=NOW,
        payload_hash="c" * 64,
    )
    viewer = user_for(tenant, "inventory-viewer")
    grant(viewer, "sales_management.view")
    response = client_for(viewer).get("/api/internal/commerce/inventory/")
    assert response.status_code == 200
    assert response.json()["data"]["results"][0]["id"] == snapshot.id
    assert response.json()["data"]["results"][0]["available_qty"] == 8


@pytest.mark.django_db
def test_inventory_endpoint_applies_region_scope_to_wms_snapshots():
    tenant, _, ph_store, ph_warehouse = create_scope("inventory-scope")
    th_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=ph_store.platform,
        code="inventory-scope-th",
        name="TH",
        country_code="TH",
        currency="THB",
        timezone="Asia/Bangkok",
    )
    th_warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code="inventory-warehouse-th",
        name="TH",
        country_code="TH",
        warehouse_type="third_party",
    )
    run = create_run(tenant, "inventory_snapshot", "inventory-scope", platform="jifeng_wms")
    for site_code, warehouse, sku in (
        ("PH", ph_warehouse, "WMS-PH"),
        ("TH", th_warehouse, "WMS-TH"),
    ):
        InventorySnapshot.objects.create(
            tenant=tenant,
            site_code=site_code,
            warehouse=warehouse,
            source_run=run,
            source_sku=sku,
            available_qty=1,
            snapshot_at_utc=NOW,
            payload_hash="d" * 64,
        )
    viewer = user_for(tenant, "inventory-scope-viewer")
    grant(
        viewer,
        "sales_management.view",
        DataScope.ScopeType.CUSTOM,
        {"store_ids": [str(ph_store.id)], "regions": ["PH"]},
    )

    response = client_for(viewer).get("/api/internal/commerce/inventory/")

    assert response.status_code == 200
    assert [row["source_sku"] for row in response.json()["data"]["results"]] == ["WMS-PH"]
    assert th_store.country_code == "TH"


@pytest.mark.django_db
def test_formal_analytics_routes_prefer_commerce_facts_when_available():
    tenant, _, store, warehouse = create_scope("analytics-commerce")
    order = create_order(tenant, store, "analytics-commerce", "120.0000")
    inventory_run = create_run(
        tenant,
        "inventory_snapshot",
        "analytics-commerce-inventory",
        platform="jifeng_wms",
    )
    InventorySnapshot.objects.create(
        tenant=tenant,
        site_code="PH",
        warehouse=warehouse,
        source_run=inventory_run,
        source_sku="ANALYTICS-SKU",
        available_qty=7,
        snapshot_at_utc=NOW,
        payload_hash="e" * 64,
    )
    viewer = user_for(tenant, "analytics-commerce-viewer")
    grant(viewer, "analytics.view")

    sales = client_for(viewer).get("/api/internal/analytics/sales/")
    inventory = client_for(viewer).get("/api/internal/analytics/inventory/")

    assert sales.status_code == 200
    assert sales.json()["data"]["dashboard_type"] == "sales"
    assert sales.json()["data"]["results"][0]["store_id"] == store.id
    assert sales.json()["data"]["results"][0]["store_name"] == store.name
    assert [metric["code"] for metric in sales.json()["data"]["summary_metrics"]] == [
        "order_count", "units_sold", "gross_sales", "net_sales"
    ]
    assert sales.json()["data"]["quality"]["metric_version"] == "经营分析 v1"
    assert sales.json()["data"]["count"] == 1
    assert order.external_order_id == "ORDER-analytics-commerce"
    assert inventory.status_code == 200
    assert inventory.json()["data"]["dashboard_type"] == "inventory"
    assert inventory.json()["data"]["results"][0]["source_sku"] == "ANALYTICS-SKU"
    assert inventory.json()["data"]["results"][0]["warehouse_code"] == warehouse.code
    assert len(inventory.json()["data"]["summary_metrics"]) == 6

    filters = client_for(viewer).get("/api/internal/analytics/filters/")
    assert filters.status_code == 200
    assert filters.json()["data"]["stores"][0]["id"] == store.id
    assert filters.json()["data"]["warehouses"][0]["id"] == warehouse.id


@pytest.mark.django_db
def test_quality_applies_store_scope():
    tenant, _, visible_store, _ = create_scope("operational-scope")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=visible_store.platform,
        code="operational-hidden",
        name="Hidden",
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )
    checks = []
    for store, suffix in ((visible_store, "visible"), (hidden_store, "hidden")):
        task = APISyncTask.objects.create(
            tenant=tenant,
            platform="shopee",
            sync_type=APISyncTask.SyncType.SALES_ORDER,
            config={"store_id": str(store.id), "store_code": store.code},
        )
        log = APISyncLog.objects.create(tenant=tenant, task=task, status=APISyncTask.Status.FAILED)
        checks.append(
            APIDataQualityCheck.objects.create(
                tenant=tenant,
                sync_log=log,
                check_type=f"check-{suffix}",
                status=APIDataQualityCheck.Status.FAILED,
            )
        )

    user = user_for(tenant, "operational-viewer")
    scope_config = {"store_ids": [str(visible_store.id)]}
    grant(user, "sales_management.data_quality.view", DataScope.ScopeType.CUSTOM, scope_config)

    quality = client_for(user).get("/api/internal/commerce/quality/")
    assert quality.status_code == 200
    assert [row["id"] for row in quality.json()["data"]["issues"]] == [checks[0].id]
    assert quality.json()["data"]["sources"] == []


@pytest.mark.django_db
def test_sales_export_reuses_report_export_and_audit_model():
    tenant, _, store, _ = create_scope("export")
    create_order(tenant, store, "export")
    user = user_for(tenant, "exporter")
    user.is_superuser = True
    user.is_staff = True
    user.save(update_fields=["is_superuser", "is_staff"])
    response = client_for(user).post(
        "/api/internal/sales-management/exports/",
        {"export_type": "orders", "filters": {"currency": "PHP"}},
        format="json",
    )
    assert response.status_code == 201
    export = ReportExportRequest.objects.get(pk=response.json()["data"]["id"])
    assert export.report_type == ReportExportRequest.ReportType.SALES_DETAILS
    assert export.masked_file_reference.startswith("export://")
    assert export.storage_key
    assert export.file_sha256


@pytest.mark.django_db
def test_sales_export_count_is_limited_to_the_sales_data_scope():
    tenant, platform, visible_store, _ = create_scope("export-scope")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="export-hidden",
        name="Hidden",
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )
    create_order(tenant, visible_store, "export-visible")
    create_order(tenant, hidden_store, "export-hidden")
    user = user_for(tenant, "scoped-exporter")
    grant(
        user,
        "sales_management.export",
        DataScope.ScopeType.CUSTOM,
        {"store_ids": [str(visible_store.id)]},
    )
    grant(
        user,
        "reports.export",
        DataScope.ScopeType.CUSTOM,
        {"report_types": [ReportExportRequest.ReportType.SALES_DETAILS]},
    )

    response = client_for(user).post(
        "/api/internal/sales-management/exports/",
        {
            "filters": {
                "currency": "PHP",
                "date_from": "2026-08-17",
                "date_to": "2026-08-17",
            }
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["data"]["record_count"] == 1


@pytest.mark.django_db
def test_sales_export_permission_is_feature_scoped():
    tenant, _, store, _ = create_scope("export-permission")
    create_order(tenant, store, "export-permission")
    user = user_for(tenant, "sales-export-only")
    grant(
        user,
        "sales_management.export",
        DataScope.ScopeType.CUSTOM,
        {"store_ids": [str(store.id)]},
    )

    client = client_for(user)
    created = client.post(
        "/api/internal/sales-management/exports/",
        {"filters": {"currency": "PHP"}},
        format="json",
    )
    assert created.status_code == 201

    visible = client.get("/api/internal/sales-management/exports/")
    assert visible.status_code == 200
    assert visible.json()["data"]["count"] == 1
    assert visible.json()["data"]["results"][0]["export_type"] == "sales_details"

    # The feature permission cannot be used to create a general report.
    denied_route = client.post(
        "/api/report/exports/",
        {"report_type": "analytics_summary", "filters": {}},
        format="json",
    )
    assert denied_route.status_code == 403
    with pytest.raises(PermissionDenied):
        create_export_request(
            user=user,
            report_type=ReportExportRequest.ReportType.ANALYTICS_SUMMARY,
            filters={},
        )
