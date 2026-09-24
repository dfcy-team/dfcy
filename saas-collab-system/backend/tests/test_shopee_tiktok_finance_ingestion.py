from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.accounts.models import CustomUser
from apps.finance.models import PlatformFinanceTransaction
from apps.integrations.adapters import MarketplaceFinanceTransactionAdapter, get_adapter_for_config
from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.integrations.platform_capabilities import supports_resource
from apps.integrations.readonly_clients import ShopeeReadonlyClient, TikTokReadonlyClient
from apps.integrations.store_authorization_service import authorization_service_write
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


NOW = datetime(2026, 9, 24, 1, 0, tzinfo=UTC)


def test_finance_capability_and_adapter_are_enabled_for_shopee_and_tiktok():
    for platform in ("shopee", "tiktok"):
        assert supports_resource(platform, "settlement_bill", "live_readonly")
        config = SimpleNamespace(platform=platform, environment="production", platform_config={})
        assert isinstance(get_adapter_for_config(config, "settlement_bill"), MarketplaceFinanceTransactionAdapter)


def test_shopee_finance_client_expands_escrow_income_fields():
    client = ShopeeReadonlyClient(SimpleNamespace(platform="shopee", platform_config={}), custody=object())
    client._runtime_path = lambda _key, fallback: fallback
    calls = []

    def request(path, query):
        calls.append((path, query))
        if path.endswith("get_escrow_list"):
            return {
                "response": {
                    "escrow_list": [{"order_sn": "SP-1", "escrow_release_time": 10}],
                    "more": False,
                }
            }
        return {
            "response": {
                "order_sn": "SP-1",
                "order_income": {
                    "currency": "PHP",
                    "escrow_amount": "90.00",
                    "commission_fee": "8.00",
                    "seller_transaction_fee": "2.00",
                },
            }
        }

    client._request = request
    page = client.fetch_finance_transactions("", {"time_from": 1, "time_to": 20, "page_size": 100})
    assert page["next_cursor"] == ""
    assert [(row["fee_name"], row["amount"]) for row in page["records"]] == [
        ("escrow_amount", "90.00"),
        ("commission_fee", "8.00"),
        ("seller_transaction_fee", "2.00"),
    ]
    assert all(row["order_id"] == "SP-1" and row["currency"] == "PHP" for row in page["records"])
    assert all(row["occurred_at"] == 10 for row in page["records"])
    assert calls[0][1]["release_time_from"] == 1


def test_tiktok_finance_client_fetches_current_statement_transactions():
    authorization = SimpleNamespace(shop_cipher="fixture-shop")
    client = TikTokReadonlyClient(
        SimpleNamespace(platform="tiktok", platform_config={}), authorization=authorization, custody=object()
    )
    client._runtime_path = lambda _key, fallback: fallback
    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/statements"):
            return {"code": 0, "data": {"statements": [{"id": "ST-1"}], "next_page_token": ""}}
        return {
            "code": 0,
            "data": {
                "transactions": [{
                    "id": "TX-1", "order_id": "TT-1", "type": "ORDER_SETTLEMENT",
                    "settlement_amount": "75.00", "currency": "PHP", "create_time": 12,
                }],
                "next_page_token": "",
            },
        }

    client._request = request
    page = client.fetch_finance_transactions("", {"time_from": 1, "time_to": 20, "page_size": 100})
    assert page["next_cursor"] == ""
    assert page["records"] == [{
        "source_key": "ST-1:TX-1", "transaction_id": "TX-1", "order_id": "TT-1",
        "order_item_id": "", "seller_sku": "", "platform_variant_id": "",
        "fee_name": "ORDER_SETTLEMENT", "amount": "75.00", "currency": "PHP", "occurred_at": 12,
    }]
    assert calls[0][1]["query"]["statement_time_ge"] == 1
    assert "/finance/202501/statements/ST-1/statement_transactions" in calls[1][0]


def _finance_scope(platform):
    tenant = Tenant.objects.create(name=f"{platform}-finance", code=f"{platform}-finance")
    user = CustomUser.objects.create_user(
        username=f"{platform}-finance-user", tenant=tenant, user_type="internal"
    )
    platform_row = PlatformMaster.objects.create(
        tenant=tenant, code=platform, name=platform, platform_type=platform
    )
    store = StoreMaster.objects.create(
        tenant=tenant, platform=platform_row, code=f"{platform}-store", name=f"{platform} store",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform=platform, account_alias=f"{platform}-finance",
        environment="production", status="verified", created_by=user,
    )
    platform_store_id = f"{platform}-external"
    identity = marketplace_identity_key(platform, "PH", platform_store_id)
    authorization = MarketplaceStoreAuthorization(
        tenant=tenant, integration_config=config, store=store, platform=platform, region="PH",
        platform_store_id=platform_store_id, platform_identity_key=identity,
        active_platform_identity_key=identity,
        active_store_binding_key=marketplace_store_binding_key(tenant.id, platform, store.id),
        merchant_subject_id="merchant", shop_cipher="fixture-shop" if platform == "tiktok" else "",
        credential_id="credential-reference", token_id="token-reference",
        status=MarketplaceStoreAuthorization.Status.ACTIVE, created_by=user, updated_by=user,
    )
    with authorization_service_write():
        authorization.save()
    job = SyncJob.objects.create(
        tenant=tenant, integration_config=config, store_authorization=authorization,
        resource_type=SyncJob.ResourceType.SETTLEMENT_BILL,
    )
    run = SyncRun.objects.create(
        tenant=tenant, sync_job=job, run_id=f"{platform}-finance-run",
        idempotency_key=f"{platform}-finance-run",
    )
    return tenant, store, config, authorization, job, run


@pytest.mark.django_db
@pytest.mark.parametrize("platform", ["shopee", "tiktok"])
def test_shopee_and_tiktok_finance_records_persist_idempotently(platform):
    tenant, store, config, authorization, job, run = _finance_scope(platform)
    adapter = MarketplaceFinanceTransactionAdapter(config)
    adapter.authorization = authorization
    adapter.bind_run(run)
    record = adapter.normalize_record({
        "source_key": f"{platform}-TX-1", "transaction_id": f"{platform}-TX-1",
        "order_id": f"{platform}-ORDER-1", "fee_name": "commission_fee",
        "amount": "3.50", "currency": "PHP", "occurred_at": int(NOW.timestamp()),
    })
    assert adapter.persist_record(job, record)["action"] == "created"
    assert adapter.persist_record(job, record)["action"] == "skipped"
    row = PlatformFinanceTransaction.objects.get(tenant=tenant, store=store)
    assert row.platform == platform
    assert row.fee_code == "COMMISSION"
    assert str(row.signed_amount) == "-3.5000"
