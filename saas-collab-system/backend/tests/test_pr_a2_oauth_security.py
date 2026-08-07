import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.finance.models import (
    FinanceAuditLog,
    PlatformStatement,
    ReconciliationMatch,
    WithdrawalRecord,
)
from apps.integrations.credential_service import RAW_CREDENTIAL_FIELDS
from apps.integrations.marketplace_providers import synthetic_callback_signature
from apps.integrations.models import MarketplaceProductMapping, MarketplaceStoreMapping
from apps.integrations.product_mapping_service import (
    confirm_product_mapping,
    create_product_mapping,
    suggest_product_mapping,
)
from apps.integrations.store_mapping_service import create_store_mapping
from apps.permissions.models import DataScope
from apps.products.models import ProductSKU, ProductSPU
from tests.test_pr_a2_oauth_shopee import START_URL, marketplace_context, start_oauth
from tests.test_pr_a2_store_mapping import client_for, grant, mapping_context


SHOPEE_CALLBACK_URL = "/api/internal/integrations/store-authorizations/oauth/callback/shopee/"
STORE_MAPPINGS_URL = "/api/internal/integrations/store-mappings/"
PRODUCT_MAPPINGS_URL = "/api/internal/integrations/product-mappings/"


def business_row_counts():
    return {
        "statement": PlatformStatement.objects.count(),
        "withdrawal": WithdrawalRecord.objects.count(),
        "reconciliation_match": ReconciliationMatch.objects.count(),
        "finance_audit": FinanceAuditLog.objects.count(),
    }


@pytest.mark.django_db
def test_unauthenticated_requests_are_rejected_on_all_internal_endpoints():
    client = APIClient()
    assert client.post(START_URL, {"platform": "shopee"}, format="json").status_code == 401
    assert client.get("/api/internal/integrations/store-authorizations/").status_code == 401
    assert client.post("/api/internal/integrations/store-authorizations/1/refresh/", {}, format="json").status_code == 401
    assert client.post("/api/internal/integrations/store-authorizations/1/revoke/", {}, format="json").status_code == 401
    assert client.get(STORE_MAPPINGS_URL).status_code == 401
    assert client.post(STORE_MAPPINGS_URL, {}, format="json").status_code == 401
    assert client.get(PRODUCT_MAPPINGS_URL).status_code == 401
    assert client.post(PRODUCT_MAPPINGS_URL, {}, format="json").status_code == 401
    assert client.patch(f"{PRODUCT_MAPPINGS_URL}1/", {"status": "inactive"}, format="json").status_code == 401


@pytest.mark.django_db
def test_external_and_rpa_users_are_forbidden_even_with_permissions():
    tenant, _internal, _store, _config = marketplace_context("sec-user-type")
    for user_type in (CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA):
        user = CustomUser.objects.create_user(
            username=f"user-{user_type}-sec", tenant=tenant, user_type=user_type
        )
        grant(user, "integrations.store.view")
        grant(user, "integrations.store.authorize")
        client = APIClient()
        client.force_authenticate(user=user)
        assert client.get(STORE_MAPPINGS_URL).status_code == 403
        assert client.post(PRODUCT_MAPPINGS_URL, {}, format="json").status_code == 403


@pytest.mark.django_db
def test_permission_without_data_scope_is_forbidden():
    _tenant, user, _store, _config = marketplace_context("sec-no-scope")
    grant(user, "integrations.store.view", scope_type=None)
    response = client_for(user).get(STORE_MAPPINGS_URL)
    assert response.status_code == 403


@pytest.mark.django_db
def test_empty_or_invalid_custom_scopes_are_rejected_with_controlled_codes():
    _tenant, user, _store, _config = marketplace_context("sec-bad-scope")
    grant(user, "integrations.store.view", DataScope.ScopeType.CUSTOM, {})
    missing = client_for(user).get(STORE_MAPPINGS_URL)
    assert missing.status_code == 403
    assert missing.json()["code"] == "DATA_SCOPE_MISSING"

    grant(user, "integrations.store.view", DataScope.ScopeType.CUSTOM, {"store_ids": ["abc"]})
    invalid = client_for(user).get(STORE_MAPPINGS_URL)
    assert invalid.status_code == 403
    assert invalid.json()["code"] == "DATA_SCOPE_INVALID"

    grant(user, "integrations.store.view", DataScope.ScopeType.CUSTOM, {"platforms": ["bigseller"]})
    unsupported = client_for(user).get(STORE_MAPPINGS_URL)
    assert unsupported.status_code == 403
    assert unsupported.json()["code"] == "DATA_SCOPE_INVALID"

    grant(user, "integrations.store.view", DataScope.ScopeType.CUSTOM, {"unknown_key": [1]})
    unknown_key = client_for(user).get(STORE_MAPPINGS_URL)
    assert unknown_key.status_code == 403
    assert unknown_key.json()["code"] == "DATA_SCOPE_INVALID"


@pytest.mark.django_db
def test_every_raw_credential_field_is_rejected_on_write_endpoints():
    tenant, user, store, _config, authorization = mapping_context("sec-raw-fields")
    store_mapping = create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)
    grant(user, "integrations.store.authorize")
    client = client_for(user)

    store_payload = {"store_id": store.id, "authorization_id": authorization.id}
    product_payload = {
        "store_mapping_id": store_mapping.id,
        "platform_product_id": "p-sec",
        "platform_variant_id": "v-sec",
    }
    for field in sorted(RAW_CREDENTIAL_FIELDS):
        response = client.post(STORE_MAPPINGS_URL, {**store_payload, field: "raw-value"}, format="json")
        assert response.status_code == 422, field
        assert response.json()["code"] == "BUSINESS_RULE_VIOLATION"

        response = client.post(PRODUCT_MAPPINGS_URL, {**product_payload, field: "raw-value"}, format="json")
        assert response.status_code == 422, field
        assert response.json()["code"] == "BUSINESS_RULE_VIOLATION"

    assert not MarketplaceStoreMapping.objects.filter(tenant=tenant).exclude(pk=store_mapping.pk).exists()
    assert not MarketplaceProductMapping.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_callback_ignores_login_session_and_requires_valid_state():
    _tenant, user, store, config = marketplace_context("sec-callback-session")
    grant(user, "integrations.store.authorize")
    state = start_oauth(client_for(user), store, config).json()["data"]["state"]

    # A logged-in session gives no advantage without a valid state.
    missing_state = client_for(user).get(
        SHOPEE_CALLBACK_URL, {"code": "c", "shop_id": "s", "sign": synthetic_callback_signature("shopee", code="c", shop_id="s")}
    )
    assert missing_state.status_code == 400
    assert "OAUTH_STATE_INVALID" in missing_state.json()["message"]

    # And a valid state completes anonymously, independent of any session.
    anonymous = APIClient()
    params = {"code": "synthetic-auth-code", "shop_id": "demo-shop-sg", "state": state}
    params["sign"] = synthetic_callback_signature("shopee", **params)
    completed = anonymous.get(SHOPEE_CALLBACK_URL, params)
    assert completed.status_code == 200
    assert completed.json()["data"]["status"] == "active"


@pytest.mark.django_db
def test_mapping_operations_never_write_business_records():
    before = business_row_counts()
    tenant, user, store, _config, authorization = mapping_context("sec-no-biz")
    store_mapping = create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="spu-sec-no-biz", product_name="Sec product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="sku-sec-no-biz")

    mapping = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-biz", platform_variant_id="v-biz",
    )
    mapping = suggest_product_mapping(mapping, actor=user, sku=sku, confidence=88)
    confirm_product_mapping(mapping, actor=user, manually_confirmed=True)

    grant(user, "integrations.store.authorize")
    client = client_for(user)
    assert client.post(
        PRODUCT_MAPPINGS_URL,
        {"store_mapping_id": store_mapping.id, "platform_product_id": "p-biz-2", "platform_variant_id": "v-biz-2"},
        format="json",
    ).status_code == 201
    assert client.patch(
        f"{PRODUCT_MAPPINGS_URL}{mapping.id}/", {"status": "inactive"}, format="json"
    ).status_code == 200

    assert business_row_counts() == before
