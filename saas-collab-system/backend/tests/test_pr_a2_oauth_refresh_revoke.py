import secrets

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
)
from apps.integrations.store_authorization_service import (
    create_store_authorization,
    transition_store_authorization,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def grant(user, permission_code, scope_type=DataScope.ScopeType.ALL, config=None):
    suffix = secrets.token_hex(3)
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"Role {permission_code} {user.id} {suffix}",
        code=f"role-{user.id}-{permission_code.replace('.', '-')}-{suffix}",
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


def active_authorization(code, platform="shopee"):
    tenant = Tenant.objects.create(name=f"Tenant {code}", code=code)
    user = create_user(tenant, f"user-{code}")
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
    record = create_store_authorization(
        tenant=tenant,
        integration_config=config,
        store=store,
        platform=platform,
        region="SG",
        platform_store_id=f"demo-store-{code}",
        merchant_subject_id=f"synthetic-{platform}-merchant-demo-store-{code}",
        shop_cipher=f"synthetic-shop-cipher-{code}" if platform == "tiktok" else "",
        credential_id=f"synthetic-{platform}-credential-demo-store-{code}",
        token_id=f"synthetic-{platform}-token-demo-store-{code}",
        scopes=["orders.read"],
        actor=user,
    )
    record = transition_store_authorization(
        record, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=user
    )
    return tenant, user, record


def refresh_url(record):
    return f"/api/internal/integrations/store-authorizations/{record.id}/refresh/"


def revoke_url(record):
    return f"/api/internal/integrations/store-authorizations/{record.id}/revoke/"


@pytest.mark.django_db
def test_refresh_requires_both_authorizer_and_rotator_permissions():
    _tenant, user, record = active_authorization("rf-perm")
    client = client_for(user)

    assert client.post(refresh_url(record), {}, format="json").status_code == 403

    grant(user, "integrations.store.authorize")
    assert client.post(refresh_url(record), {}, format="json").status_code == 403

    grant(user, "integrations.credential.rotate")
    response = client.post(refresh_url(record), {}, format="json")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["credential_reference_version"] == 2
    assert data["credential_mask"]["credential"].startswith("synthetic-")
    assert data["status"] == MarketplaceStoreAuthorization.Status.ACTIVE
    assert data["refreshed_at"]

    record.refresh_from_db()
    assert record.credential_id.endswith("-v2")
    assert record.token_id.endswith("-v2")
    assert IntegrationAuditLog.objects.filter(
        tenant=record.tenant, action="rotate_reference", result=IntegrationAuditLog.Result.SUCCESS
    ).exists()
    assert record.credential_reference_version == 2


@pytest.mark.django_db
def test_refresh_rejects_raw_credential_payload():
    _tenant, user, record = active_authorization("rf-raw")
    grant(user, "integrations.store.authorize")
    grant(user, "integrations.credential.rotate")

    response = client_for(user).post(refresh_url(record), {"refresh_token": "raw"}, format="json")

    assert response.status_code == 422
    assert response.json()["code"] == "BUSINESS_RULE_VIOLATION"
    record.refresh_from_db()
    assert record.credential_reference_version == 1


@pytest.mark.django_db
def test_revoke_transitions_to_terminal_state_and_is_idempotent():
    tenant, user, record = active_authorization("rv-basic")
    grant(user, "integrations.store.revoke")
    client = client_for(user)

    response = client.post(revoke_url(record), {}, format="json")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["idempotent"] is False
    assert payload["authorization"]["status"] == MarketplaceStoreAuthorization.Status.REVOKED
    assert payload["authorization"]["revoked_at"]

    record.refresh_from_db()
    assert record.status == MarketplaceStoreAuthorization.Status.REVOKED

    repeat = client.post(revoke_url(record), {}, format="json")
    assert repeat.status_code == 200
    assert repeat.json()["data"]["idempotent"] is True
    assert repeat.json()["data"]["authorization"]["status"] == MarketplaceStoreAuthorization.Status.REVOKED
    assert IntegrationAuditLog.objects.filter(
        tenant=tenant, action="revoke", result=IntegrationAuditLog.Result.SUCCESS
    ).count() == 2


@pytest.mark.django_db
def test_refresh_revoked_authorization_is_conflict():
    _tenant, user, record = active_authorization("rf-after-revoke")
    grant(user, "integrations.store.revoke")
    grant(user, "integrations.store.authorize")
    grant(user, "integrations.credential.rotate")
    client = client_for(user)
    assert client.post(revoke_url(record), {}, format="json").status_code == 200

    response = client.post(refresh_url(record), {}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    record.refresh_from_db()
    assert record.status == MarketplaceStoreAuthorization.Status.REVOKED


@pytest.mark.django_db
def test_refresh_and_revoke_cross_tenant_records_are_hidden():
    _tenant, _owner, record = active_authorization("rv-cross")
    other_tenant = Tenant.objects.create(name="Tenant rv-other", code="rv-other")
    intruder = create_user(other_tenant, "user-rv-other")
    grant(intruder, "integrations.store.authorize")
    grant(intruder, "integrations.credential.rotate")
    grant(intruder, "integrations.store.revoke")
    client = client_for(intruder)

    refresh = client.post(refresh_url(record), {}, format="json")
    assert refresh.status_code == 404
    assert refresh.json()["code"] == "RESOURCE_NOT_FOUND"
    revoke = client.post(revoke_url(record), {}, format="json")
    assert revoke.status_code == 404

    record.refresh_from_db()
    assert record.status == MarketplaceStoreAuthorization.Status.ACTIVE
    assert record.credential_reference_version == 1


@pytest.mark.django_db
def test_revoke_requires_permission_and_rejects_raw_payload():
    _tenant, user, record = active_authorization("rv-guard")

    forbidden = client_for(user).post(revoke_url(record), {}, format="json")
    assert forbidden.status_code == 403

    grant(user, "integrations.store.revoke")
    raw = client_for(user).post(revoke_url(record), {"access_token": "raw"}, format="json")
    assert raw.status_code == 422
    record.refresh_from_db()
    assert record.status == MarketplaceStoreAuthorization.Status.ACTIVE
