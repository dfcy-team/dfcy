import json
import importlib

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.common.exceptions import BusinessRuleViolation, DataScopeDenied, StateConflict
from apps.integrations.models import IntegrationAuditLog, MarketplaceStoreAuthorization, PlatformIntegrationConfig
from apps.integrations.store_auth_services import (
    activate_mock_store_authorization,
    create_pending_store_authorization,
    expire_mock_store_authorization,
    record_mock_authorization_error,
    record_mock_sync_request,
    retry_mock_store_authorization,
    revoke_mock_store_authorization,
    rotate_mock_credential_references,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.services import user_has_integration_permission
from apps.tenants.models import Tenant


STORE_PERMISSION_CODES = (
    "integrations.store.view",
    "integrations.store.authorize",
    "integrations.store.revoke",
    "integrations.store.sync",
    "integrations.store.retry",
    "integrations.credential.rotate",
)


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, *permission_codes, scope=None):
    role = Role.objects.create(tenant=user.tenant, name="Marketplace role", code=f"marketplace-{user.id}")
    for code in permission_codes:
        action = code.removeprefix("integrations.")
        permission, _created = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "integrations", "action": action},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=DataScope.ScopeType.ALL if scope is None else DataScope.ScopeType.CUSTOM,
        config={} if scope is None else scope,
    )


def create_store_context(tenant, user, platform, suffix, country="SG"):
    platform_master = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"{platform}-{suffix}",
        name=f"{platform.title()} {suffix}",
        platform_type=platform,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform_master,
        code=f"store-{suffix}",
        name=f"Store {suffix}",
        country_code=country,
        currency="SGD",
        timezone="Asia/Singapore",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=f"mock-{suffix}",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.DISABLED,
        created_by=user,
    )
    return store, config


def create_authorization(user, store, config, suffix):
    return create_pending_store_authorization(
        actor=user,
        integration_config=config,
        store=store,
        platform_store_id=f"mock-store-{suffix}",
        merchant_subject_id=f"mock-merchant-{suffix}",
        shop_cipher=f"mock-shop-cipher-{suffix}" if config.platform == "tiktok" else "",
        scopes=["shop.read", "order.read"],
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_two_tenants_two_platforms_and_store_scope_are_isolated():
    tenant_a = Tenant.objects.create(name="Tenant A", code="market-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="market-b")
    user_a = create_user(tenant_a, "market-a-user")
    user_b = create_user(tenant_b, "market-b-user")
    grant(user_a, *STORE_PERMISSION_CODES)
    grant(user_b, *STORE_PERMISSION_CODES)
    shopee_store, shopee_config = create_store_context(tenant_a, user_a, "shopee", "a")
    tiktok_store, tiktok_config = create_store_context(tenant_b, user_b, "tiktok", "b")
    shopee = create_authorization(user_a, shopee_store, shopee_config, "shopee-a")
    tiktok = create_authorization(user_b, tiktok_store, tiktok_config, "tiktok-b")

    list_a = client_for(user_a).get("/api/internal/integrations/store-authorizations/")
    assert list_a.status_code == 200
    assert list_a.json()["data"]["count"] == 1
    assert list_a.json()["data"]["results"][0]["id"] == shopee.id
    assert client_for(user_a).get(f"/api/internal/integrations/store-authorizations/{tiktok.id}/").status_code == 404

    scoped_user = create_user(tenant_a, "market-a-scoped")
    grant(scoped_user, "integrations.store.view", scope={"platforms": ["shopee"], "store_ids": [shopee_store.id]})
    assert client_for(scoped_user).get(f"/api/internal/integrations/store-authorizations/{shopee.id}/").status_code == 200


@pytest.mark.django_db
def test_global_platform_store_identity_cannot_bind_across_tenants_but_platforms_do_not_collide():
    tenant_a = Tenant.objects.create(name="Tenant A", code="global-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="global-b")
    user_a = create_user(tenant_a, "global-a-user")
    user_b = create_user(tenant_b, "global-b-user")
    grant(user_a, "integrations.store.authorize")
    grant(user_b, "integrations.store.authorize")
    store_a, config_a = create_store_context(tenant_a, user_a, "shopee", "global-a")
    store_b, config_b = create_store_context(tenant_b, user_b, "shopee", "global-b")
    create_authorization(user_a, store_a, config_a, "shared")

    with pytest.raises(StateConflict):
        create_authorization(user_b, store_b, config_b, "shared")

    tiktok_store, tiktok_config = create_store_context(tenant_b, user_b, "tiktok", "global-tiktok")
    tiktok = create_authorization(user_b, tiktok_store, tiktok_config, "shared")
    assert tiktok.platform == "tiktok"


@pytest.mark.django_db
def test_store_tenant_and_platform_mismatch_are_rejected():
    tenant_a = Tenant.objects.create(name="Tenant A", code="mismatch-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="mismatch-b")
    user_a = create_user(tenant_a, "mismatch-user")
    grant(user_a, "integrations.store.authorize")
    shopee_store, shopee_config = create_store_context(tenant_a, user_a, "shopee", "mismatch-shopee")
    other_user = create_user(tenant_b, "mismatch-other-user")
    tiktok_store, _tiktok_config = create_store_context(tenant_b, other_user, "tiktok", "mismatch-tiktok")

    with pytest.raises(DataScopeDenied):
        create_authorization(user_a, tiktok_store, shopee_config, "wrong-tenant")

    candidate = MarketplaceStoreAuthorization(
        tenant=tenant_a,
        platform="shopee",
        store=tiktok_store,
        integration_config=shopee_config,
        region="SG",
        platform_store_id="mock-store-invalid",
        platform_identity_key="0" * 64,
        merchant_subject_id="mock-merchant-invalid",
        created_by=user_a,
        updated_by=user_a,
    )
    with pytest.raises(DjangoValidationError):
        candidate.full_clean()
    assert shopee_store.tenant_id == tenant_a.id


@pytest.mark.django_db
def test_state_transitions_direct_writes_and_append_only_audit_are_enforced():
    tenant = Tenant.objects.create(name="Tenant", code="state-tenant")
    user = create_user(tenant, "state-user")
    grant(user, *STORE_PERMISSION_CODES)
    store, config = create_store_context(tenant, user, "shopee", "state")
    authorization = create_authorization(user, store, config, "state")

    with pytest.raises(DjangoValidationError):
        MarketplaceStoreAuthorization.objects.filter(pk=authorization.pk).update(status="active")
    authorization.status = MarketplaceStoreAuthorization.Status.ACTIVE
    with pytest.raises(DjangoValidationError):
        authorization.save()

    authorization = activate_mock_store_authorization(
        actor=user,
        authorization_id=authorization.id,
        credential_id="mock-credential-state-v1",
        token_id="mock-token-state-v1",
    )
    assert authorization.status == MarketplaceStoreAuthorization.Status.ACTIVE
    assert expire_mock_store_authorization(actor=user, authorization_id=authorization.id).status == "expired"
    assert retry_mock_store_authorization(actor=user, authorization_id=authorization.id).status == "pending"
    authorization = activate_mock_store_authorization(
        actor=user,
        authorization_id=authorization.id,
        credential_id="mock-credential-state-v2",
        token_id="mock-token-state-v2",
    )
    record_mock_sync_request(actor=user, authorization_id=authorization.id)
    authorization = record_mock_authorization_error(
        actor=user,
        authorization_id=authorization.id,
        error_code="MOCK_TIMEOUT",
    )
    assert authorization.status == MarketplaceStoreAuthorization.Status.ERROR
    assert retry_mock_store_authorization(actor=user, authorization_id=authorization.id).status == "pending"
    with pytest.raises(StateConflict):
        retry_mock_store_authorization(actor=user, authorization_id=authorization.id)
    assert revoke_mock_store_authorization(actor=user, authorization_id=authorization.id).status == "revoked"
    with pytest.raises(StateConflict):
        revoke_mock_store_authorization(actor=user, authorization_id=authorization.id)

    audit = IntegrationAuditLog.objects.filter(store_authorization_id=authorization.id).first()
    with pytest.raises(DjangoValidationError):
        IntegrationAuditLog.objects.filter(pk=audit.pk).update(action="changed")
    with pytest.raises(DjangoValidationError):
        audit.delete()


@pytest.mark.django_db
def test_reference_rotation_reloads_locked_row_and_increments_version_atomically():
    tenant = Tenant.objects.create(name="Tenant", code="rotation-tenant")
    user = create_user(tenant, "rotation-user")
    grant(user, "integrations.store.authorize", "integrations.credential.rotate")
    store, config = create_store_context(tenant, user, "tiktok", "rotation")
    authorization = create_authorization(user, store, config, "rotation")
    authorization = activate_mock_store_authorization(
        actor=user,
        authorization_id=authorization.id,
        credential_id="mock-credential-rotation-v1",
        token_id="mock-token-rotation-v1",
    )
    stale_version = authorization.credential_reference_version

    first = rotate_mock_credential_references(
        actor=user,
        authorization_id=authorization.id,
        credential_id="mock-credential-rotation-v2",
        token_id="mock-token-rotation-v2",
    )
    second = rotate_mock_credential_references(
        actor=user,
        authorization_id=authorization.id,
        credential_id="mock-credential-rotation-v3",
        token_id="mock-token-rotation-v3",
    )

    assert first.credential_reference_version == stale_version + 1
    assert second.credential_reference_version == stale_version + 2
    assert second.credential_mask == {"credential": "mock-credential-***", "token": "mock-token-***"}
    assert IntegrationAuditLog.objects.filter(
        store_authorization=authorization,
        action="store_authorization.credential_reference_rotated_mock",
    ).count() == 2


@pytest.mark.django_db
def test_six_exact_permissions_cannot_substitute_for_each_other():
    tenant = Tenant.objects.create(name="Tenant", code="exact-permissions")
    for index, granted_code in enumerate(STORE_PERMISSION_CODES):
        user = create_user(tenant, f"exact-user-{index}")
        grant(user, granted_code)
        for checked_code in STORE_PERMISSION_CODES:
            assert user_has_integration_permission(user, checked_code) is (checked_code == granted_code)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "scope",
    (
        {},
        {"platforms": []},
        {"platforms": ["unknown"]},
        {"store_ids": ["invalid"]},
        {"platforms": ["shopee"], "unknown": [1]},
    ),
)
def test_missing_empty_unknown_and_invalid_store_scopes_are_rejected(scope):
    tenant = Tenant.objects.create(name="Tenant", code=f"scope-{len(json.dumps(scope))}-{len(str(scope))}")
    user = create_user(tenant, f"scope-user-{len(json.dumps(scope))}-{len(str(scope))}")
    grant(user, "integrations.store.view", scope=scope)
    response = client_for(user).get("/api/internal/integrations/store-authorizations/")
    assert response.status_code == 403
    assert response.json()["code"] in {"DATA_SCOPE_MISSING", "DATA_SCOPE_INVALID"}


@pytest.mark.django_db
def test_authentication_user_types_and_raw_credential_inputs_are_rejected_without_echo():
    tenant = Tenant.objects.create(name="Tenant", code="boundary-tenant")
    internal = create_user(tenant, "boundary-internal")
    external = create_user(tenant, "boundary-external", CustomUser.UserType.EXTERNAL)
    rpa = create_user(tenant, "boundary-rpa", CustomUser.UserType.RPA)
    grant(external, "integrations.store.view")
    grant(rpa, "integrations.store.view")

    path = "/api/internal/integrations/store-authorizations/"
    assert APIClient().get(path).status_code == 401
    assert client_for(internal).get(path).status_code == 403
    assert client_for(external).get(path).status_code == 403
    assert client_for(rpa).get(path).status_code == 403

    grant(internal, "integrations.manage")
    raw_value = "demo-sensitive-material"
    for field in (
        "credentials",
        "access_token",
        "refresh_token",
        "credential_ciphertext",
        "credential_id",
        "token_id",
    ):
        response = client_for(internal).post(
            "/api/internal/integrations/configs/",
            {
                "platform": "mock",
                "account_alias": f"reject-{field}",
                "environment": "mock",
                "status": "disabled",
                field: raw_value,
            },
            format="json",
        )
        assert response.status_code == 400
        assert raw_value not in json.dumps(response.json())


@pytest.mark.django_db
def test_service_conflicts_and_business_validation_use_409_and_422_contracts():
    tenant = Tenant.objects.create(name="Tenant", code="status-contract")
    user = create_user(tenant, "status-user")
    grant(user, "integrations.store.authorize")
    store, config = create_store_context(tenant, user, "shopee", "status")
    authorization = create_authorization(user, store, config, "status")
    activate_mock_store_authorization(
        actor=user,
        authorization_id=authorization.id,
        credential_id="mock-credential-status",
        token_id="mock-token-status",
    )

    with pytest.raises(StateConflict) as conflict:
        activate_mock_store_authorization(
            actor=user,
            authorization_id=authorization.id,
            credential_id="mock-credential-status-repeat",
            token_id="mock-token-status",
        )
    assert conflict.value.status_code == 409

    other_store, other_config = create_store_context(tenant, user, "shopee", "status-invalid")
    with pytest.raises(BusinessRuleViolation) as invalid:
        create_pending_store_authorization(
            actor=user,
            integration_config=other_config,
            store=other_store,
            platform_store_id="invalid",
            merchant_subject_id="mock-merchant-invalid",
        )
    assert invalid.value.status_code == 422


@pytest.mark.django_db
def test_legacy_ciphertext_and_direct_config_reference_writes_are_blocked():
    tenant = Tenant.objects.create(name="Tenant", code="legacy-guard")
    user = create_user(tenant, "legacy-user")
    with pytest.raises(DjangoValidationError):
        PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="mock",
            account_alias="legacy",
            credential_ciphertext="demo-sensitive-material",
            created_by=user,
        )
    with pytest.raises(DjangoValidationError):
        PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="mock",
            account_alias="reference",
            credential_id="mock-credential-direct-write",
            created_by=user,
        )


def test_legacy_migration_guard_blocks_without_reading_or_printing_values():
    migration = importlib.import_module(
        "apps.integrations.migrations.0007_platformintegrationconfig_credential_id_and_more"
    )

    class GuardedQuery:
        def exclude(self, **kwargs):
            assert kwargs == {"credential_ciphertext": ""}
            return self

        def exists(self):
            return True

    class HistoricalConfig:
        objects = GuardedQuery()

    class HistoricalApps:
        def get_model(self, app_label, model_name):
            assert (app_label, model_name) == ("integrations", "PlatformIntegrationConfig")
            return HistoricalConfig

    with pytest.raises(RuntimeError, match="external credential reference"):
        migration.block_unmigrated_legacy_credentials(HistoricalApps(), None)
