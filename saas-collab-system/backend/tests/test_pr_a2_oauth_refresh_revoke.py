import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
)
from apps.integrations.store_authorization_service import (
    create_store_authorization,
    rotate_store_authorization_references,
    transition_store_authorization,
)
from apps.common.exceptions import StateConflict
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


@pytest.mark.django_db
def test_reauthorization_creates_new_record_and_reference_after_revoke():
    tenant, user, record = active_authorization("reauthorize")
    revoked = transition_store_authorization(
        record,
        target_status=MarketplaceStoreAuthorization.Status.REVOKED,
        actor=user,
    )

    replacement = create_store_authorization(
        tenant=tenant,
        integration_config=revoked.integration_config,
        store=revoked.store,
        platform=revoked.platform,
        region=revoked.region,
        platform_store_id=revoked.platform_store_id,
        merchant_subject_id=revoked.merchant_subject_id,
        shop_cipher=revoked.shop_cipher,
        credential_id="synthetic-shopee-credential-reauthorize-new",
        token_id="synthetic-shopee-token-reauthorize-new",
        scopes=revoked.scopes,
        actor=user,
    )
    replacement = transition_store_authorization(
        replacement,
        target_status=MarketplaceStoreAuthorization.Status.ACTIVE,
        actor=user,
    )

    revoked.refresh_from_db()
    assert revoked.active_platform_identity_key is None
    assert revoked.active_store_binding_key is None
    assert replacement.pk != revoked.pk
    assert replacement.credential_id != revoked.credential_id
    assert MarketplaceStoreAuthorization.objects.filter(tenant=tenant).count() == 2


@pytest.mark.django_db
def test_live_refresh_version_conflict_revokes_losing_new_reference():
    _tenant, user, record = active_authorization("live-race")
    revoked = []

    def revoke(credential_id, token_id):
        revoked.append((credential_id, token_id))
        return {"status": "revoked", "error_code": ""}

    first = rotate_store_authorization_references(
        record,
        credential_id="custody:credential:live-race-0002",
        token_id="custody:token:live-race-0002",
        credential_mask={"credential": "custody-***", "token": "custody-***"},
        version=2,
        actor=user,
        allow_live_references=True,
        revoker=revoke,
        new_reference_revoker=revoke,
    )
    assert first.credential_reference_version == 2

    with pytest.raises(StateConflict):
        rotate_store_authorization_references(
            record,
            credential_id="custody:credential:live-race-loser",
            token_id="custody:token:live-race-loser",
            credential_mask={"credential": "custody-***", "token": "custody-***"},
            version=2,
            actor=user,
            allow_live_references=True,
            revoker=revoke,
            new_reference_revoker=revoke,
        )
    assert ("custody:credential:live-race-loser", "custody:token:live-race-loser") in revoked
    first.refresh_from_db()
    assert first.credential_reference_version == 2


@pytest.mark.django_db
def test_live_refresh_old_reference_revoke_failure_is_not_reported_success():
    tenant, user, record = active_authorization("live-revoke-failure")

    def fail_old(credential_id, token_id):
        return {"status": "failed", "error_code": "CUSTODY_REVOCATION_FAILED"}

    with pytest.raises(StateConflict):
        rotate_store_authorization_references(
            record,
            credential_id="custody:credential:revoke-failure-0002",
            token_id="custody:token:revoke-failure-0002",
            credential_mask={"credential": "custody-***", "token": "custody-***"},
            version=2,
            actor=user,
            allow_live_references=True,
            revoker=fail_old,
            new_reference_revoker=lambda credential_id, token_id: {"status": "revoked"},
        )

    record.refresh_from_db()
    assert record.status == MarketplaceStoreAuthorization.Status.ERROR
    assert record.last_error_code == "CUSTODY_REVOCATION_FAILED"
    assert IntegrationAuditLog.objects.filter(
        tenant=tenant,
        action="rotate_reference",
        result=IntegrationAuditLog.Result.FAILED,
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_live_refresh_allows_one_mysql_commit_and_revokes_loser():
    if connection.vendor != "mysql":
        pytest.skip("MySQL live-reference row-lock verification runs in Local Sandbox.")
    _tenant, user, record = active_authorization("live-mysql-race")
    start = threading.Event()
    previous_revocations = []
    losing_revocations = []

    def revoke_previous(credential_id, token_id):
        previous_revocations.append((credential_id, token_id))
        return {"status": "revoked", "error_code": ""}

    def rotate(suffix):
        close_old_connections()
        start.wait(timeout=5)
        try:
            current = MarketplaceStoreAuthorization.objects.get(pk=record.pk)
            actor = CustomUser.objects.get(pk=user.pk)

            def revoke_new(credential_id, token_id):
                losing_revocations.append((credential_id, token_id))
                return {"status": "revoked", "error_code": ""}

            rotate_store_authorization_references(
                current,
                credential_id=f"custody:credential:live-mysql-race-{suffix}",
                token_id=f"custody:token:live-mysql-race-{suffix}",
                credential_mask={"credential": "custody-***", "token": "custody-***"},
                version=2,
                actor=actor,
                allow_live_references=True,
                revoker=revoke_previous,
                new_reference_revoker=revoke_new,
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
    assert len(previous_revocations) == 1
    assert len(losing_revocations) == 1
    record.refresh_from_db()
    assert record.credential_reference_version == 2
