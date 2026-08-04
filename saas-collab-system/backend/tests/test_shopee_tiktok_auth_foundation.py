import base64
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import threading
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, migrations
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.common.exceptions import StateConflict
from apps.integrations.models import (
    APIIntegrationConfig,
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    marketplace_identity_key,
)
from apps.integrations.admin import MarketplaceStoreAuthorizationAdmin, PlatformIntegrationConfigAdmin
from apps.integrations.credential_service import rotate_config_references
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
