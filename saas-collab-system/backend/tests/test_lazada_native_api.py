from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.integrations import lazada_archive_import as archive
from apps.integrations.automatic_refresh import _refresh_enabled_for_record
from apps.integrations.lazada_api_contract import OPERATIONS, prepare_operation
from apps.integrations.lazada_api_service import execute_operation
from apps.integrations.marketplace_oauth_service import refresh_marketplace_authorization
from apps.integrations.models import MarketplaceStoreAuthorization, PlatformIntegrationConfig, LazadaApiSnapshot, authorization_service_write
from apps.integrations.readonly_clients import LazadaReadonlyClient
from apps.integrations.store_authorization_service import create_store_authorization, transition_store_authorization
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


@pytest.fixture
def context(db):
    tenant = Tenant.objects.create(name="Native Lazada", code="native-lazada")
    actor = CustomUser.objects.create_user(username="native-lazada", tenant=tenant, user_type="internal", is_superuser=True)
    platform = PlatformMaster.objects.create(tenant=tenant, code="lazada", name="Lazada", platform_type="lazada")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="LZ-TEST", name="Test", country_code="PH", currency="PHP")
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="lazada", account_alias="Test", environment="production", status="verified", platform_config={"app_key":"public-test"}, network_enabled=True, sync_read_enabled=True, created_by=actor)
    authorization = create_store_authorization(tenant=tenant, integration_config=config, store=store,
        platform="lazada", region="PH", platform_store_id="123", merchant_subject_id="123", shop_cipher="",
        credential_id="custody-test-old-credential", token_id="custody-test-old-token", allow_live_references=True,
        scopes=[archive.NO_REFRESH], expires_at=timezone.now()+timedelta(days=10), actor=actor)
    authorization = transition_store_authorization(authorization, target_status="active", actor=actor)
    return actor, authorization


@pytest.mark.parametrize("payload", [{"access_token":"not-real"}, {"path":"/product/remove"}, {"app_key":"other"}, {"sign":"not-real"}])
def test_native_contract_cannot_override_auth_or_path(payload):
    with pytest.raises(ValidationError):
        prepare_operation("seller", payload)


def test_only_read_operation_catalog():
    assert len({item.name for item in OPERATIONS}) == len(OPERATIONS)
    assert not any(word in item.path for item in OPERATIONS for word in ("/create", "/update", "/delete", "/refresh", "/sign"))
    with pytest.raises(ValidationError):
        prepare_operation("orders_items", {"order_ids":["1"]*51})
    with pytest.raises(ValidationError):
        prepare_operation("finance", {"start_time":"2026-09-01", "end_time":"2026-09-02", "limit":True})
    with pytest.raises(ValidationError):
        prepare_operation("smax_campaigns", {})


@pytest.mark.parametrize('changes', [
    {'start_time': '2026-09-01'}, {'end_time': '20260931'}, {'start_time': '20261001'},
    {'start_time': 20260901}, {'transaction_type': 'Unknown'}, {'sub_transaction_type': 'Anything'},
    {'transaction_number': ['1']}, {'page_num': True},
])
def test_account_transactions_reject_invalid_dates_and_filters(changes):
    with pytest.raises(ValidationError):
        prepare_operation('account_transactions', {'start_time': '20260901', 'end_time': '20260930',
            'page_num': 1, 'page_size': 20, **changes})


def account_response():
    return {'success': True, 'data': {'page_info': {'page_num': 1, 'page_size': 20,
        'total_count': 1, 'total_page': 1}, 'transactions': [{'transaction_number': 'TX-001',
        'transaction_time': '2026-09-30 12:00:00', 'type': 'Payment',
        'sub_type': 'Sponsored Solutions Top-up', 'amount': '-100.000000', 'currency': 'PHP'}]}}


def test_account_transaction_query_retains_original_money_and_ad_filter(context):
    actor, authorization = context
    client = Mock()
    client._request.return_value = account_response()
    payload = {'start_time': '20260901', 'end_time': '20260930', 'page_num': 1, 'page_size': 20,
               'sub_transaction_type': 'Sponsored Solutions Top-up'}
    result = execute_operation(actor=actor, authorization_id=authorization.pk, name='account_transactions',
                               payload=payload, client=client)
    assert result['status'] == 'succeeded'
    assert result['response']['data']['transactions'][0]['amount'] == '-100.000000'
    client._request.assert_called_once_with('/rest/finance/transaction/accountTransactions/query', payload)


@pytest.mark.parametrize('empty', [True, False])
def test_account_page_accepts_missing_optional_total_page_without_changing_source(context, empty):
    actor, authorization = context
    response = account_response()
    response['data']['page_info'].pop('total_page')
    if empty:
        response['data']['transactions'] = []
        response['data']['page_info']['total_count'] = 0
    client = Mock()
    client._request.return_value = response
    result = execute_operation(actor=actor, authorization_id=authorization.pk, name='account_transactions',
        payload={'start_time': '20260901', 'end_time': '20260930', 'page_num': 1, 'page_size': 20}, client=client)
    assert result['status'] == 'succeeded'
    assert 'total_page' not in result['response']['data']['page_info']


@pytest.mark.parametrize('amount,valid', [('-1,234.000000', True), ('+1,000', True),
    ('1,23.4', False), ('NaN', False), ('Infinity', False), ('1e3', False), (12.4, False)])
def test_account_money_accepts_platform_grouping_but_never_rounds_or_accepts_bad_amounts(context, amount, valid):
    actor, authorization = context
    response = account_response()
    response['data']['transactions'][0]['amount'] = amount
    client = Mock()
    client._request.return_value = response
    result = execute_operation(actor=actor, authorization_id=authorization.pk, name='account_transactions',
        payload={'start_time': '20260901', 'end_time': '20260930', 'page_num': 1, 'page_size': 20}, client=client)
    assert (result['status'] == 'succeeded') is valid
    if valid:
        assert result['response']['data']['transactions'][0]['amount'] == amount


@pytest.mark.parametrize('response', [
    {'success': False, 'error_code': 'ACCOUNT_DENIED'}, {'success': True},
    {'success': True, 'data': {'transactions': []}},
])
def test_account_rejection_or_incomplete_page_is_not_empty_success(context, response):
    actor, authorization = context
    client = Mock()
    client._request.return_value = response
    result = execute_operation(actor=actor, authorization_id=authorization.pk, name='account_transactions',
        payload={'start_time': '20260901', 'end_time': '20260930', 'page_num': 1, 'page_size': 20}, client=client)
    assert result['status'] == 'failed'
    assert result['error_code'] == ('ACCOUNT_DENIED' if response.get('success') is False else 'LAZADA_ACCOUNT_RESPONSE_INVALID')


def test_no_refresh_fences(context, monkeypatch):
    actor, authorization = context
    monkeypatch.setattr("apps.integrations.automatic_refresh.get_runtime_platform_config", lambda _: {"auto_refresh_enabled":True})
    assert _refresh_enabled_for_record(authorization) is False
    with pytest.raises(ValidationError, match="禁止"):
        refresh_marketplace_authorization(authorization, actor=actor)


def test_native_read_archives_redacted_response(context):
    actor, authorization = context
    client = Mock()
    client._request.return_value = {"code":"0", "data":{"seller_id":"123"}, "access_token":"synthetic-secret"}
    result = execute_operation(actor=actor, authorization_id=authorization.pk, name="seller", payload={}, client=client)
    assert result["status"] == "succeeded"
    assert "synthetic-secret" not in str(result)
    assert LazadaApiSnapshot.objects.count() == 1
    with pytest.raises(ValueError):
        LazadaApiSnapshot.objects.all().update(status="changed")


def test_failed_read_does_not_persist_signed_exception(context):
    actor, authorization = context
    client = Mock()
    client._request.side_effect = RuntimeError("https://example.test/?access_token=synthetic-secret")
    result = execute_operation(actor=actor, authorization_id=authorization.pk, name="seller", payload={}, client=client)
    assert result["status"] == "failed"
    assert "synthetic-secret" not in str(result)
    assert result["error_code"] == "LAZADA_READ_FAILED"


def test_other_tenant_cannot_query(context):
    actor, authorization = context
    other = Tenant.objects.create(name="Other", code="other-native")
    outsider = CustomUser.objects.create_user(username="other-native", tenant=other, user_type="internal", is_superuser=True)
    client = Mock()
    with pytest.raises(PermissionDenied):
        execute_operation(actor=outsider, authorization_id=authorization.pk, name="seller", payload={}, client=client)
    client._request.assert_not_called()


def test_expired_authorization_never_calls_provider(context):
    actor, authorization = context
    authorization.expires_at = timezone.now()-timedelta(seconds=1)
    with authorization_service_write():
        authorization.save(update_fields=["expires_at"])
    client = Mock()
    with pytest.raises(ValidationError, match="不会刷新"):
        execute_operation(actor=actor, authorization_id=authorization.pk, name="seller", payload={}, client=client)
    client._request.assert_not_called()


def test_product_snapshot_uses_merchant_sku_and_keeps_ids():
    client = LazadaReadonlyClient(SimpleNamespace(platform_config={}), custody=Mock())
    client._request = Mock(return_value={"data":{"total_products":1, "products":[{"item_id":1, "attributes":{"name":"Test"}, "skus":[{"SkuId":2, "SellerSku":"OLD-SKU", "Status":"active"}]}]}})
    result = client.fetch_products("", {"page_size":10})
    assert result["records"][0]["platform_sku"] == "OLD-SKU"
    assert result["records"][0]["platform_variant_id"] == "2"
    assert "new_sku_code" not in result["records"][0]


def test_client_auth_override_fails_before_custody():
    custody = Mock()
    client = LazadaReadonlyClient(SimpleNamespace(platform_config={}), custody=custody)
    with pytest.raises(ValidationError, match="authentication"):
        client._request("/rest/orders/get", {"access_token":"not-real"})
    custody.retrieve_secret.assert_not_called()


def test_product_incremental_filter_is_not_silently_ignored():
    client = LazadaReadonlyClient(SimpleNamespace(platform_config={}), custody=Mock())
    client._request = Mock()
    with pytest.raises(ValidationError, match="完整目录"):
        client.fetch_products("", {"page_size":10, "product_full_sync":False})
    client._request.assert_not_called()


def test_provider_business_failure_is_not_a_success(context):
    actor, authorization = context
    client = Mock()
    client._request.return_value = {"code":"0", "success":False, "result":{"success":False,"error_code":"BAD_ARGUMENT"}}
    result = execute_operation(actor=actor, authorization_id=authorization.pk, name="seller", payload={}, client=client)
    assert result["status"] == "failed"
    assert result["error_code"] == "BAD_ARGUMENT"


def test_archive_preview_and_preserve_no_network(context, monkeypatch):
    actor, authorization = context
    expiry = (timezone.now()+timedelta(days=20)).isoformat()
    source = {"apps":{"app":{"app_key":"public-test", "app_secret":"synthetic-secret"}},
        "stores":{"LZ-TEST":{"country":"ph", "app_profile":"app", "access_token":"synthetic-access", "refresh_token":"synthetic-refresh", "access_token_expires_at":expiry,
        "country_user_info":[{"country":"ph", "seller_id":"123", "user_id":"123"}]}}}
    monkeypatch.setattr(archive, "read_archive", lambda _:source)
    monkeypatch.setattr(archive, "get_runtime_platform_config", lambda _: {"auto_refresh_enabled":False})
    custody = Mock()
    assert archive.import_archive("unused", actor=actor)[0]["action"] == "preview"
    assert archive.import_archive("unused", actor=actor, commit=True, custody=custody)[0]["action"] == "preserved"
    custody.store_secrets.assert_not_called()
    source["stores"]["LZ-TEST"]["country_user_info"][0]["seller_id"] = "wrong"
    with pytest.raises(ValidationError):
        archive.import_archive("unused", actor=actor, commit=True, custody=custody)


def test_archive_expired_token_replaced_without_refresh(context, monkeypatch):
    actor, authorization = context
    previous_refreshed_at = authorization.refreshed_at
    authorization.expires_at = timezone.now()-timedelta(days=1)
    with authorization_service_write():
        authorization.save(update_fields=["expires_at"])
    expiry = (timezone.now()+timedelta(days=20)).isoformat()
    source = {"apps":{"app":{"app_key":"public-test", "app_secret":"synthetic-secret"}},
        "stores":{"LZ-TEST":{"country":"ph", "app_profile":"app", "access_token":"synthetic-access", "refresh_token":"synthetic-refresh", "access_token_expires_at":expiry,
        "country_user_info":[{"country":"ph", "seller_id":"123", "user_id":"123"}]}}}
    monkeypatch.setattr(archive, "read_archive", lambda _:source)
    monkeypatch.setattr(archive, "get_runtime_platform_config", lambda _: {"auto_refresh_enabled":False})
    custody = Mock()
    custody.store_secrets.return_value = {"credential_id":"custody-test-credential", "token_id":"custody-test-token"}
    result = archive.import_archive("unused", actor=actor, commit=True, custody=custody)
    assert result[0]["action"] == "imported"
    authorization.refresh_from_db()
    assert authorization.expires_at.isoformat() == expiry
    assert authorization.refreshed_at == previous_refreshed_at
    assert archive.NO_REFRESH in authorization.scopes
    assert custody.store_secrets.call_count == 1
