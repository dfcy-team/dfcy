import base64
import importlib
import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import migrations
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.common.exceptions import StateConflict
from apps.integrations.models import (
    APIIntegrationConfig,
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
)
from apps.integrations.store_authorization_service import (
    create_store_authorization,
    rotate_store_authorization_references,
    transition_store_authorization,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.api_permissions import (
    IsMarketplaceCredentialRotator,
    IsMarketplaceStoreAuthorizer,
    IsMarketplaceStoreRetryRunner,
    IsMarketplaceStoreRevoker,
    IsMarketplaceStoreSyncRunner,
    IsMarketplaceStoreViewer,
)
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


EXACT_PERMISSION_CLASSES = {
    "integrations.store.view": IsMarketplaceStoreViewer,
    "integrations.store.authorize": IsMarketplaceStoreAuthorizer,
    "integrations.store.revoke": IsMarketplaceStoreRevoker,
    "integrations.store.sync": IsMarketplaceStoreSyncRunner,
    "integrations.store.retry": IsMarketplaceStoreRetryRunner,
    "integrations.credential.rotate": IsMarketplaceCredentialRotator,
}


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, permission_code, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"Role {permission_code} {user.id}",
        code=f"role-{user.id}-{permission_code.replace('.', '-')}",
    )
    role.permissions.add(Permission.objects.get(code=permission_code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    if scope_type:
        DataScope.objects.create(
            tenant=user.tenant,
            role=role,
            scope_type=scope_type,
            config=config or {},
        )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def marketplace_context(code, platform="shopee", user_type=CustomUser.UserType.INTERNAL):
    tenant = Tenant.objects.create(name=f"Tenant {code}", code=code)
    user = create_user(tenant, f"user-{code}", user_type)
    platform_master = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"{platform}-{code}",
        name=f"{platform} demo",
        platform_type=platform,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform_master,
        code=f"store-{code}",
        name=f"Store {code}",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=f"demo-{code}",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.DISABLED,
        created_by=user,
    )
    return tenant, user, store, config


def create_authorization(code, platform="shopee", platform_store_id=None):
    tenant, user, store, config = marketplace_context(code, platform)
    authorization = create_store_authorization(
        tenant=tenant,
        integration_config=config,
        store=store,
        platform=platform,
        region="SG",
        platform_store_id=platform_store_id or f"demo-store-{code}",
        merchant_subject_id=f"demo-merchant-{code}",
        shop_cipher=f"synthetic-shop-cipher-{code}" if platform == "tiktok" else "",
        credential_id=f"synthetic-{code}-credential",
        token_id=f"synthetic-{code}-token",
        scopes=["orders.read", "inventory.read"],
        actor=user,
    )
    return tenant, user, store, config, authorization


@pytest.mark.django_db
def test_store_authorization_validates_tenant_platform_and_tiktok_cipher():
    tenant, user, store, config = marketplace_context("validation", "shopee")
    other = Tenant.objects.create(name="Other", code="validation-other")
    record = MarketplaceStoreAuthorization(
        tenant=other,
        integration_config=config,
        store=store,
        platform="tiktok",
        region="SG",
        platform_store_id="demo-validation",
        platform_identity_key="a" * 64,
        merchant_subject_id="demo-subject",
        credential_id="synthetic-validation-credential",
        token_id="synthetic-validation-token",
        created_by=user,
        updated_by=user,
    )

    with pytest.raises(ValidationError) as exc_info:
        record.full_clean()

    assert {"store", "platform", "integration_config", "shop_cipher"} <= set(exc_info.value.message_dict)


@pytest.mark.django_db
def test_platform_store_identity_is_unique_across_tenants():
    create_authorization("identity-a", platform_store_id="global-demo-store")
    tenant, user, store, config = marketplace_context("identity-b", "shopee")

    with pytest.raises(StateConflict):
        create_store_authorization(
            tenant=tenant,
            integration_config=config,
            store=store,
            platform="shopee",
            region="SG",
            platform_store_id="global-demo-store",
            merchant_subject_id="demo-other-merchant",
            shop_cipher="",
            credential_id="synthetic-identity-b-credential",
            token_id="synthetic-identity-b-token",
            scopes=[],
            actor=user,
        )


@pytest.mark.django_db
def test_status_transitions_require_service_and_revoked_is_terminal():
    _tenant, user, _store, _config, record = create_authorization("state")
    record = transition_store_authorization(
        record,
        target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
        actor=user,
    )
    record.status = MarketplaceStoreAuthorization.Status.REVOKED
    with pytest.raises(ValidationError, match="service layer"):
        record.save()
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreAuthorization.objects.filter(pk=record.pk).update(status="revoked")
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreAuthorization.objects.bulk_create([MarketplaceStoreAuthorization()])

    record.refresh_from_db()
    revoked = transition_store_authorization(
        record,
        target_status=MarketplaceStoreAuthorization.Status.REVOKED,
        actor=user,
    )
    with pytest.raises(StateConflict):
        transition_store_authorization(
            revoked,
            target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
            actor=user,
        )


@pytest.mark.django_db
def test_reference_rotation_increments_version_and_audit_is_append_only():
    _tenant, user, _store, _config, record = create_authorization("rotation")
    rotated = rotate_store_authorization_references(
        record,
        credential_id="synthetic-rotation-credential-v2",
        token_id="synthetic-rotation-token-v2",
        version=2,
        actor=user,
    )
    assert rotated.credential_reference_version == 2
    with pytest.raises(StateConflict):
        rotate_store_authorization_references(
            rotated,
            credential_id="synthetic-rotation-credential-v2b",
            token_id="synthetic-rotation-token-v2b",
            version=2,
            actor=user,
        )

    audit = IntegrationAuditLog.objects.get(store_authorization=record, action="rotate_reference")
    assert audit.masked_detail["credential_id"] == "synthetic-rotation-credential-v2"
    with pytest.raises(ValidationError, match="append-only"):
        audit.save()
    with pytest.raises(ValidationError, match="append-only"):
        IntegrationAuditLog.objects.filter(pk=audit.pk).update(action="changed")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        audit.delete()


@pytest.mark.django_db
def test_read_api_is_paginated_scoped_and_never_returns_reference_ids():
    tenant, user, store, _config, record = create_authorization("read-api")
    grant(
        user,
        "integrations.store.view",
        DataScope.ScopeType.CUSTOM,
        {"platforms": ["shopee"], "store_ids": [store.id]},
    )
    response = client_for(user).get("/api/internal/integrations/store-authorizations/?page=1&page_size=10")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == 1
    assert data["results"][0]["id"] == record.id
    response_text = json.dumps(response.json())
    assert record.credential_id not in response_text
    assert record.token_id not in response_text

    other_tenant, other_user, _other_store, _other_config = marketplace_context("read-api-other", "shopee")
    grant(other_user, "integrations.store.view")
    hidden = client_for(other_user).get(f"/api/internal/integrations/store-authorizations/{record.id}/")
    assert other_tenant.id != tenant.id
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db
@pytest.mark.parametrize("target_code", tuple(EXACT_PERMISSION_CLASSES))
def test_each_exact_action_permission_cannot_be_replaced(target_code):
    tenant = Tenant.objects.create(name=f"Tenant {target_code}", code=target_code.replace(".", "-")[:50])
    user = create_user(tenant, f"user-{target_code.replace('.', '-')}")
    codes = list(EXACT_PERMISSION_CLASSES)
    granted_code = codes[(codes.index(target_code) + 1) % len(codes)]
    grant(user, granted_code)
    request = SimpleNamespace(user=user, method="GET")

    assert EXACT_PERMISSION_CLASSES[target_code]().has_permission(request, None) is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("scope_type", "config", "expected_code"),
    (
        (None, None, "DATA_SCOPE_MISSING"),
        (DataScope.ScopeType.CUSTOM, {}, "DATA_SCOPE_MISSING"),
        (DataScope.ScopeType.CUSTOM, {"unknown": [1]}, "DATA_SCOPE_INVALID"),
        (DataScope.ScopeType.CUSTOM, {"store_ids": []}, "DATA_SCOPE_INVALID"),
        (DataScope.ScopeType.CUSTOM, {"store_ids": ["bad"]}, "DATA_SCOPE_INVALID"),
        (DataScope.ScopeType.CUSTOM, {"platforms": ["mock"]}, "DATA_SCOPE_INVALID"),
    ),
)
def test_missing_empty_unknown_and_invalid_store_scopes_are_denied(scope_type, config, expected_code):
    tenant, user, _store, _integration_config = marketplace_context(f"scope-{expected_code.lower()}-{len(str(config))}")
    grant(user, "integrations.store.view", scope_type, config)

    response = client_for(user).get("/api/internal/integrations/store-authorizations/")

    assert response.status_code == 403
    assert response.json()["code"] == expected_code


@pytest.mark.django_db
def test_cross_tenant_store_scope_is_denied():
    _tenant, user, _store, _config = marketplace_context("scope-owner")
    _other_tenant, _other_user, other_store, _other_config = marketplace_context("scope-foreign")
    grant(user, "integrations.store.view", DataScope.ScopeType.CUSTOM, {"store_ids": [other_store.id]})

    response = client_for(user).get("/api/internal/integrations/store-authorizations/")

    assert response.status_code == 403
    assert response.json()["code"] == "DATA_SCOPE_FORBIDDEN"


@pytest.mark.django_db
def test_unauthed_external_rpa_and_plain_internal_users_are_rejected():
    tenant = Tenant.objects.create(name="Tenant types", code="user-types")
    plain = create_user(tenant, "plain")
    external = create_user(tenant, "external", CustomUser.UserType.EXTERNAL)
    rpa = create_user(tenant, "rpa", CustomUser.UserType.RPA)

    assert APIClient().get("/api/internal/integrations/store-authorizations/").status_code == 401
    assert client_for(plain).get("/api/internal/integrations/store-authorizations/").status_code == 403
    assert client_for(external).get("/api/internal/integrations/store-authorizations/").status_code == 403
    assert client_for(rpa).get("/api/internal/integrations/store-authorizations/").status_code == 403


@pytest.mark.django_db
def test_query_errors_and_empty_state_keep_unified_response():
    tenant, user, _store, _config = marketplace_context("query-contract")
    grant(user, "integrations.store.view")
    client = client_for(user)

    empty = client.get("/api/internal/integrations/store-authorizations/")
    invalid = client.get("/api/internal/integrations/store-authorizations/?unknown=1")
    missing = client.get("/api/internal/integrations/store-authorizations/999999/")

    assert empty.status_code == 200
    assert empty.json()["data"]["results"] == []
    assert invalid.status_code == 400
    assert invalid.json()["success"] is False
    assert missing.status_code == 404
    assert missing.json()["code"] == "RESOURCE_NOT_FOUND"
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()


def test_legacy_credential_migration_converts_only_mock_and_never_outputs_values(capsys):
    module = importlib.import_module("apps.integrations.migrations.0007_alter_apiintegrationconfig_options_and_more")

    class Records(list):
        def all(self):
            return self

        def iterator(self):
            return iter(self)

    class Record(SimpleNamespace):
        def save(self, update_fields):
            self.saved_fields = update_fields

    safe_payload = base64.urlsafe_b64encode(
        json.dumps({"credentials": {"api_key": "not-a-real-demo-value"}}).encode()
    ).decode()
    safe = Record(
        pk=1,
        credential_ciphertext=f"test-only:{safe_payload}",
        credential_id="",
        token_id="",
        credential_mask={},
        credential_reference_version=1,
        credential_key_version="",
        credential_fingerprint="",
    )
    legacy = Record(
        pk=2,
        api_key_encrypted="placeholder-key",
        api_secret_encrypted="mock-secret",
        credential_ref="",
        credential_status="placeholder",
        credential_key_version="",
    )
    safe_apps = SimpleNamespace(
        get_model=lambda app, name: SimpleNamespace(objects=Records([safe] if name == "PlatformIntegrationConfig" else [legacy]))
    )

    module.migrate_synthetic_credential_references(safe_apps, None)

    assert safe.credential_id == "synthetic-legacy-config-1-credential"
    assert legacy.credential_ref == "synthetic-legacy-api-config-2"
    unknown_text = "opaque-unapproved-value"
    unknown_payload = base64.urlsafe_b64encode(json.dumps({"credentials": {"api_key": unknown_text}}).encode()).decode()
    unknown = Record(pk=3, credential_ciphertext=f"test-only:{unknown_payload}")
    blocked_apps = SimpleNamespace(
        get_model=lambda app, name: SimpleNamespace(objects=Records([unknown] if name == "PlatformIntegrationConfig" else []))
    )
    with pytest.raises(RuntimeError) as exc_info:
        module.migrate_synthetic_credential_references(blocked_apps, None)
    captured = capsys.readouterr()
    assert unknown_text not in str(exc_info.value)
    assert unknown_text not in captured.out + captured.err


def test_auth_migration_uses_backend_portable_operations():
    module = importlib.import_module("apps.integrations.migrations.0007_alter_apiintegrationconfig_options_and_more")
    assert not any(isinstance(operation, migrations.RunSQL) for operation in module.Migration.operations)


def test_legacy_config_has_no_persistent_secret_fields():
    field_names = {field.name for field in APIIntegrationConfig._meta.fields}
    assert APIIntegrationConfig.is_legacy is True
    assert {"api_key_encrypted", "api_secret_encrypted"}.isdisjoint(field_names)
    platform_fields = {field.name for field in PlatformIntegrationConfig._meta.fields}
    assert "credential_ciphertext" not in platform_fields
