import base64
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import threading
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import apps.integrations.oauth_services as oauth_services_module
import apps.integrations.store_authorization_service as store_authorization_module
import apps.integrations.views as oauth_views_module
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, migrations, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.common.exceptions import StateConflict
from apps.integrations.models import (
    APIIntegrationConfig,
    IntegrationAuditLog,
    MarketplaceOAuthAction,
    MarketplaceOAuthOperation,
    MarketplaceOAuthResourceLease,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    marketplace_identity_key,
)
from apps.integrations.admin import MarketplaceStoreAuthorizationAdmin, PlatformIntegrationConfigAdmin
from apps.integrations.credential_service import rotate_config_references
from apps.integrations.oauth_adapters import OAuthAdapterError, synthetic_callback_signature
from apps.integrations.models import MarketplaceOAuthAttempt, oauth_lease_write, oauth_service_write
from apps.integrations.oauth_services import (
    _update_operation,
    begin_oauth_action,
    claim_oauth_action,
    claim_oauth_operation,
    complete_oauth_action,
    fail_oauth_action,
    recover_oauth_operation,
)
from apps.integrations.store_authorization_service import (
    assert_operation_fence,
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


def oauth_service_request(path, key, body=None, session_key="test-oauth-session"):
    return SimpleNamespace(
        method="POST",
        path=path,
        headers={"Idempotency-Key": key},
        session=SimpleNamespace(session_key=session_key, create=lambda: None),
        data=body or {},
    )


def expire_oauth_claim(action):
    expired_at = timezone.now() - timedelta(seconds=1)
    with oauth_service_write():
        MarketplaceOAuthAction.objects.filter(pk=action.pk).update(lease_expires_at=expired_at)
        MarketplaceOAuthOperation.objects.filter(operation_id_hash=action.operation_id_hash).update(
            lease_expires_at=expired_at
        )
    with oauth_lease_write():
        MarketplaceOAuthResourceLease.objects.filter(
            tenant=action.tenant,
            object_type=action.object_type,
            object_id=action.object_id,
        ).update(lease_expires_at=expired_at)


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, permission_code, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"Role {permission_code} {user.id}",
        code=f"role-{user.id}-{permission_code.replace('.', '-')}",
    )
    permission, _created = Permission.objects.get_or_create(
        code=permission_code,
        defaults={
            "name": permission_code,
            "module": permission_code.split(".")[0],
            "action": permission_code.rsplit(".", 1)[-1],
        },
    )
    role.permissions.add(permission)
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
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketplaceStoreAuthorization.objects.filter(pk=record.pk).delete()

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
def test_all_store_authorization_write_bypasses_are_blocked_without_audit():
    tenant, user, store, config, record = create_authorization("write-guards")
    other_tenant = Tenant.objects.create(name="Other tenant", code="write-guards-other")
    other_user = create_user(other_tenant, "write-guards-other-user")
    audit_count = IntegrationAuditLog.objects.count()
    direct = MarketplaceStoreAuthorization(
        tenant=tenant,
        integration_config=config,
        store=store,
        platform="shopee",
        region="SG",
        platform_store_id="direct-demo-store",
        platform_identity_key=marketplace_identity_key("shopee", "SG", "direct-demo-store"),
        merchant_subject_id="direct-demo-subject",
        credential_id="synthetic-direct-demo-credential",
        token_id="synthetic-direct-demo-token",
        created_by=user,
        updated_by=user,
    )
    with pytest.raises(ValidationError, match="created by the service layer"):
        direct.save()
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreAuthorization.objects.filter(pk=record.pk).update(tenant_id=other_tenant.id)
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreAuthorization.objects.filter(pk=record.pk).update(platform_store_id="changed")

    record.region = "MY"
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreAuthorization.objects.bulk_update([record], ["region"])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketplaceStoreAuthorization.objects.filter(pk=record.pk).delete()
    with pytest.raises(ValidationError, match="actor"):
        transition_store_authorization(
            record,
            target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
            actor=other_user,
        )
    with pytest.raises(ValidationError, match="actor"):
        rotate_config_references(
            config,
            credential_id="synthetic-cross-tenant-config-credential",
            token_id="synthetic-cross-tenant-config-token",
            version=2,
            actor=other_user,
        )

    record.refresh_from_db()
    assert record.tenant_id == tenant.id
    assert record.region == "SG"
    assert IntegrationAuditLog.objects.count() == audit_count


@pytest.mark.django_db
def test_identity_key_config_reference_and_admin_bypasses_are_blocked():
    tenant, user, store, config = marketplace_context("identity-guard")
    invalid = MarketplaceStoreAuthorization(
        tenant=tenant,
        integration_config=config,
        store=store,
        platform="shopee",
        region="SG",
        platform_store_id="identity-guard-store",
        platform_identity_key="0" * 64,
        merchant_subject_id="identity-guard-subject",
        credential_id="synthetic-identity-guard-credential",
        token_id="synthetic-identity-guard-token",
        created_by=user,
        updated_by=user,
    )
    with pytest.raises(ValidationError) as exc_info:
        invalid.full_clean()
    assert "platform_identity_key" in exc_info.value.message_dict

    config.credential_id = "synthetic-config-direct-credential"
    with pytest.raises(ValidationError, match="rotation service"):
        config.save()
    with pytest.raises(ValidationError, match="rotation service"):
        PlatformIntegrationConfig.objects.filter(pk=config.pk).update(
            token_id="synthetic-config-direct-token"
        )
    config.refresh_from_db()
    config.credential_reference_version = 2
    with pytest.raises(ValidationError, match="rotation service"):
        PlatformIntegrationConfig.objects.bulk_update(
            [config],
            ["credential_reference_version"],
        )
    with pytest.raises(ValidationError, match="rotation service"):
        PlatformIntegrationConfig.objects.bulk_create(
            [
                PlatformIntegrationConfig(
                    tenant=tenant,
                    platform="mock",
                    account_alias="direct-reference",
                    credential_id="synthetic-config-bulk-credential",
                    token_id="synthetic-config-bulk-token",
                    created_by=user,
                )
            ]
        )

    assert set(PlatformIntegrationConfigAdmin.readonly_fields) >= {
        "credential_id",
        "token_id",
        "credential_reference_version",
    }
    assert MarketplaceStoreAuthorizationAdmin.has_add_permission(None, None) is False
    assert MarketplaceStoreAuthorizationAdmin.has_change_permission(None, None) is False
    assert MarketplaceStoreAuthorizationAdmin.has_delete_permission(None, None) is False


@pytest.mark.django_db
def test_error_transition_requires_controlled_error_code():
    _tenant, user, _store, _config, record = create_authorization("error-code")
    for error_code in ("", "lowercase", "BAD-CODE"):
        with pytest.raises(ValidationError):
            transition_store_authorization(
                record,
                target_status=MarketplaceStoreAuthorization.Status.ERROR,
                actor=user,
                error_code=error_code,
            )

    failed = transition_store_authorization(
        record,
        target_status=MarketplaceStoreAuthorization.Status.ERROR,
        actor=user,
        error_code="AUTH_EXPIRED",
    )
    assert failed.last_error_code == "AUTH_EXPIRED"


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
    assert audit.masked_detail["previous_reference"]["credential_id"] == "synthetic-rotation-credential"
    assert audit.masked_detail["previous_reference"]["reference_version"] == 1
    assert audit.masked_detail["new_reference"]["reference_version"] == 2
    assert audit.masked_detail["revocation"] == {"status": "revoked", "error_code": ""}
    with pytest.raises(ValidationError, match="append-only"):
        audit.save()
    with pytest.raises(ValidationError, match="append-only"):
        IntegrationAuditLog.objects.filter(pk=audit.pk).update(action="changed")
    with pytest.raises(ValidationError, match="cannot be deleted"):
        audit.delete()


@pytest.mark.django_db
def test_reference_revocation_failure_preserves_old_reference_and_is_audited():
    _tenant, user, _store, _config, record = create_authorization("revoke-failure")

    def failing_revoker(_credential_id, _token_id):
        return {"status": "failed", "error_code": "CUSTODY_UNAVAILABLE"}

    with pytest.raises(StateConflict, match="could not be revoked"):
        rotate_store_authorization_references(
            record,
            credential_id="synthetic-revoke-failure-credential-v2",
            token_id="synthetic-revoke-failure-token-v2",
            version=2,
            actor=user,
            revoker=failing_revoker,
        )

    record.refresh_from_db()
    assert record.credential_id == "synthetic-revoke-failure-credential"
    assert record.credential_reference_version == 1
    audit = IntegrationAuditLog.objects.get(store_authorization=record, action="rotate_reference")
    assert audit.result == IntegrationAuditLog.Result.FAILED
    assert audit.masked_detail["revocation"] == {
        "status": "failed",
        "error_code": "CUSTODY_UNAVAILABLE",
    }
    audit_text = json.dumps(audit.masked_detail)
    assert record.merchant_subject_id not in audit_text
    assert "shop_cipher" not in audit_text

    with pytest.raises(StateConflict):
        rotate_store_authorization_references(
            record,
            credential_id="synthetic-revoke-failure-credential-v2",
            token_id="synthetic-revoke-failure-token-v2",
            version=2,
            actor=user,
            revoker=lambda _credential_id, _token_id: "unexpected-result",
        )
    non_dict_audit = IntegrationAuditLog.objects.filter(
        store_authorization=record,
        action="rotate_reference",
        result=IntegrationAuditLog.Result.FAILED,
    ).latest("id")
    assert non_dict_audit.masked_detail["revocation"]["error_code"] == "REFERENCE_REVOCATION_FAILED"


@pytest.mark.django_db
def test_config_rotation_revokes_previous_reference_and_failure_keeps_current_version():
    _tenant, user, _store, config = marketplace_context("config-rotation")
    config = rotate_config_references(
        config,
        credential_id="synthetic-config-rotation-credential-v2",
        token_id="synthetic-config-rotation-token-v2",
        version=2,
        actor=user,
    )
    rotated = rotate_config_references(
        config,
        credential_id="synthetic-config-rotation-credential-v3",
        token_id="synthetic-config-rotation-token-v3",
        version=3,
        actor=user,
    )
    audit = IntegrationAuditLog.objects.filter(
        integration_config=config,
        action="rotate_config_reference",
        result=IntegrationAuditLog.Result.SUCCESS,
    ).first()
    assert audit.masked_detail["previous_reference"]["reference_version"] == 2
    assert audit.masked_detail["new_reference"]["reference_version"] == 3
    assert audit.masked_detail["revocation"]["status"] == "revoked"

    def failing_revoker(_credential_id, _token_id):
        return {"status": "failed", "error_code": "CUSTODY_UNAVAILABLE"}

    with pytest.raises(StateConflict):
        rotate_config_references(
            rotated,
            credential_id="synthetic-config-rotation-credential-v4",
            token_id="synthetic-config-rotation-token-v4",
            version=4,
            actor=user,
            revoker=failing_revoker,
        )
    rotated.refresh_from_db()
    assert rotated.credential_reference_version == 3
    failed_audit = IntegrationAuditLog.objects.get(
        integration_config=config,
        action="rotate_config_reference",
        result=IntegrationAuditLog.Result.FAILED,
    )
    assert failed_audit.masked_detail["revocation"]["error_code"] == "CUSTODY_UNAVAILABLE"


@pytest.mark.django_db(transaction=True)
def test_concurrent_store_reference_rotation_serializes_on_mysql():
    if connection.vendor != "mysql":
        pytest.skip("MySQL row-lock verification runs in Local Sandbox.")
    _tenant, user, _store, _config, record = create_authorization("concurrent-rotation")
    start = threading.Event()

    def rotate(suffix):
        close_old_connections()
        start.wait(timeout=5)
        try:
            current = MarketplaceStoreAuthorization.objects.get(pk=record.pk)
            actor = CustomUser.objects.get(pk=user.pk)
            rotate_store_authorization_references(
                current,
                credential_id=f"synthetic-concurrent-rotation-credential-{suffix}",
                token_id=f"synthetic-concurrent-rotation-token-{suffix}",
                version=2,
                actor=actor,
            )
            return "success"
        except StateConflict:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(rotate, suffix) for suffix in ("a", "b")]
        start.set()
        results = [future.result(timeout=15) for future in futures]

    assert sorted(results) == ["conflict", "success"]
    record.refresh_from_db()
    assert record.credential_reference_version == 2


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
    assert record.merchant_subject_id not in response_text
    assert "shop_cipher" not in response_text

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


def test_legacy_credential_migration_preflights_all_rows_before_writing(capsys):
    module = importlib.import_module("apps.integrations.migrations.0007_alter_apiintegrationconfig_options_and_more")

    class Records(list):
        def all(self):
            return self

        def iterator(self):
            return iter(self)

    class Record(SimpleNamespace):
        def save(self, update_fields):
            self.saved_fields = update_fields
            self.save_count = getattr(self, "save_count", 0) + 1

    safe_payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "migration_provenance": "approved_mock_fixture_v1",
                "credentials": {"api_key": "opaque-fixture-value"},
            }
        ).encode()
    ).decode()
    safe = Record(
        pk=1,
        platform="mock",
        environment="mock",
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
        platform="mock",
        environment="mock",
        api_base_url="https://api.example.test/v1/",
        api_key_encrypted="opaque-fixture-key",
        api_secret_encrypted="opaque-fixture-secret",
        credential_ref="",
        credential_status="placeholder",
        credential_key_version="",
    )
    safe_apps = SimpleNamespace(
        get_model=lambda app, name: SimpleNamespace(objects=Records([safe] if name == "PlatformIntegrationConfig" else [legacy]))
    )

    false_positive_payload = base64.urlsafe_b64encode(
        json.dumps({"credentials": {"api_key": "live-example-credential"}}).encode()
    ).decode()
    unknown = Record(
        pk=3,
        platform="mock",
        environment="mock",
        credential_ciphertext=f"test-only:{false_positive_payload}",
    )
    blocked_apps = SimpleNamespace(
        get_model=lambda app, name: SimpleNamespace(
            objects=Records([safe, unknown] if name == "PlatformIntegrationConfig" else [legacy])
        )
    )
    with pytest.raises(RuntimeError) as exc_info:
        module.migrate_synthetic_credential_references(blocked_apps, None)
    assert not hasattr(safe, "saved_fields")
    assert not hasattr(legacy, "saved_fields")

    unknown.credential_ciphertext = f"test-only:{safe_payload}"
    module.migrate_synthetic_credential_references(blocked_apps, None)
    assert safe.credential_id == "synthetic-legacy-config-1-credential"
    assert legacy.credential_ref == "synthetic-legacy-api-config-2"
    assert unknown.credential_id == "synthetic-legacy-config-3-credential"
    captured = capsys.readouterr()
    assert "live-example-credential" not in str(exc_info.value)
    assert "live-example-credential" not in captured.out + captured.err


def test_auth_migration_uses_backend_portable_operations():
    module = importlib.import_module("apps.integrations.migrations.0007_alter_apiintegrationconfig_options_and_more")
    assert not any(isinstance(operation, migrations.RunSQL) for operation in module.Migration.operations)

    data_migration = importlib.import_module(
        "apps.integrations.migrations.0008_migrate_legacy_credential_references"
    )
    drop_migration = importlib.import_module(
        "apps.integrations.migrations.0009_remove_legacy_credential_columns"
    )
    assert data_migration.Migration.atomic is False
    assert any(isinstance(operation, migrations.RunPython) for operation in data_migration.Migration.operations)
    assert any(
        isinstance(operation, migrations.SeparateDatabaseAndState)
        for operation in drop_migration.Migration.operations
    )


def test_legacy_column_preflight_accepts_absent_columns_and_rejects_partial_schema():
    module = importlib.import_module("apps.integrations.migrations.0007_alter_apiintegrationconfig_options_and_more")

    class Introspection:
        def __init__(self, columns):
            self.columns = columns

        def get_table_description(self, _cursor, table_name):
            return [SimpleNamespace(name=name) for name in self.columns.get(table_name, set())]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def schema_editor(columns):
        return SimpleNamespace(
            connection=SimpleNamespace(
                cursor=lambda: Cursor(),
                introspection=Introspection(columns),
            )
        )

    assert module._legacy_columns_available(schema_editor({})) is False
    with pytest.raises(RuntimeError, match="partially present"):
        module._legacy_columns_available(
            schema_editor({"integrations_platformintegrationconfig": {"credential_ciphertext"}})
        )


def test_legacy_config_has_no_persistent_secret_fields():
    field_names = {field.name for field in APIIntegrationConfig._meta.fields}
    assert APIIntegrationConfig.is_legacy is True
    assert {"api_key_encrypted", "api_secret_encrypted"}.isdisjoint(field_names)
    platform_fields = {field.name for field in PlatformIntegrationConfig._meta.fields}
    assert "credential_ciphertext" not in platform_fields


def test_global_oauth_idempotency_migration_preflights_before_writing():
    module = importlib.import_module(
        "apps.integrations.migrations.0013_marketplaceoauthresourcelease_and_more"
    )

    class DuplicateQuery:
        def values(self, *_args):
            return self

        def annotate(self, **_kwargs):
            return self

        def filter(self, **_kwargs):
            return self

        def exists(self):
            return True

    fake_model = SimpleNamespace(objects=DuplicateQuery())
    fake_apps = SimpleNamespace(get_model=lambda *_args: fake_model)
    with pytest.raises(RuntimeError, match="duplicates must be reconciled"):
        module.preflight_global_idempotency_key(fake_apps, None)


def oauth_scope_payload(config=None):
    return config or {"platforms": ["shopee", "tiktok"], "store_ids": [1]}


def oauth_initiate_payload(store, config):
    return {
        "integration_config_id": config.id,
        "store_id": store.id,
        "platform": config.platform,
        "region": "SG",
        "redirect_target_code": "integrations",
    }


@pytest.mark.django_db
def test_synthetic_oauth_success_is_one_time_and_stores_only_hashes():
    tenant, user, store, config = marketplace_context("oauth-success", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    payload = {
        "integration_config_id": config.id,
        "store_id": store.id,
        "platform": "shopee",
        "region": "SG",
        "redirect_target_code": "integrations",
    }
    initiated = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-idempotency-001",
    )
    assert initiated.status_code == 201
    data = initiated.json()["data"]
    assert data["api_status"] == "mock"
    assert "state" not in data
    assert "credential" not in json.dumps(data).lower()
    attempt = MarketplaceOAuthAttempt.objects.get(pk=data["attempt_id"])
    authorization_url = data["authorization_url"]
    parsed = parse_qs(urlparse(authorization_url).query)
    state = parsed["state"][0]
    callback_code = "synthetic-code-success-001"
    store_id = f"synthetic-store-{store.id}"
    signature = synthetic_callback_signature("shopee", state, callback_code, store_id)

    callback = client.get(
        "/api/platform/oauth/shopee/callback/",
        {"state": state, "code": callback_code, "platform_store_id": store_id, "signature": signature},
    )
    assert callback.status_code == 302
    assert "oauth_result=success" in callback["Location"]
    attempt.refresh_from_db()
    assert attempt.status == MarketplaceOAuthAttempt.Status.SUCCEEDED
    authorization = MarketplaceStoreAuthorization.objects.get(tenant=tenant, store=store)
    assert authorization.status == MarketplaceStoreAuthorization.Status.ACTIVE
    assert callback_code not in json.dumps(list(MarketplaceOAuthAttempt.objects.values()), default=str)
    assert callback_code not in json.dumps(list(IntegrationAuditLog.objects.values()), default=str)
    assert attempt.state_hash != state

    replay = client.get(
        "/api/platform/oauth/shopee/callback/",
        {"state": state, "code": callback_code, "platform_store_id": store_id, "signature": signature},
    )
    assert replay.status_code == 409
    assert replay.json()["code"] == "OAUTH_STATE_CONSUMED"


@pytest.mark.django_db
def test_oauth_idempotency_same_request_replays_and_changed_request_conflicts():
    _tenant, user, store, config = marketplace_context("oauth-idempotency", "tiktok")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    payload = {
        "integration_config_id": config.id,
        "store_id": store.id,
        "platform": "tiktok",
        "region": "SG",
        "redirect_target_code": "integrations",
    }
    headers = {"HTTP_IDEMPOTENCY_KEY": "oauth-idempotency-002"}
    first = client.post("/api/internal/integrations/store-authorizations/oauth/initiate/", payload, format="json", **headers)
    second = client.post("/api/internal/integrations/store-authorizations/oauth/initiate/", payload, format="json", **headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["attempt_id"] == first.json()["data"]["attempt_id"]
    changed = {**payload, "region": "MY"}
    conflict = client.post("/api/internal/integrations/store-authorizations/oauth/initiate/", changed, format="json", **headers)
    assert conflict.status_code == 409


@pytest.mark.django_db
def test_oauth_callback_rejects_signature_store_and_unknown_field_without_leaking_input():
    _tenant, user, store, config = marketplace_context("oauth-negative", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    payload = {
        "integration_config_id": config.id,
        "store_id": store.id,
        "platform": "shopee",
        "region": "SG",
        "redirect_target_code": "integrations",
    }
    initiated = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-idempotency-003",
    )
    parsed = parse_qs(urlparse(initiated.json()["data"]["authorization_url"]).query)
    state = parsed["state"][0]
    bad_signature = client.get(
        "/api/platform/oauth/shopee/callback/",
        {"state": state, "code": "synthetic-code-canary", "platform_store_id": f"synthetic-store-{store.id}", "signature": "bad"},
    )
    assert bad_signature.status_code == 302
    assert "OAUTH_SIGNATURE_INVALID" in bad_signature["Location"]
    assert not MarketplaceStoreAuthorization.objects.exists()

    # A second attempt proves wrong-store and unknown callback fields are not accepted.
    initiated_two = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-idempotency-004",
    )
    parsed_two = parse_qs(urlparse(initiated_two.json()["data"]["authorization_url"]).query)
    state_two = parsed_two["state"][0]
    code_two = "synthetic-code-canary-two"
    store_id_two = f"synthetic-store-{store.id}"
    signature_two = synthetic_callback_signature("shopee", state_two, code_two, store_id_two)
    unknown = client.get(
        "/api/platform/oauth/shopee/callback/",
        {"state": state_two, "code": code_two, "platform_store_id": store_id_two, "signature": signature_two, "redirect": "https://evil.invalid"},
    )
    assert unknown.status_code == 302
    assert "OAUTH_CALLBACK_INVALID" in unknown["Location"]
    assert "evil.invalid" not in unknown["Location"]


@pytest.mark.django_db
def test_oauth_cross_tenant_session_replay_and_exact_permission_are_denied():
    tenant, user, store, config = marketplace_context("oauth-tenant-a", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    other_tenant, other_user, _other_store, _other_config = marketplace_context("oauth-tenant-b", "shopee")
    grant(other_user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    payload = {"integration_config_id": config.id, "store_id": store.id, "platform": "shopee", "region": "SG", "redirect_target_code": "integrations"}
    initiated = client.post("/api/internal/integrations/store-authorizations/oauth/initiate/", payload, format="json", HTTP_IDEMPOTENCY_KEY="oauth-idempotency-005")
    parsed = parse_qs(urlparse(initiated.json()["data"]["authorization_url"]).query)
    state = parsed["state"][0]
    code = "synthetic-code-cross-tenant"
    store_id = f"synthetic-store-{store.id}"
    signature = synthetic_callback_signature("shopee", state, code, store_id)
    other_client = client_for(other_user)
    operation_count = MarketplaceOAuthOperation.objects.count()
    audit_count = IntegrationAuditLog.objects.count()
    replay = other_client.get("/api/platform/oauth/shopee/callback/", {"state": state, "code": code, "platform_store_id": store_id, "signature": signature})
    assert replay.status_code == 422
    attempt = MarketplaceOAuthAttempt.objects.get(pk=initiated.json()["data"]["attempt_id"])
    assert attempt.status == MarketplaceOAuthAttempt.Status.INITIATED
    assert attempt.consumed_at is None
    assert MarketplaceOAuthOperation.objects.count() == operation_count
    assert IntegrationAuditLog.objects.count() == audit_count
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=other_tenant).exists()
    valid = client.get("/api/platform/oauth/shopee/callback/", {"state": state, "code": code, "platform_store_id": store_id, "signature": signature})
    assert valid.status_code == 302
    assert "oauth_result=success" in valid["Location"]
    assert MarketplaceStoreAuthorization.objects.filter(tenant=tenant).count() == 1
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=other_tenant).exists()


@pytest.mark.django_db
def test_oauth_refresh_and_revoke_use_exact_actions_and_idempotency():
    tenant, user, store, config, authorization = create_authorization("oauth-actions")
    grant(user, "integrations.credential.rotate", DataScope.ScopeType.ALL)
    grant(user, "integrations.store.revoke", DataScope.ScopeType.ALL)
    client = client_for(user)

    refreshed = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-refresh-key-001",
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["api_status"] == "mock"
    authorization.refresh_from_db()
    assert authorization.credential_reference_version == 2

    replay = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-refresh-key-001",
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["credential_reference_version"] == 2

    revoked = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/revoke/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-revoke-key-001",
    )
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "revoked"
    assert IntegrationAuditLog.objects.filter(action="oauth_refresh").exists()
    assert IntegrationAuditLog.objects.filter(action="oauth_revoke").exists()


@pytest.mark.django_db
def test_oauth_action_scope_does_not_share_state_and_expired_callback_is_persisted():
    tenant, user, store, config = marketplace_context("oauth-action-scope", "shopee")
    other_user = create_user(tenant, "oauth-action-scope-other")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    grant(other_user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    payload = {
        "integration_config_id": config.id,
        "store_id": store.id,
        "platform": "shopee",
        "region": "SG",
        "redirect_target_code": "integrations",
    }
    user_client = client_for(user)
    first = user_client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="same-key-for-two-users",
    )
    second = client_for(other_user).post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="same-key-for-two-users",
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["attempt_id"] != second.json()["data"]["attempt_id"]
    assert all("authorization_url" not in action.response_data for action in MarketplaceOAuthAction.objects.all())

    attempt = MarketplaceOAuthAttempt.objects.get(pk=first.json()["data"]["attempt_id"])
    with oauth_service_write():
        MarketplaceOAuthAttempt.objects.filter(pk=attempt.pk).update(
            expires_at=attempt.created_at,
        )
    state = parse_qs(urlparse(first.json()["data"]["authorization_url"]).query)["state"][0]
    expired = user_client.get(
        "/api/platform/oauth/shopee/callback/",
        {"state": state, "code": "synthetic-code-expired", "platform_store_id": f"synthetic-store-{store.id}", "signature": synthetic_callback_signature("shopee", state, "synthetic-code-expired", f"synthetic-store-{store.id}")},
    )
    assert expired.status_code == 302
    attempt.refresh_from_db()
    assert attempt.status == MarketplaceOAuthAttempt.Status.EXPIRED
    assert attempt.consumed_at is not None


@pytest.mark.django_db
def test_oauth_revoke_failure_blocks_usage_and_records_reconciliation_operation():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-reconcile")
    grant(user, "integrations.store.revoke", DataScope.ScopeType.ALL)
    response = client_for(user).post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/revoke/",
        {"scenario": "custody-fail"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-reconcile-key-001",
    )
    assert response.status_code == 503
    authorization.refresh_from_db()
    assert authorization.status == MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED
    assert MarketplaceOAuthOperation.objects.filter(
        action="revoke",
        status=MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED,
    ).exists()
    assert MarketplaceOAuthAction.objects.filter(
        action=MarketplaceOAuthAction.Action.REVOKE,
        status=MarketplaceOAuthAction.Status.RECONCILE_REQUIRED,
    ).exists()


@pytest.mark.django_db
def test_oauth_action_key_cannot_cross_resources():
    tenant, user, store, config = marketplace_context("oauth-cross-resource", "shopee")
    second_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=store.platform,
        code="store-oauth-cross-resource-2",
        name="Second demo store",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    first = create_store_authorization(
        tenant=tenant,
        integration_config=config,
        store=store,
        platform="shopee",
        region="SG",
        platform_store_id="demo-cross-resource-a",
        merchant_subject_id="demo-cross-resource-a",
        shop_cipher="",
        credential_id="synthetic-cross-resource-a-credential",
        token_id="synthetic-cross-resource-a-token",
        scopes=["orders.read"],
        actor=user,
    )
    second = create_store_authorization(
        tenant=tenant,
        integration_config=config,
        store=second_store,
        platform="shopee",
        region="SG",
        platform_store_id="demo-cross-resource-b",
        merchant_subject_id="demo-cross-resource-b",
        shop_cipher="",
        credential_id="synthetic-cross-resource-b-credential",
        token_id="synthetic-cross-resource-b-token",
        scopes=["orders.read"],
        actor=user,
    )
    grant(user, "integrations.credential.rotate", DataScope.ScopeType.ALL)
    client = client_for(user)
    first_response = client.post(
        f"/api/internal/integrations/store-authorizations/{first.id}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-resource-key-001",
    )
    second_response = client.post(
        f"/api/internal/integrations/store-authorizations/{second.id}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-resource-key-001",
    )
    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["code"] == "STATE_CONFLICT"
    second.refresh_from_db()
    assert second.credential_reference_version == 1


@pytest.mark.django_db
def test_reconcile_retry_replaces_existing_authorization_without_unique_conflict():
    _tenant, user, store, config, authorization = create_authorization("oauth-retry-reconcile")
    grant(user, "integrations.store.retry", DataScope.ScopeType.ALL)
    transition_store_authorization(
        authorization,
        target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
        actor=user,
    )
    transition_store_authorization(
        authorization,
        target_status=MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED,
        actor=user,
        error_code="OAUTH_REVOKE_RECONCILE_REQUIRED",
    )
    client = client_for(user)
    retry = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/retry/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-retry-reconcile-001",
    )
    assert retry.status_code == 201
    parsed = parse_qs(urlparse(retry.json()["data"]["authorization_url"]).query)
    state = parsed["state"][0]
    code = "synthetic-code-reconcile-retry"
    store_id = f"synthetic-store-{store.id}"
    callback = client.get(
        "/api/platform/oauth/shopee/callback/",
        {"state": state, "code": code, "platform_store_id": store_id, "signature": synthetic_callback_signature("shopee", state, code, store_id)},
    )
    assert callback.status_code == 302
    authorization.refresh_from_db()
    assert authorization.status == MarketplaceStoreAuthorization.Status.ACTIVE
    assert authorization.credential_reference_version == 2


@pytest.mark.django_db
@override_settings(MARKETPLACE_OAUTH_SYNTHETIC_ENABLED=False, MARKETPLACE_OAUTH_NETWORK_ENABLED=False)
def test_production_synthetic_gate_rejects_every_mutating_oauth_entrypoint_without_action_records():
    _tenant, user, store, config, authorization = create_authorization("oauth-production-gate")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    grant(user, "integrations.credential.rotate", DataScope.ScopeType.ALL)
    grant(user, "integrations.store.revoke", DataScope.ScopeType.ALL)
    grant(user, "integrations.store.retry", DataScope.ScopeType.ALL)
    client = client_for(user)
    initiate = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        {"integration_config_id": config.id, "store_id": store.id, "platform": "shopee", "region": "SG", "redirect_target_code": "integrations"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-production-gate-initiate",
    )
    callback = client.get("/api/platform/oauth/shopee/callback/", {"state": "synthetic-state-not-stored"})
    refresh = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-production-gate-refresh",
    )
    revoke = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/revoke/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-production-gate-revoke",
    )
    retry = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/retry/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-production-gate-retry",
    )
    assert all(response.status_code == 503 for response in (initiate, callback, refresh, revoke, retry))
    assert not MarketplaceOAuthAction.objects.exists()
    authorization.refresh_from_db()
    assert authorization.credential_reference_version == 1
    assert authorization.status == MarketplaceStoreAuthorization.Status.PENDING


@pytest.mark.django_db
def test_callback_invalid_ownership_matrix_has_zero_side_effects():
    _tenant, user, store, config = marketplace_context("oauth-zero-side-effect", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    initiated = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-zero-side-effect-initiate",
    )
    state = parse_qs(urlparse(initiated.json()["data"]["authorization_url"]).query)["state"][0]
    attempt = MarketplaceOAuthAttempt.objects.get(pk=initiated.json()["data"]["attempt_id"])
    operation_count = MarketplaceOAuthOperation.objects.count()
    audit_count = IntegrationAuditLog.objects.count()

    invalid_requests = [
        client.get("/api/platform/oauth/tiktok/callback/", {"state": state}),
        client.get("/api/platform/oauth/shopee/callback/", {"state": "unknown-state"}),
        client.get(f"/api/platform/oauth/shopee/callback/?state={state}&state=duplicate"),
    ]
    assert [response.status_code for response in invalid_requests] == [422, 422, 400]
    attempt.refresh_from_db()
    assert attempt.status == MarketplaceOAuthAttempt.Status.INITIATED
    assert attempt.consumed_at is None
    assert MarketplaceOAuthOperation.objects.count() == operation_count
    assert IntegrationAuditLog.objects.count() == audit_count


@pytest.mark.django_db
def test_action_and_operation_bindings_reject_same_tenant_mismatches():
    tenant, user, store, config = marketplace_context("oauth-binding", "shopee")
    other_user = create_user(tenant, "oauth-binding-other")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    initiated = client_for(user).post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-binding-initiate",
    )
    attempt = MarketplaceOAuthAttempt.objects.get(pk=initiated.json()["data"]["attempt_id"])
    with pytest.raises(ValidationError), oauth_service_write():
        MarketplaceOAuthAction.objects.create(
            tenant=tenant,
            internal_user=other_user,
            action=MarketplaceOAuthAction.Action.INITIATE,
            object_type="store_target",
            object_id=str(store.id),
            session_hash="a" * 64,
            idempotency_key_hash="b" * 64,
            request_fingerprint_hash="c" * 64,
            operation_id_hash="d" * 64,
            attempt=attempt,
        )
    action = MarketplaceOAuthAction.objects.get(attempt=attempt)
    with pytest.raises(ValidationError), oauth_service_write():
        MarketplaceOAuthAction.objects.filter(pk=action.pk).update(object_id="999999")

    second_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=store.platform,
        code="store-oauth-binding-2",
        name="Second demo store",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    authorization = create_store_authorization(
        tenant=tenant,
        integration_config=config,
        store=second_store,
        platform="shopee",
        region="SG",
        platform_store_id="demo-binding-second",
        merchant_subject_id="demo-binding-second",
        shop_cipher="",
        credential_id="synthetic-binding-second-credential",
        token_id="synthetic-binding-second-token",
        scopes=["orders.read"],
        actor=user,
    )
    with pytest.raises(ValidationError), oauth_service_write():
        MarketplaceOAuthOperation.objects.create(
            tenant=tenant,
            action="exchange",
            operation_id_hash="e" * 64,
            attempt=attempt,
            authorization=authorization,
        )


@pytest.mark.django_db
def test_resource_lease_fencing_rejects_old_owner_and_serializes_different_keys():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-fencing")
    first, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-fencing-key-001"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    second, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-fencing-key-002"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    old_claim, claimed = claim_oauth_action(first)
    assert claimed is True
    _blocked, claimed = claim_oauth_action(second)
    assert claimed is False
    expire_oauth_claim(old_claim)
    new_claim, claimed = claim_oauth_action(second)
    assert claimed is True
    assert new_claim.execution_fence > old_claim.execution_fence
    with pytest.raises(StateConflict):
        complete_oauth_action(old_claim, {"status": "stale"}, authorization=authorization)
    complete_oauth_action(new_claim, {"status": "active"}, authorization=authorization)
    second.refresh_from_db()
    assert second.status == MarketplaceOAuthAction.Status.SUCCEEDED


@pytest.mark.django_db
def test_exchange_recovery_resumes_from_persisted_custody_reference(monkeypatch):
    _tenant, user, store, config = marketplace_context("oauth-exchange-recovery", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    initiated = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-exchange-recovery-initiate",
    )
    state = parse_qs(urlparse(initiated.json()["data"]["authorization_url"]).query)["state"][0]
    code = "synthetic-code-exchange-recovery"
    platform_store_id = f"synthetic-store-{store.id}"
    signature = synthetic_callback_signature("shopee", state, code, platform_store_id)
    original = oauth_services_module._complete_exchange
    monkeypatch.setattr(oauth_services_module, "_complete_exchange", lambda **_kwargs: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit):
        client.get(
            "/api/platform/oauth/shopee/callback/",
            {"state": state, "code": code, "platform_store_id": platform_store_id, "signature": signature},
        )
    operation = MarketplaceOAuthOperation.objects.get(action="exchange")
    assert operation.phase == "custody_exchanged"
    assert operation.metadata["custody_reference"]["credential_id"]
    with oauth_service_write():
        MarketplaceOAuthOperation.objects.filter(pk=operation.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
    monkeypatch.setattr(oauth_services_module, "_complete_exchange", original)
    result = recover_oauth_operation(operation.operation_id_hash)
    assert result["status"] == MarketplaceStoreAuthorization.Status.ACTIVE
    operation.refresh_from_db()
    assert operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED
    assert MarketplaceStoreAuthorization.objects.filter(store=store, status="active").count() == 1


@pytest.mark.django_db
def test_refresh_recovery_reuses_one_persisted_reference(monkeypatch):
    _tenant, user, _store, _config, authorization = create_authorization("oauth-refresh-recovery")
    grant(user, "integrations.credential.rotate", DataScope.ScopeType.ALL)
    original = oauth_services_module.rotate_store_authorization_references
    monkeypatch.setattr(
        oauth_services_module,
        "rotate_store_authorization_references",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit()),
    )
    with pytest.raises(SystemExit):
        client_for(user).post(
            f"/api/internal/integrations/store-authorizations/{authorization.id}/refresh/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="oauth-refresh-recovery-key",
        )
    action = MarketplaceOAuthAction.objects.get(action=MarketplaceOAuthAction.Action.REFRESH)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=action.operation_id_hash)
    reference = dict(operation.metadata["custody_reference"])
    expire_oauth_claim(action)
    monkeypatch.setattr(oauth_services_module, "rotate_store_authorization_references", original)
    recover_oauth_operation(operation.operation_id_hash)
    authorization.refresh_from_db()
    action.refresh_from_db()
    assert authorization.credential_id == reference["credential_id"]
    assert authorization.credential_reference_version == reference["credential_reference_version"]
    assert action.status == MarketplaceOAuthAction.Status.SUCCEEDED


@pytest.mark.django_db
def test_revoke_recovery_skips_repeated_custody_side_effect(monkeypatch):
    _tenant, user, _store, _config, authorization = create_authorization("oauth-revoke-recovery")
    grant(user, "integrations.store.revoke", DataScope.ScopeType.ALL)
    original = oauth_services_module.transition_store_authorization

    def crash_before_local_revoke(record, *, target_status, actor, **kwargs):
        if target_status == MarketplaceStoreAuthorization.Status.REVOKED:
            raise SystemExit()
        return original(record, target_status=target_status, actor=actor, **kwargs)

    monkeypatch.setattr(oauth_services_module, "transition_store_authorization", crash_before_local_revoke)
    with pytest.raises(SystemExit):
        client_for(user).post(
            f"/api/internal/integrations/store-authorizations/{authorization.id}/revoke/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="oauth-revoke-recovery-key",
        )
    action = MarketplaceOAuthAction.objects.get(action=MarketplaceOAuthAction.Action.REVOKE)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=action.operation_id_hash)
    assert operation.metadata["custody_revoked"] is True
    expire_oauth_claim(action)
    monkeypatch.setattr(oauth_services_module, "transition_store_authorization", original)
    recover_oauth_operation(operation.operation_id_hash)
    authorization.refresh_from_db()
    action.refresh_from_db()
    assert authorization.status == MarketplaceStoreAuthorization.Status.REVOKED
    assert action.status == MarketplaceOAuthAction.Status.SUCCEEDED


@pytest.mark.django_db
def test_refresh_recovery_finalizes_action_after_operation_success(monkeypatch):
    _tenant, user, _store, _config, authorization = create_authorization("oauth-refresh-finalize")
    grant(user, "integrations.credential.rotate", DataScope.ScopeType.ALL)
    original = oauth_views_module.complete_oauth_action
    monkeypatch.setattr(
        oauth_views_module,
        "complete_oauth_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit()),
    )
    with pytest.raises(SystemExit):
        client_for(user).post(
            f"/api/internal/integrations/store-authorizations/{authorization.id}/refresh/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="oauth-refresh-finalize-key",
        )
    action = MarketplaceOAuthAction.objects.get(action=MarketplaceOAuthAction.Action.REFRESH)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=action.operation_id_hash)
    assert operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED
    assert action.status == MarketplaceOAuthAction.Status.RUNNING
    expire_oauth_claim(action)
    monkeypatch.setattr(oauth_views_module, "complete_oauth_action", original)
    result = recover_oauth_operation(operation.operation_id_hash)
    action.refresh_from_db()
    authorization.refresh_from_db()
    assert result["status"] == "succeeded"
    assert action.status == MarketplaceOAuthAction.Status.SUCCEEDED
    assert authorization.credential_reference_version == 2


@pytest.mark.django_db
def test_exchange_recovery_keeps_compensated_reference_inactive(monkeypatch):
    tenant, user, store, config = marketplace_context("oauth-exchange-compensated", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    initiated = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-exchange-compensated-initiate",
    )
    state = parse_qs(urlparse(initiated.json()["data"]["authorization_url"]).query)["state"][0]
    code = "synthetic-code-exchange-compensated"
    platform_store_id = f"synthetic-store-{store.id}"
    monkeypatch.setattr(
        oauth_services_module,
        "_complete_exchange",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic crash")),
    )
    callback = client.get(
        "/api/platform/oauth/shopee/callback/",
        {
            "state": state,
            "code": code,
            "platform_store_id": platform_store_id,
            "signature": synthetic_callback_signature("shopee", state, code, platform_store_id),
        },
    )
    assert callback.status_code == 302
    operation = MarketplaceOAuthOperation.objects.get(action="exchange")
    assert operation.metadata["compensation"]["status"] == "revoked"
    result = recover_oauth_operation(operation.operation_id_hash)
    operation.refresh_from_db()
    assert result["status"] == "compensated"
    assert operation.phase == "compensated"
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_production_gate_blocks_direct_mutation_services_without_side_effects():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-service-gate")
    action, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-service-gate-key"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    action, claimed = claim_oauth_action(action)
    assert claimed is True
    counts = {
        "actions": MarketplaceOAuthAction.objects.count(),
        "operations": MarketplaceOAuthOperation.objects.count(),
        "attempts": MarketplaceOAuthAttempt.objects.count(),
        "audits": IntegrationAuditLog.objects.count(),
    }
    with override_settings(MARKETPLACE_OAUTH_SYNTHETIC_ENABLED=False):
        blocked_calls = [
            lambda: begin_oauth_action(
                request=oauth_service_request("/oauth/revoke/", "oauth-service-gate-new-key"),
                actor=user,
                action=MarketplaceOAuthAction.Action.REVOKE,
                object_type="store_authorization",
                object_id=authorization.pk,
                payload={},
                authorization=authorization,
            ),
            lambda: claim_oauth_action(action),
            lambda: complete_oauth_action(action, {"status": "active"}, authorization=authorization),
            lambda: fail_oauth_action(action, "OAUTH_BLOCKED"),
            lambda: _update_operation(
                action.operation_id_hash,
                claim=action,
                status=MarketplaceOAuthOperation.Status.SUCCEEDED,
            ),
        ]
        for blocked_call in blocked_calls:
            with pytest.raises(OAuthAdapterError) as exc_info:
                blocked_call()
            assert exc_info.value.error_code == "OAUTH_SYNTHETIC_DISABLED"
    assert MarketplaceOAuthAction.objects.count() == counts["actions"]
    assert MarketplaceOAuthOperation.objects.count() == counts["operations"]
    assert MarketplaceOAuthAttempt.objects.count() == counts["attempts"]
    assert IntegrationAuditLog.objects.count() == counts["audits"]
    authorization.refresh_from_db()
    assert authorization.credential_reference_version == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "permission_code"),
    (
        ("authorize", "integrations.store.authorize"),
        ("refresh", "integrations.credential.rotate"),
        ("revoke", "integrations.store.revoke"),
        ("retry", "integrations.store.retry"),
    ),
)
def test_oauth_target_endpoint_uses_internal_exact_action_permission(action, permission_code):
    _tenant, user, _store, _config, _authorization = create_authorization(f"oauth-target-{action}")
    grant(user, permission_code, DataScope.ScopeType.ALL)
    response = client_for(user).get(
        "/api/internal/integrations/store-authorizations/oauth/targets/",
        {"action": action},
    )
    assert response.status_code == 200
    assert response.json()["data"]["action"] == action


@pytest.mark.django_db
def test_oauth_target_endpoint_rejects_external_user_even_with_exact_scope():
    tenant, _user, _store, _config, _authorization = create_authorization("oauth-target-external")
    external = create_user(tenant, "oauth-target-external-user", CustomUser.UserType.EXTERNAL)
    grant(external, "integrations.store.retry", DataScope.ScopeType.ALL)
    response = client_for(external).get(
        "/api/internal/integrations/store-authorizations/oauth/targets/",
        {"action": "retry"},
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_retry_only_user_can_read_the_attempt_created_by_retry():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-retry-only-status")
    grant(user, "integrations.store.retry", DataScope.ScopeType.ALL)
    transition_store_authorization(
        authorization,
        target_status=MarketplaceStoreAuthorization.Status.ERROR,
        actor=user,
        error_code="OAUTH_SYNTHETIC_FAILURE",
    )
    retry = client_for(user).post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/retry/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-retry-only-status-key",
    )
    assert retry.status_code == 201
    data = retry.json()["data"]
    assert data["authorization_url"].startswith("https://synthetic.invalid/")
    detail = client_for(user).get(
        f"/api/internal/integrations/oauth-attempts/{data['attempt_id']}/"
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == data["attempt_id"]


@pytest.mark.django_db(transaction=True)
def test_mysql_oauth_idempotency_registry_serializes_concurrent_workers():
    if connection.vendor != "mysql":
        pytest.skip("MySQL idempotency race verification runs in Local Sandbox.")
    tenant, user, _store, config, first = create_authorization("oauth-action-race")
    second_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=first.store.platform,
        code="store-oauth-action-race-second",
        name="Second race store",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    second = create_store_authorization(
        tenant=tenant,
        integration_config=config,
        store=second_store,
        platform="shopee",
        region="SG",
        platform_store_id="demo-oauth-action-race-second",
        merchant_subject_id="demo-oauth-action-race-second",
        shop_cipher="",
        credential_id="synthetic-oauth-action-race-second-credential",
        token_id="synthetic-oauth-action-race-second-token",
        scopes=["orders.read"],
        actor=user,
    )

    def begin(authorization_id, key):
        close_old_connections()
        try:
            actor = CustomUser.objects.get(pk=user.pk)
            authorization = MarketplaceStoreAuthorization.objects.get(pk=authorization_id)
            _action, replay = begin_oauth_action(
                request=oauth_service_request("/oauth/refresh/", key),
                actor=actor,
                action=MarketplaceOAuthAction.Action.REFRESH,
                object_type="store_authorization",
                object_id=authorization.pk,
                payload={},
                authorization=authorization,
            )
            return "replay" if replay else "created"
        except StateConflict:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        cross_resource = list(executor.map(
            lambda authorization_id: begin(authorization_id, "oauth-action-race-cross-key"),
            (first.pk, second.pk),
        ))
    assert sorted(cross_resource) == ["conflict", "created"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        same_resource = list(executor.map(
            lambda _index: begin(first.pk, "oauth-action-race-same-key"),
            range(2),
        ))
    assert sorted(same_resource) == ["created", "replay"]


def _pause_fence_and_take_over(monkeypatch, worker_call, takeover):
    """Pause a worker inside a fenced write boundary, take over its lease, then release it."""
    gate = threading.Event()
    release = threading.Event()
    original_fence = store_authorization_module.assert_operation_fence

    def pausing_fence(claim):
        gate.set()
        if not release.wait(timeout=15):
            raise RuntimeError("fence release timed out")
        return original_fence(claim)

    monkeypatch.setattr(store_authorization_module, "assert_operation_fence", pausing_fence)
    errors = []

    def worker():
        close_old_connections()
        try:
            worker_call()
        except Exception as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    thread = threading.Thread(target=worker)
    thread.start()
    assert gate.wait(timeout=15)
    result = takeover()
    release.set()
    thread.join(timeout=15)
    assert not thread.is_alive()
    return errors, result


@pytest.mark.django_db
def test_assert_operation_fence_rejects_stale_expired_and_foreign_claims():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-fence-gate")
    action, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-fence-gate-key"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    claim, claimed = claim_oauth_action(action)
    assert claimed is True
    with transaction.atomic():
        assert_operation_fence(claim)
    foreign = SimpleNamespace(
        operation_id_hash=claim.operation_id_hash,
        execution_owner="other-owner",
        execution_fence=claim.execution_fence,
        lease_expires_at=claim.lease_expires_at,
    )
    bumped = SimpleNamespace(
        operation_id_hash=claim.operation_id_hash,
        execution_owner=claim.execution_owner,
        execution_fence=claim.execution_fence + 5,
        lease_expires_at=claim.lease_expires_at,
    )
    for stale in (foreign, bumped):
        with pytest.raises(StateConflict), transaction.atomic():
            assert_operation_fence(stale)
    expire_oauth_claim(claim)
    with pytest.raises(StateConflict), transaction.atomic():
        assert_operation_fence(claim)


@pytest.mark.django_db
def test_fenced_exchange_create_rejects_stale_claim_without_side_effects(monkeypatch):
    tenant, user, store, config = marketplace_context("oauth-fence-exchange-direct", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    initiated = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-fence-exchange-direct-initiate",
    )
    state = parse_qs(urlparse(initiated.json()["data"]["authorization_url"]).query)["state"][0]
    code = "synthetic-code-fence-exchange-direct"
    platform_store_id = f"synthetic-store-{store.id}"
    original = oauth_services_module._complete_exchange
    monkeypatch.setattr(oauth_services_module, "_complete_exchange", lambda **_kwargs: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit):
        client.get(
            "/api/platform/oauth/shopee/callback/",
            {"state": state, "code": code, "platform_store_id": platform_store_id, "signature": synthetic_callback_signature("shopee", state, code, platform_store_id)},
        )
    monkeypatch.setattr(oauth_services_module, "_complete_exchange", original)
    operation = MarketplaceOAuthOperation.objects.get(action="exchange")
    attempt = MarketplaceOAuthAttempt.objects.get(pk=operation.attempt_id)
    stale_claim = SimpleNamespace(
        operation_id_hash=operation.operation_id_hash,
        execution_owner=operation.execution_owner,
        execution_fence=operation.execution_fence,
        lease_expires_at=operation.lease_expires_at,
    )
    with oauth_service_write():
        MarketplaceOAuthOperation.objects.filter(pk=operation.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
    new_claim, claimed = claim_oauth_operation(MarketplaceOAuthOperation.objects.get(pk=operation.pk))
    assert claimed is True
    assert new_claim.execution_fence > stale_claim.execution_fence
    reference = dict(operation.metadata["custody_reference"])
    audit_count = IntegrationAuditLog.objects.count()
    with pytest.raises(StateConflict):
        oauth_services_module._complete_exchange(
            attempt=attempt,
            operation_claim=stale_claim,
            reference=reference,
            platform_store_id=operation.metadata["platform_store_id"],
        )
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()
    assert IntegrationAuditLog.objects.count() == audit_count
    attempt.refresh_from_db()
    assert attempt.status == MarketplaceOAuthAttempt.Status.CALLBACK_RECEIVED
    with oauth_service_write():
        MarketplaceOAuthOperation.objects.filter(pk=operation.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
    result = recover_oauth_operation(operation.operation_id_hash)
    assert result["status"] == MarketplaceStoreAuthorization.Status.ACTIVE
    assert MarketplaceStoreAuthorization.objects.filter(tenant=tenant, status="active").count() == 1


@pytest.mark.django_db
def test_initiate_closes_operation_terminal_state():
    tenant, user, store, config = marketplace_context("oauth-terminal-initiate", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    initiated = client_for(user).post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-terminal-initiate-key",
    )
    assert initiated.status_code == 201
    action = MarketplaceOAuthAction.objects.get(action=MarketplaceOAuthAction.Action.INITIATE)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=action.operation_id_hash)
    assert action.status == MarketplaceOAuthAction.Status.SUCCEEDED
    assert operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED
    assert operation.phase == "initiate_completed"
    assert operation.attempt_id == action.attempt_id
    assert operation.execution_owner == ""
    assert operation.lease_expires_at is None


@pytest.mark.django_db
def test_retry_closes_outer_and_inner_operation_terminal_states():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-terminal-retry")
    grant(user, "integrations.store.retry", DataScope.ScopeType.ALL)
    transition_store_authorization(
        authorization,
        target_status=MarketplaceStoreAuthorization.Status.ERROR,
        actor=user,
        error_code="OAUTH_SYNTHETIC_FAILURE",
    )
    retry = client_for(user).post(
        f"/api/internal/integrations/store-authorizations/{authorization.id}/retry/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-terminal-retry-key",
    )
    assert retry.status_code == 201
    retry_action = MarketplaceOAuthAction.objects.get(action=MarketplaceOAuthAction.Action.RETRY)
    outer_operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=retry_action.operation_id_hash)
    assert retry_action.status == MarketplaceOAuthAction.Status.SUCCEEDED
    assert outer_operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED
    assert outer_operation.phase == "retry_completed"
    assert outer_operation.execution_owner == ""
    inner_action = MarketplaceOAuthAction.objects.get(action=MarketplaceOAuthAction.Action.INITIATE)
    inner_operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=inner_action.operation_id_hash)
    assert inner_action.status == MarketplaceOAuthAction.Status.SUCCEEDED
    assert inner_operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED
    assert inner_operation.phase == "initiate_completed"


@pytest.mark.django_db
def test_fail_oauth_action_sets_operation_terminal_state():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-terminal-fail")
    action, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/revoke/", "oauth-terminal-fail-key"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REVOKE,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    action, claimed = claim_oauth_action(action)
    assert claimed is True
    fail_oauth_action(action, "OAUTH_REVOKE_FAILED")
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=action.operation_id_hash)
    assert operation.status == MarketplaceOAuthOperation.Status.FAILED
    assert operation.phase == "action_failed"
    assert operation.last_error_code == "OAUTH_REVOKE_FAILED"
    assert operation.execution_owner == ""
    assert operation.lease_expires_at is None


@pytest.mark.django_db
def test_recovery_converges_operation_after_action_success_window():
    tenant, user, store, config = marketplace_context("oauth-window-success", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    initiated = client_for(user).post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-window-success-initiate",
    )
    assert initiated.status_code == 201
    action = MarketplaceOAuthAction.objects.get(action=MarketplaceOAuthAction.Action.INITIATE)
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=action.operation_id_hash)
    assert action.status == MarketplaceOAuthAction.Status.SUCCEEDED
    assert operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED
    with oauth_service_write():
        MarketplaceOAuthOperation.objects.filter(pk=operation.pk).update(
            status="pending", phase="attempt_created", execution_owner="", lease_expires_at=None
        )
    result = recover_oauth_operation(operation.operation_id_hash)
    assert result["status"] == "succeeded"
    operation.refresh_from_db()
    assert operation.status == MarketplaceOAuthOperation.Status.SUCCEEDED
    assert operation.phase == "initiate_completed"
    assert operation.attempt_id == action.attempt_id
    assert operation.execution_owner == ""
    assert recover_oauth_operation(operation.operation_id_hash)["status"] == "succeeded"


@pytest.mark.django_db
def test_recovery_converges_operation_after_action_failure_window():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-window-failure")
    action, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-window-failure-key"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    action, claimed = claim_oauth_action(action)
    assert claimed is True
    fail_oauth_action(action, "OAUTH_REFRESH_FAILED", reconcile=True)
    action.refresh_from_db()
    assert action.status == MarketplaceOAuthAction.Status.RECONCILE_REQUIRED
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=action.operation_id_hash)
    assert operation.status == MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED
    with oauth_service_write():
        MarketplaceOAuthOperation.objects.filter(pk=operation.pk).update(
            status="pending", execution_owner="", lease_expires_at=None
        )
    result = recover_oauth_operation(operation.operation_id_hash)
    assert result["status"] == "compensated"
    assert result["error_code"] == "OAUTH_REFRESH_FAILED"
    operation.refresh_from_db()
    assert operation.status == MarketplaceOAuthOperation.Status.RECONCILE_REQUIRED
    assert operation.phase == "action_failed"


@pytest.mark.django_db
def test_resource_lease_service_gate_blocks_bypass_writes():
    _tenant, user, _store, _config, authorization = create_authorization("oauth-lease-gate")
    action, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-lease-gate-key"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    action, claimed = claim_oauth_action(action)
    assert claimed is True
    lease = MarketplaceOAuthResourceLease.objects.get(
        tenant=action.tenant,
        object_type=action.object_type,
        object_id=action.object_id,
    )
    assert lease.fence_token == 1
    with pytest.raises(ValidationError, match="service layer"):
        lease.fence_token = 999
        lease.save()
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceOAuthResourceLease.objects.filter(pk=lease.pk).update(fence_token=999)
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceOAuthResourceLease.objects.bulk_create([MarketplaceOAuthResourceLease()])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketplaceOAuthResourceLease.objects.filter(pk=lease.pk).delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        lease.delete()
    lease.refresh_from_db()
    assert lease.fence_token == 1
    assert lease.execution_owner == action.execution_owner


@pytest.mark.django_db(transaction=True)
def test_mysql_exchange_create_boundary_zero_side_effects_after_takeover(monkeypatch):
    if connection.vendor != "mysql":
        pytest.skip("MySQL double-worker fencing verification runs in Local Sandbox.")
    tenant, user, store, config = marketplace_context("oauth-fence-exchange-race", "shopee")
    grant(user, "integrations.store.authorize", DataScope.ScopeType.ALL)
    client = client_for(user)
    initiated = client.post(
        "/api/internal/integrations/store-authorizations/oauth/initiate/",
        oauth_initiate_payload(store, config),
        format="json",
        HTTP_IDEMPOTENCY_KEY="oauth-fence-exchange-race-initiate",
    )
    state = parse_qs(urlparse(initiated.json()["data"]["authorization_url"]).query)["state"][0]
    code = "synthetic-code-fence-exchange-race"
    platform_store_id = f"synthetic-store-{store.id}"
    original = oauth_services_module._complete_exchange
    monkeypatch.setattr(oauth_services_module, "_complete_exchange", lambda **_kwargs: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit):
        client.get(
            "/api/platform/oauth/shopee/callback/",
            {"state": state, "code": code, "platform_store_id": platform_store_id, "signature": synthetic_callback_signature("shopee", state, code, platform_store_id)},
        )
    monkeypatch.setattr(oauth_services_module, "_complete_exchange", original)
    operation = MarketplaceOAuthOperation.objects.get(action="exchange")
    attempt_pk = operation.attempt_id
    stale_claim = SimpleNamespace(
        operation_id_hash=operation.operation_id_hash,
        execution_owner=operation.execution_owner,
        execution_fence=operation.execution_fence,
        lease_expires_at=operation.lease_expires_at,
    )
    reference = dict(operation.metadata["custody_reference"])
    meta_store_id = operation.metadata["platform_store_id"]
    audit_count = IntegrationAuditLog.objects.count()

    def worker_call():
        worker_attempt = MarketplaceOAuthAttempt.objects.get(pk=attempt_pk)
        oauth_services_module._complete_exchange(
            attempt=worker_attempt,
            operation_claim=stale_claim,
            reference=reference,
            platform_store_id=meta_store_id,
        )

    def takeover():
        with oauth_service_write():
            MarketplaceOAuthOperation.objects.filter(pk=operation.pk).update(
                lease_expires_at=timezone.now() - timedelta(seconds=1)
            )
        new_claim, claimed = claim_oauth_operation(MarketplaceOAuthOperation.objects.get(pk=operation.pk))
        assert claimed is True
        return new_claim

    errors, _new_claim = _pause_fence_and_take_over(monkeypatch, worker_call, takeover)
    assert len(errors) == 1
    assert isinstance(errors[0], StateConflict)
    assert not MarketplaceStoreAuthorization.objects.filter(tenant=tenant).exists()
    assert IntegrationAuditLog.objects.count() == audit_count
    attempt = MarketplaceOAuthAttempt.objects.get(pk=attempt_pk)
    assert attempt.status == MarketplaceOAuthAttempt.Status.CALLBACK_RECEIVED
    with oauth_service_write():
        MarketplaceOAuthOperation.objects.filter(pk=operation.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
    result = recover_oauth_operation(operation.operation_id_hash)
    assert result["status"] == MarketplaceStoreAuthorization.Status.ACTIVE
    assert MarketplaceStoreAuthorization.objects.filter(tenant=tenant, status="active").count() == 1


@pytest.mark.django_db(transaction=True)
def test_mysql_refresh_rotate_boundary_zero_side_effects_after_takeover(monkeypatch):
    if connection.vendor != "mysql":
        pytest.skip("MySQL double-worker fencing verification runs in Local Sandbox.")
    _tenant, user, _store, _config, authorization = create_authorization("oauth-fence-refresh-race")
    first, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-fence-refresh-race-001"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    second, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/refresh/", "oauth-fence-refresh-race-002"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    old_claim, claimed = claim_oauth_action(first)
    assert claimed is True
    reference = {
        "credential_id": "synthetic-fence-refresh-race-credential",
        "token_id": "synthetic-fence-refresh-race-token",
        "credential_reference_version": 2,
        "expires_at": None,
    }
    _update_operation(first.operation_id_hash, claim=old_claim, phase="new_reference_created", metadata={"custody_reference": reference})
    stale_claim = SimpleNamespace(
        operation_id_hash=first.operation_id_hash,
        execution_owner=old_claim.execution_owner,
        execution_fence=old_claim.execution_fence,
        lease_expires_at=old_claim.lease_expires_at,
    )
    audit_count = IntegrationAuditLog.objects.count()

    def worker_call():
        worker_authorization = MarketplaceStoreAuthorization.objects.get(pk=authorization.pk)
        worker_actor = CustomUser.objects.get(pk=user.pk)
        oauth_services_module.refresh_authorization(
            authorization=worker_authorization,
            actor=worker_actor,
            operation_id=first.operation_id_hash,
            operation_claim=stale_claim,
        )

    def takeover():
        expire_oauth_claim(MarketplaceOAuthAction.objects.get(pk=first.pk))
        new_claim, claimed_new = claim_oauth_action(MarketplaceOAuthAction.objects.get(pk=second.pk))
        assert claimed_new is True
        return new_claim

    errors, new_claim = _pause_fence_and_take_over(monkeypatch, worker_call, takeover)
    assert len(errors) == 1
    assert isinstance(errors[0], StateConflict)
    authorization.refresh_from_db()
    assert authorization.credential_reference_version == 1
    assert IntegrationAuditLog.objects.count() == audit_count
    _update_operation(second.operation_id_hash, claim=new_claim, phase="new_reference_created", metadata={"custody_reference": reference})
    updated = oauth_services_module.refresh_authorization(
        authorization=MarketplaceStoreAuthorization.objects.get(pk=authorization.pk),
        actor=user,
        operation_id=second.operation_id_hash,
        operation_claim=new_claim,
    )
    assert updated.credential_reference_version == 2


@pytest.mark.django_db(transaction=True)
def test_mysql_revoke_transition_boundary_zero_side_effects_after_takeover(monkeypatch):
    if connection.vendor != "mysql":
        pytest.skip("MySQL double-worker fencing verification runs in Local Sandbox.")
    _tenant, user, _store, _config, authorization = create_authorization("oauth-fence-revoke-race")
    first, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/revoke/", "oauth-fence-revoke-race-001"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REVOKE,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    second, _ = begin_oauth_action(
        request=oauth_service_request("/oauth/revoke/", "oauth-fence-revoke-race-002"),
        actor=user,
        action=MarketplaceOAuthAction.Action.REVOKE,
        object_type="store_authorization",
        object_id=authorization.pk,
        payload={},
        authorization=authorization,
    )
    old_claim, claimed = claim_oauth_action(first)
    assert claimed is True
    stale_claim = SimpleNamespace(
        operation_id_hash=first.operation_id_hash,
        execution_owner=old_claim.execution_owner,
        execution_fence=old_claim.execution_fence,
        lease_expires_at=old_claim.lease_expires_at,
    )
    audit_count = IntegrationAuditLog.objects.count()

    def worker_call():
        worker_authorization = MarketplaceStoreAuthorization.objects.get(pk=authorization.pk)
        worker_actor = CustomUser.objects.get(pk=user.pk)
        oauth_services_module.revoke_authorization(
            authorization=worker_authorization,
            actor=worker_actor,
            operation_id=first.operation_id_hash,
            operation_claim=stale_claim,
        )

    def takeover():
        expire_oauth_claim(MarketplaceOAuthAction.objects.get(pk=first.pk))
        new_claim, claimed_new = claim_oauth_action(MarketplaceOAuthAction.objects.get(pk=second.pk))
        assert claimed_new is True
        return new_claim

    errors, new_claim = _pause_fence_and_take_over(monkeypatch, worker_call, takeover)
    assert len(errors) == 1
    assert isinstance(errors[0], StateConflict)
    authorization.refresh_from_db()
    assert authorization.status == MarketplaceStoreAuthorization.Status.PENDING
    operation = MarketplaceOAuthOperation.objects.get(operation_id_hash=first.operation_id_hash)
    assert not (operation.metadata or {}).get("custody_revoked")
    assert IntegrationAuditLog.objects.count() == audit_count
    updated = oauth_services_module.revoke_authorization(
        authorization=MarketplaceStoreAuthorization.objects.get(pk=authorization.pk),
        actor=user,
        operation_id=second.operation_id_hash,
        operation_claim=new_claim,
    )
    assert updated.status == MarketplaceStoreAuthorization.Status.REVOKED
