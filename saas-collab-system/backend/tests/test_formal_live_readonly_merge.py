from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.commerce.models import InventorySnapshot, RefundReturn, SalesOrder
from apps.commerce.services import upsert_inventory_snapshot
from apps.integrations.adapters import PlatformAdapter
from apps.integrations.inventory_snapshot_contract import normalize_inventory_snapshot_record
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.integrations.readonly_clients import TikTokReadonlyClient
from apps.integrations.refund_return_contract import normalize_refund_return_record
from apps.integrations.sync_services import run_sync_job
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.reports.export_services import _render_sales_export
from apps.sales_management.services import upsert_normalized_order, upsert_normalized_refund
from apps.tenants.models import Tenant


NOW = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)


def _scope(code, platform_type="shopee"):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(username=f"user-{code}", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"{platform_type}-{code}",
        name=platform_type,
        platform_type=platform_type,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name=code,
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code=f"warehouse-{code}",
        name=code,
        country_code="PH",
        warehouse_type="third_party",
    )
    return tenant, user, store, warehouse


def _run(tenant, user, resource_type, platform):
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=f"{platform}-{resource_type}",
        created_by=user,
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type=resource_type)
    run = SyncRun.objects.create(
        tenant=tenant,
        sync_job=job,
        run_id=f"run-{resource_type}",
        idempotency_key=f"key-{resource_type}",
    )
    return job, run


def test_contracts_reject_credentials_and_normalize_sites():
    with pytest.raises(DjangoValidationError):
        normalize_refund_return_record(
            "shopee",
            {"contract_version": "refund_return.v1", "access_token": "forbidden"},
        )
    inventory = normalize_inventory_snapshot_record(
        {
            "contract_version": "inventory_snapshot.v1",
            "site_code": "ph",
            "warehouse_id": "1",
            "source_sku": "SKU-1",
            "snapshot_at_utc": NOW.isoformat(),
            "available_qty": 2,
        }
    )
    assert inventory["site_code"] == "PH"
    assert inventory["available_qty"] == 2


@pytest.mark.django_db
def test_refund_contract_persists_idempotently_to_existing_fact_tables():
    tenant, user, store, _warehouse = _scope("formal-refund")
    _job, run = _run(tenant, user, "refund_return", "shopee")
    payload = normalize_refund_return_record(
        "shopee",
        {
            "contract_version": "refund_return.v1",
            "store_id": store.id,
            "external_return_id": "RET-1",
            "case_type": "refund_only",
            "raw_status": "COMPLETED",
            "normalized_status": "completed",
            "requested_at_utc": NOW.isoformat(),
            "updated_at_utc": NOW.isoformat(),
            "currency": "PHP",
            "refund_amount": "12.3400",
            "items": [
                {
                    "external_return_item_id": "RET-1-1",
                    "seller_sku": "SKU-1",
                    "quantity": 1,
                    "refund_amount": "12.3400",
                }
            ],
        },
    )
    first = upsert_normalized_refund(tenant=tenant, payload=payload, source_run=run)
    second = upsert_normalized_refund(tenant=tenant, payload=payload, source_run=run)
    assert first.pk == second.pk
    assert RefundReturn.objects.filter(tenant=tenant, external_return_id="RET-1").count() == 1
    assert first.items.count() == 1


@pytest.mark.django_db
def test_inventory_contract_persists_idempotently_to_existing_snapshot_table():
    tenant, user, _store, warehouse = _scope("formal-inventory", platform_type="other")
    _job, run = _run(tenant, user, "inventory_snapshot", "jifeng_wms")
    payload = normalize_inventory_snapshot_record(
        {
            "contract_version": "inventory_snapshot.v1",
            "site_code": "PH",
            "warehouse_id": warehouse.id,
            "source_sku": "SKU-1",
            "snapshot_at_utc": NOW.isoformat(),
            "on_hand_qty": 10,
            "available_qty": 8,
            "reserved_qty": 2,
        }
    )
    first = upsert_inventory_snapshot(tenant=tenant, payload=payload, source_run=run)
    second = upsert_inventory_snapshot(tenant=tenant, payload=payload, source_run=run)
    assert first.pk == second.pk
    assert InventorySnapshot.objects.filter(tenant=tenant, source_sku="SKU-1").count() == 1


@pytest.mark.django_db
def test_sales_csv_and_txt_are_real_files_and_csv_formula_values_are_escaped():
    tenant, user, store, _warehouse = _scope("formal-export")
    _job, run = _run(tenant, user, "sales_order", "shopee")
    upsert_normalized_order(
        tenant=tenant,
        source_run=run,
        payload={
            "store_id": store.id,
            "external_order_id": "ORDER-1",
            "created_at_utc": NOW.isoformat(),
            "updated_at_utc": NOW.isoformat(),
            "normalized_status": "completed",
            "raw_status": "COMPLETED",
            "currency": "PHP",
            "order_total_amount": "10.0000",
            "lines": [
                {
                        "external_line_id": "LINE-1",
                        "platform_product_id": "PRODUCT-1",
                        "seller_sku": "=FORMULA",
                    "quantity": 1,
                    "sale_unit_price": "10.0000",
                    "line_total_amount": "10.0000",
                    "currency": "PHP",
                }
            ],
        },
    )
    queryset = SalesOrder.objects.filter(tenant=tenant)
    csv_content = _render_sales_export(queryset, "csv").decode("utf-8")
    txt_content = _render_sales_export(queryset, "txt").decode("utf-8")
    assert "'=FORMULA" in csv_content
    assert '"external_order_id": "ORDER-1"' in txt_content


class _TwoPageAdapter(PlatformAdapter):
    execution_mode = "mock"

    def fetch_page(self, sync_job, cursor_value=None):
        if cursor_value == "page-2":
            return {"records": [{"external_id": "2"}], "next_cursor": ""}
        return {"records": [{"external_id": "1"}], "next_cursor": "page-2"}

    def normalize_record(self, record):
        return record

    def validate_record(self, record):
        return bool(record.get("external_id"))

    def persist_record(self, sync_job, record):
        return {"action": "skipped"}

    def get_next_cursor(self, page):
        return page["next_cursor"]

    def should_continue(self, page, previous_cursor):
        return bool(page["next_cursor"])


@pytest.mark.django_db
def test_sync_service_completes_all_pages_before_success():
    tenant, user, _store, _warehouse = _scope("formal-pages")
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="mock",
        account_alias="pages",
        environment="mock",
        created_by=user,
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type="mock_record")
    run, created = run_sync_job(job, adapter=_TwoPageAdapter(), retry_wait=lambda _delay: None)
    assert created is True
    assert run.status == SyncRun.Status.SUCCESS
    assert run.fetched_count == 2


class _NoCredentialAccess:
    def retrieve_access_token(self, _token_id):
        raise AssertionError("Expired TikTok authorization must not resolve a token.")


@override_settings(
    DEBUG=False,
    PLATFORM_NETWORK_MODE="approved-live-test",
    LIVE_PLATFORM_SECURITY_APPROVED=True,
    LIVE_PLATFORM_ALLOWED_HOSTS=["open-api.example.test"],
    LIVE_CUSTODY_BACKEND="file",
    LIVE_READONLY_SYNC_ENABLED=True,
)
def test_tiktok_expiry_fails_without_implicit_refresh_or_token_resolution(tmp_path):
    config = SimpleNamespace(
        platform="tiktok",
        environment="production",
        status="active",
        network_enabled=True,
        sync_read_enabled=True,
        sync_write_enabled=False,
        platform_config={"contract_approved": True},
    )
    authorization = SimpleNamespace(
        status="active",
        Status=SimpleNamespace(ACTIVE="active"),
        expires_at=NOW - timedelta(seconds=1),
    )
    custody_path = tmp_path / "approved-custody.json"
    with override_settings(CREDENTIAL_CUSTODY_PATH=str(custody_path)):
        client = TikTokReadonlyClient(config, authorization, custody=_NoCredentialAccess(), now=lambda: NOW)
        with pytest.raises(ValidationError, match="TOKEN_EXPIRED_REAUTH_REQUIRED"):
            client._request("/order/202309/orders/search", method="POST", body={})
