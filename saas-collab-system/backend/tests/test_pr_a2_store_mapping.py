import secrets

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.admin import MarketplaceStoreMappingAdmin
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformIntegrationConfig,
    store_mapping_service_write,
)
from apps.integrations.store_authorization_service import (
    create_store_authorization,
    transition_store_authorization,
)
from apps.integrations.store_mapping_service import create_store_mapping, update_store_mapping
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


MAPPINGS_URL = "/api/internal/integrations/store-mappings/"


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


def mapping_context(code, platform="shopee", activate=True):
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
    authorization = create_store_authorization(
        tenant=tenant,
        integration_config=config,
        store=store,
        platform=platform,
        region="SG",
        platform_store_id=f"demo-store-{code}",
        merchant_subject_id=f"synthetic-{platform}-merchant-{code}",
        shop_cipher=f"synthetic-shop-cipher-{code}" if platform == "tiktok" else "",
        credential_id=f"synthetic-{platform}-credential-{code}",
        token_id=f"synthetic-{platform}-token-{code}",
        scopes=["orders.read"],
        actor=user,
    )
    if activate:
        authorization = transition_store_authorization(
            authorization, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=user
        )
    return tenant, user, store, config, authorization


@pytest.mark.django_db
def test_mapping_write_bypasses_are_blocked():
    tenant, user, store, _config, authorization = mapping_context("map-guard")
    mapping = create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)

    direct = MarketplaceStoreMapping(
        tenant=tenant,
        platform="shopee",
        store=store,
        authorization=authorization,
        platform_store_id="demo-store-map-guard",
        platform_identity_key=authorization.platform_identity_key,
        region="SG",
        mapping_source="manual",
        mapped_by=user,
    )
    with pytest.raises(ValidationError, match="service layer"):
        direct.save()
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreMapping.objects.filter(pk=mapping.pk).update(status="inactive")
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreMapping.objects.bulk_create([direct])
    mapping.currency = "XXX"
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceStoreMapping.objects.bulk_update([mapping], ["currency"])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketplaceStoreMapping.objects.filter(pk=mapping.pk).delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        mapping.delete()

    mapping.refresh_from_db()
    assert mapping.status == MarketplaceStoreMapping.Status.ACTIVE
    assert mapping.currency == ""
    assert MarketplaceStoreMappingAdmin.has_add_permission(None, None) is False
    assert MarketplaceStoreMappingAdmin.has_change_permission(None, None) is False
    assert MarketplaceStoreMappingAdmin.has_delete_permission(None, None) is False


@pytest.mark.django_db
def test_service_derives_identity_from_authorization_and_rejects_invalid_context():
    tenant, user, store, _config, authorization = mapping_context("map-service")
    mapping = create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)
    assert mapping.platform_store_id == authorization.platform_store_id
    assert mapping.platform_identity_key == authorization.platform_identity_key
    assert mapping.region == authorization.region
    assert mapping.mapping_source == MarketplaceStoreMapping.MappingSource.MANUAL
    assert mapping.status == MarketplaceStoreMapping.Status.ACTIVE
    assert mapping.last_verified_at is not None
    assert IntegrationAuditLog.objects.filter(tenant=tenant, action="store_mapping_create").exists()

    from apps.common.exceptions import StateConflict

    with pytest.raises(StateConflict):
        create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)

    _tenant, _user, _store, _config, pending = mapping_context("map-service-pending", activate=False)
    with pytest.raises(ValidationError, match="active authorization"):
        create_store_mapping(tenant=_tenant, actor=_user, store=_store, authorization=pending)

    other_tenant = Tenant.objects.create(name="Tenant map-other", code="map-other")
    other_user = create_user(other_tenant, "user-map-other")
    with pytest.raises(ValidationError, match="actor"):
        create_store_mapping(tenant=tenant, actor=other_user, store=store, authorization=authorization)


@pytest.mark.django_db
def test_create_mapping_api_requires_authorize_permission_and_scopes():
    tenant, user, store, _config, authorization = mapping_context("map-api-perm")
    client = client_for(user)
    payload = {"store_id": store.id, "authorization_id": authorization.id}

    assert client.post(MAPPINGS_URL, payload, format="json").status_code == 403

    grant(user, "integrations.store.view")
    assert client.post(MAPPINGS_URL, payload, format="json").status_code == 403

    grant(user, "integrations.store.authorize")
    response = client.post(MAPPINGS_URL, {**payload, "currency": "sgd", "timezone": "Asia/Singapore"}, format="json")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["platform_store_id"] == authorization.platform_store_id
    assert data["currency"] == "SGD"
    assert data["status"] == "active"
    assert data["mapping_source"] == "manual"
    assert "platform_subject_id" not in data
    assert "platform_identity_key" not in data

    duplicate = client.post(MAPPINGS_URL, payload, format="json")
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "STATE_CONFLICT"


@pytest.mark.django_db
def test_create_mapping_api_rejects_forbidden_identity_fields_and_raw_credentials():
    tenant, user, store, _config, authorization = mapping_context("map-api-forbid")
    grant(user, "integrations.store.authorize")
    client = client_for(user)

    identity = client.post(
        MAPPINGS_URL,
        {"store_id": store.id, "authorization_id": authorization.id, "platform_store_id": "forged-store"},
        format="json",
    )
    assert identity.status_code == 400
    assert identity.json()["code"] == "VALIDATION_ERROR"

    tenant_field = client.post(
        MAPPINGS_URL,
        {"store_id": store.id, "authorization_id": authorization.id, "tenant_id": 999},
        format="json",
    )
    assert tenant_field.status_code == 400

    raw = client.post(
        MAPPINGS_URL,
        {"store_id": store.id, "authorization_id": authorization.id, "access_token": "raw"},
        format="json",
    )
    assert raw.status_code == 422
    assert raw.json()["code"] == "BUSINESS_RULE_VIOLATION"
    assert not MarketplaceStoreMapping.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_mapping_detail_cross_tenant_hidden_and_scoped_read():
    tenant, _owner, store, _config, authorization = mapping_context("map-owner")
    mapping = create_store_mapping(tenant=tenant, actor=_owner, store=store, authorization=authorization)

    other_tenant = Tenant.objects.create(name="Tenant map-intruder", code="map-intruder")
    intruder = create_user(other_tenant, "user-map-intruder")
    grant(intruder, "integrations.store.view")
    grant(intruder, "integrations.store.authorize")
    intruder_client = client_for(intruder)

    assert intruder_client.get(f"{MAPPINGS_URL}{mapping.id}/").status_code == 404
    assert intruder_client.patch(f"{MAPPINGS_URL}{mapping.id}/", {"status": "inactive"}, format="json").status_code == 404

    grant(_owner, "integrations.store.view")
    listing = client_for(_owner).get(MAPPINGS_URL)
    assert listing.status_code == 200
    assert listing.json()["data"]["count"] == 1


@pytest.mark.django_db
def test_update_mapping_deactivates_with_masked_audit():
    tenant, user, store, _config, authorization = mapping_context("map-update")
    mapping = create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)
    grant(user, "integrations.store.authorize")
    grant(user, "integrations.store.view")
    client = client_for(user)

    empty = client.patch(f"{MAPPINGS_URL}{mapping.id}/", {}, format="json")
    assert empty.status_code == 400

    response = client.patch(
        f"{MAPPINGS_URL}{mapping.id}/",
        {"status": "inactive", "currency": "USD"},
        format="json",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "inactive"
    assert data["currency"] == "USD"

    mapping.refresh_from_db()
    assert mapping.status == MarketplaceStoreMapping.Status.INACTIVE
    audit = IntegrationAuditLog.objects.get(tenant=tenant, action="store_mapping_update")
    assert audit.result == IntegrationAuditLog.Result.SUCCESS
    assert audit.masked_detail["changed"]["status"] == "inactive"
    assert audit.masked_detail["previous"]["status"] == "active"

    invalid_currency = client.patch(f"{MAPPINGS_URL}{mapping.id}/", {"currency": "TOOLONG"}, format="json")
    assert invalid_currency.status_code == 400


@pytest.mark.django_db
def test_query_filters_and_unknown_params_are_rejected():
    tenant, user, store, _config, authorization = mapping_context("map-query")
    create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)
    grant(user, "integrations.store.view")
    client = client_for(user)

    assert client.get(MAPPINGS_URL + "?unknown=1").status_code == 400
    assert client.get(MAPPINGS_URL + "?platform=bigseller").status_code == 400
    assert client.get(MAPPINGS_URL + "?status=weird").status_code == 400

    filtered = client.get(MAPPINGS_URL + "?platform=shopee&status=active")
    assert filtered.status_code == 200
    assert filtered.json()["data"]["count"] == 1

    missing = client.get(f"{MAPPINGS_URL}999999/")
    assert missing.status_code == 404
    assert missing.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db
def test_service_update_requires_active_authorization_to_reactivate():
    tenant, user, store, _config, authorization = mapping_context("map-reactivate")
    mapping = create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)
    mapping = update_store_mapping(mapping, actor=user, status=MarketplaceStoreMapping.Status.INACTIVE)
    transition_store_authorization(
        authorization, target_status=MarketplaceStoreAuthorization.Status.REVOKED, actor=user
    )
    authorization.refresh_from_db()

    with pytest.raises(ValidationError, match="active authorization"):
        update_store_mapping(mapping, actor=user, status=MarketplaceStoreMapping.Status.ACTIVE)
    mapping.refresh_from_db()
    assert mapping.status == MarketplaceStoreMapping.Status.INACTIVE
