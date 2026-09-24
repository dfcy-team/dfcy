from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.finance.ingestion import upsert_finance_transaction
from apps.finance.models import LazadaFinanceWide, PlatformFinanceTransaction
from apps.finance.wide_service import rebuild_lazada_finance_wide
from apps.finance.normalization import normalize_fee
from apps.integrations.adapters import (
    LazadaFinanceTransactionAdapter,
    LazadaOrderAdapter,
    MarketplaceRefundAdapter,
    get_adapter_for_config,
)
from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.integrations.platform_capabilities import supports_resource
from apps.integrations import readonly_clients
from apps.integrations.readonly_clients import LazadaReadonlyClient, _lazada_api_host, default_sync_scope
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.sales_management.services import upsert_normalized_order
from apps.tenants.models import Tenant


NOW = datetime(2026, 9, 21, 2, 0, tzinfo=UTC)


def test_lazada_readonly_capabilities_and_adapters_are_explicit():
    config = SimpleNamespace(platform="lazada", environment="production", platform_config={})

    assert supports_resource("lazada", "sales_order", "live_readonly")
    assert supports_resource("lazada", "refund_return", "live_readonly")
    assert supports_resource("lazada", "settlement_bill", "live_readonly")
    assert isinstance(get_adapter_for_config(config, "sales_order"), LazadaOrderAdapter)
    assert isinstance(get_adapter_for_config(config, "refund_return"), MarketplaceRefundAdapter)
    assert isinstance(get_adapter_for_config(config, "settlement_bill"), LazadaFinanceTransactionAdapter)


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("PH", "https://api.lazada.com.ph"),
        ("MY", "https://api.lazada.com.my"),
        ("SG", "https://api.lazada.sg"),
    ],
)
def test_lazada_readonly_requests_use_the_store_region_host(region, expected):
    assert _lazada_api_host(region, "https://api.lazada.com") == expected


def test_lazada_unknown_region_preserves_the_approved_host():
    assert _lazada_api_host("CB", "https://approved.example.test/") == "https://approved.example.test"


def test_lazada_finance_incremental_scope_starts_at_local_day(monkeypatch):
    monkeypatch.setattr(readonly_clients.timezone, "now", lambda: NOW)
    config = SimpleNamespace(
        platform="lazada",
        platform_config={"sync_scope": {"lookback_days": 2}},
    )

    scope = default_sync_scope(config, resource_type="settlement_bill")

    assert scope["time_from"] == int(datetime(2026, 9, 19, 16, 0, tzinfo=UTC).timestamp())
    assert scope["time_to"] == int(NOW.timestamp())
    assert scope["page_size"] == 500


def test_lazada_finance_uses_local_dates_and_fifteen_day_windows():
    client = LazadaReadonlyClient(
        SimpleNamespace(platform="lazada", platform_config={}),
        SimpleNamespace(store=SimpleNamespace(timezone="Asia/Manila")),
        custody=object(),
    )
    client._runtime_path = lambda _key, fallback: fallback
    queries = []
    client._request = lambda _path, query: queries.append(query) or {"data": []}
    scope = {
        "time_from": int(datetime(2026, 7, 31, 16, 0, tzinfo=UTC).timestamp()),
        "time_to": int(datetime(2026, 8, 31, 15, 59, 59, tzinfo=UTC).timestamp()),
        "page_size": 500,
    }

    first = client.fetch_finance_transactions("", scope)
    second = client.fetch_finance_transactions(first["next_cursor"], scope)
    third = client.fetch_finance_transactions(second["next_cursor"], scope)

    assert queries == [
        {"start_time": "2026-08-01", "end_time": "2026-08-15", "limit": 500, "offset": 0},
        {"start_time": "2026-08-16", "end_time": "2026-08-30", "limit": 500, "offset": 0},
        {"start_time": "2026-08-31", "end_time": "2026-08-31", "limit": 500, "offset": 0},
    ]
    assert third["next_cursor"] == ""


def test_lazada_order_adapter_uses_lazada_fields_not_tiktok_shape():
    adapter = LazadaOrderAdapter(SimpleNamespace(platform="lazada", platform_config={}))
    adapter.authorization = SimpleNamespace(
        store=SimpleNamespace(id=11, currency="MYR"),
        region="MY",
    )

    record = adapter.normalize_record(
        {
            "order_id": "LZ-1001",
            "created_at": "2026-09-21T09:00:00+08:00",
            "updated_at": "2026-09-21T10:00:00+08:00",
            "statuses": ["shipped"],
            "currency": "MYR",
            "price": "42.50",
            "shipping_fee": "3.00",
            "order_items": [
                {
                    "order_item_id": "LZ-LINE-1",
                    "shop_sku": "SELLER-SKU-1",
                    "sku": "PLATFORM-SKU-1",
                    "sku_id": "VARIANT-1",
                    "product_id": "PRODUCT-1",
                    "item_price": "21.25",
                    "quantity": 2,
                    "status": "shipped",
                }
            ],
        }
    )

    assert record["source_order_id"] == "LZ-1001"
    assert record["order_status"] == "fulfilled"
    assert record["lines"][0]["source_line_id"] == "LZ-LINE-1"
    assert record["lines"][0]["platform_product_id"] == "PRODUCT-1"
    assert record["lines"][0]["platform_variant_id"] == "VARIANT-1"
    assert record["lines"][0]["sku"] == "SELLER-SKU-1"


def test_lazada_finance_adapter_localizes_platform_date():
    adapter = LazadaFinanceTransactionAdapter(SimpleNamespace(platform="lazada", platform_config={}))
    adapter.authorization = SimpleNamespace(
        store=SimpleNamespace(id=11, currency="PHP", timezone="Asia/Manila"),
        region="PH",
    )

    record = adapter.normalize_record(
        {
            "transaction_number": "TX-1001",
            "order_no": "LZ-1001",
            "orderItem_no": "LZ-LINE-1",
            "lazada_sku": "VARIANT-1",
            "fee_name": "Commission",
            "amount": "3.50",
            "transaction_date": "16 Sep 2026",
        }
    )

    assert record["external_order_item_id"] == "LZ-LINE-1"
    assert record["platform_variant_id"] == "VARIANT-1"
    assert record["occurred_at_utc"] == "2026-09-15T16:00:00+00:00"

    second = adapter.normalize_record(
        {
            "transaction_number": "TX-1001",
            "order_no": "LZ-1001",
            "orderItem_no": "LZ-LINE-1",
            "fee_name": "Shipping Fee",
            "amount": "1.25",
            "transaction_date": "16 Sep 2026",
        }
    )
    assert second["source_key"] != record["source_key"]


def test_lazada_client_pages_orders_and_fetches_order_items():
    client = LazadaReadonlyClient(
        SimpleNamespace(platform="lazada", platform_config={}),
        SimpleNamespace(),
        custody=object(),
    )
    client._runtime_path = lambda _key, fallback: fallback
    responses = iter(
        [
            {
                "data": {
                    "countTotal": 2,
                    "orders": [{"order_id": "LZ-1001", "created_at": "2026-09-21T09:00:00+08:00"}],
                }
            },
            {"data": [{"order_item_id": "LZ-LINE-1", "sku": "SELLER-SKU-1"}]},
        ]
    )
    client._request = lambda _path, _query: next(responses)

    page = client.fetch_orders(
        "",
        {"time_from": int(NOW.timestamp()), "time_to": int(NOW.timestamp()) + 3600, "page_size": 1},
    )

    assert page["records"][0]["order_items"][0]["order_item_id"] == "LZ-LINE-1"
    assert page["next_cursor"] == "1"
    assert [item["endpoint"] for item in page["raw_responses"]] == [
        "/rest/orders/get",
        "/rest/order/items/get",
    ]


def test_lazada_client_pages_and_filters_reverse_orders():
    client = LazadaReadonlyClient(
        SimpleNamespace(platform="lazada", platform_config={}),
        SimpleNamespace(),
        custody=object(),
    )
    client._runtime_path = lambda _key, fallback: fallback
    client._request = lambda path, query: {
        "code": "0",
        "result": {
            "success": True,
            "page_no": 1,
            "page_size": 1,
            "total": 2,
            "items": [
                {
                    "reverse_order_id": 9001,
                    "reverse_order_lines": [
                        {
                            "reverse_order_line_id": 9101,
                            "return_order_line_gmt_create": int(NOW.timestamp()),
                            "return_order_line_gmt_modified": int(NOW.timestamp()),
                        }
                    ],
                }
            ],
        },
    }

    page = client.fetch_returns(
        "",
        {
            "time_from": int(NOW.timestamp()) - 60,
            "time_to": int(NOW.timestamp()) + 60,
            "page_size": 1,
        },
    )

    assert page["records"][0]["reverse_order_id"] == 9001
    assert page["next_cursor"] == "2"
    assert page["raw_responses"][0]["endpoint"] == "/rest/reverse/getreverseordersforseller"


def test_lazada_refund_adapter_uses_reverse_order_fields():
    adapter = MarketplaceRefundAdapter(SimpleNamespace(platform="lazada", platform_config={}))
    adapter.authorization = SimpleNamespace(
        store=SimpleNamespace(id=11, currency="PHP", timezone="Asia/Manila"),
        region="PH",
    )

    record = adapter.normalize_record(
        {
            "reverse_order_id": 9001,
            "trade_order_id": 8001,
            "request_type": "RETURN",
            "reverse_order_lines": [
                {
                    "reverse_order_line_id": 9101,
                    "trade_order_line_id": 8101,
                    "reverse_status": "REFUND_SUCCESS",
                    "reason_code": 42,
                    "reason_text": "DAMAGED",
                    "refund_amount": 199,
                    "return_order_line_gmt_create": int(NOW.timestamp()),
                    "return_order_line_gmt_modified": int(NOW.timestamp()) + 60,
                    "platform_sku_id": 7001,
                    "product": {"product_id": 6001, "product_sku": "SELLER-SKU-1"},
                }
            ],
        }
    )

    assert record["platform"] == "lazada"
    assert record["external_return_id"] == "9001"
    assert record["external_order_id"] == "8001"
    assert record["raw_status"] == "REFUND_SUCCESS"
    assert record["refund_amount"] == "1.99"
    assert record["requires_physical_return"] is True
    assert record["items"][0]["external_return_item_id"] == "9101"
    assert record["items"][0]["external_order_item_id"] == "8101"
    assert record["items"][0]["platform_product_id"] == "6001"
    assert record["items"][0]["seller_sku"] == "SELLER-SKU-1"
    assert record["items"][0]["refund_amount"] == "1.99"


@pytest.mark.parametrize(
    ("raw_name", "amount", "fee_code", "signed_amount"),
    [
        ("Item Price", "100.00", "ITEM_PRICE", "100.00"),
        ("Commission", "8.50", "COMMISSION", "-8.50"),
        ("Commission Reversal", "8.50", "COMMISSION_REVERSAL", "8.50"),
        ("Refund", "25.00", "REFUND", "-25.00"),
        ("New Provider Fee", "-1.25", "OTHER", "-1.25"),
    ],
)
def test_lazada_fee_normalization_preserves_raw_amount(raw_name, amount, fee_code, signed_amount):
    normalized = normalize_fee(raw_name, amount)

    assert normalized["raw_fee_name"] == raw_name
    assert str(normalized["raw_amount"]) == amount
    assert normalized["fee_code"] == fee_code
    assert str(normalized["signed_amount"]) == signed_amount


def _lazada_scope(code):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(username=f"{code}-user", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"lazada-{code}",
        name="Lazada",
        platform_type="lazada",
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name=code,
        country_code="MY",
        currency="MYR",
        timezone="Asia/Kuala_Lumpur",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="lazada",
        account_alias=code,
        environment="production",
        status="verified",
        created_by=user,
    )
    external_store_id = f"external-{code}"
    identity = marketplace_identity_key("lazada", "MY", external_store_id)
    authorization = MarketplaceStoreAuthorization(
        tenant=tenant,
        integration_config=config,
        store=store,
        platform="lazada",
        region="MY",
        platform_store_id=external_store_id,
        platform_identity_key=identity,
        active_platform_identity_key=identity,
        active_store_binding_key=marketplace_store_binding_key(tenant.id, "lazada", store.id),
        merchant_subject_id="merchant",
        credential_id="credential-reference",
        token_id="token-reference",
        status=MarketplaceStoreAuthorization.Status.ACTIVE,
        created_by=user,
        updated_by=user,
    )
    with authorization_service_write():
        authorization.save()
    return tenant, user, store, config, authorization


def _grant_finance_view(user):
    role = Role.objects.create(tenant=user.tenant, name="Finance Viewer", code=f"finance-view-{user.id}")
    permission, _created = Permission.objects.get_or_create(
        code="finance.view",
        defaults={"name": "View finance", "module": "finance", "action": "view"},
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


@pytest.mark.django_db
def test_finance_transaction_is_idempotent_and_matches_exact_order_line():
    tenant, user, store, config, authorization = _lazada_scope("lazada-finance")
    order_job = SyncJob.objects.create(
        tenant=tenant,
        integration_config=config,
        store_authorization=authorization,
        resource_type=SyncJob.ResourceType.SALES_ORDER,
    )
    order_run = SyncRun.objects.create(
        tenant=tenant,
        sync_job=order_job,
        run_id="order-run",
        idempotency_key="order-run",
    )
    upsert_normalized_order(
        tenant=tenant,
        source_run=order_run,
        payload={
            "store_id": store.id,
            "source_order_id": "LZ-1001",
            "ordered_at": NOW.isoformat(),
            "source_updated_at": NOW.isoformat(),
            "currency": "MYR",
            "gross_amount": "42.50",
            "order_status": "completed",
            "lines": [
                {
                    "source_line_id": "LZ-LINE-1",
                    "sku": "SELLER-SKU-1",
                    "platform_product_id": "PRODUCT-1",
                    "platform_variant_id": "VARIANT-1",
                    "quantity": 2,
                    "unit_price": "21.25",
                }
            ],
        },
    )
    finance_job = SyncJob.objects.create(
        tenant=tenant,
        integration_config=config,
        store_authorization=authorization,
        resource_type=SyncJob.ResourceType.SETTLEMENT_BILL,
    )
    finance_run = SyncRun.objects.create(
        tenant=tenant,
        sync_job=finance_job,
        run_id="finance-run",
        idempotency_key="finance-run",
    )
    payload = {
        "contract_version": "finance_transaction.v1",
        "source_key": "TX-1",
        "external_transaction_id": "TX-1",
        "external_order_id": "LZ-1001",
        "external_order_item_id": "LZ-LINE-1",
        "seller_sku": "SELLER-SKU-1",
        "platform_variant_id": "VARIANT-1",
        "raw_fee_name": "Commission",
        "raw_amount": "3.50",
        "currency": "MYR",
        "occurred_at_utc": NOW.isoformat(),
    }

    first = upsert_finance_transaction(
        tenant=tenant,
        store=store,
        authorization=authorization,
        source_run=finance_run,
        payload=payload,
    )
    second = upsert_finance_transaction(
        tenant=tenant,
        store=store,
        authorization=authorization,
        source_run=finance_run,
        payload=payload,
    )

    assert first.instance.pk == second.instance.pk
    assert first.action == "created"
    assert second.action == "skipped"
    assert first.instance.match_status == PlatformFinanceTransaction.MatchStatus.MATCHED
    assert first.instance.sales_order.external_order_id == "LZ-1001"
    assert first.instance.sales_order_item.external_line_id == "LZ-LINE-1"
    assert first.instance.signed_amount < 0
    assert PlatformFinanceTransaction.objects.filter(tenant=tenant, source_key="TX-1").count() == 1

    _grant_finance_view(user)
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/finance/transactions/", {"currency": "myr", "match_status": "matched"})

    assert response.status_code == 200
    assert response.json()["data"]["pagination"]["total"] == 1
    item = response.json()["data"]["items"][0]
    assert {
        "platform": item["platform"],
        "store_name": item["store_name"],
        "external_order_id": item["external_order_id"],
        "fee_code": item["fee_code"],
        "signed_amount": item["signed_amount"],
        "currency": item["currency"],
        "match_status": item["match_status"],
    } == {
        "platform": "lazada",
        "store_name": store.name,
        "external_order_id": "LZ-1001",
        "fee_code": "COMMISSION",
        "signed_amount": "-3.5000",
        "currency": "MYR",
        "match_status": "matched",
    }

    assert rebuild_lazada_finance_wide(tenant=tenant, store=store) == 1
    wide = LazadaFinanceWide.objects.get(tenant=tenant, store=store)
    assert wide.external_order_item_id == "LZ-LINE-1"
    assert wide.commission == Decimal("-3.5000")
    assert wide.net_income == Decimal("-3.5000")

    response = client.get("/api/finance/lazada-income-wide/", {"currency": "myr", "seller_sku": "SELLER-SKU-1"})
    assert response.status_code == 200
    assert response.json()["data"]["pagination"]["total"] == 1
    assert response.json()["data"]["items"][0]["commission"] == "-3.5000"
