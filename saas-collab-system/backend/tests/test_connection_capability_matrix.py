import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    ConnectionCapability, MarketplaceStoreAuthorization, PlatformIntegrationConfig,
    authorization_service_write, marketplace_identity_key, marketplace_store_binding_key,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def grant(user, *codes):
    role = Role.objects.create(tenant=user.tenant, code=f"role-{user.username}", name=f"Role {user.username}")
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code, "module": "integrations", "action": code.rsplit(".", 1)[-1]}
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def make_authorization(code="capability", status=MarketplaceStoreAuthorization.Status.ACTIVE):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(username=f"{code}-user", password="not-real", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="shop", name="Shop", country_code="PH", currency="PHP")
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="shopee", account_alias="test", created_by=user,
    )
    external_store_id = f"external-{code}"
    identity = marketplace_identity_key("shopee", "PH", external_store_id)
    authorization = MarketplaceStoreAuthorization(
        tenant=tenant, integration_config=config, store=store, platform="shopee", region="PH",
        platform_store_id=external_store_id, platform_identity_key=identity,
        active_platform_identity_key=None if status == MarketplaceStoreAuthorization.Status.REVOKED else identity,
        active_store_binding_key=None if status == MarketplaceStoreAuthorization.Status.REVOKED else marketplace_store_binding_key(tenant.id, "shopee", store.id),
        merchant_subject_id="merchant", credential_id="credential-ref", token_id="token-ref",
        status=status, created_by=user, updated_by=user,
    )
    with authorization_service_write():
        authorization.save()
    return tenant, user, authorization


def test_capability_matrix_upsert_is_idempotent_and_write_is_fail_closed():
    _, user, authorization = make_authorization()
    grant(user, "integrations.store.view", "integrations.store.authorize")
    client = APIClient(); client.force_authenticate(user)
    url = f"/api/internal/integrations/store-authorizations/{authorization.id}/capabilities/"
    payload = {"capabilities": [{
        "capability_code": "ORDER", "read_enabled": True, "write_enabled": False,
        "sync_mode": "scheduled", "source_priority": 10, "status": "active",
    }]}
    first = client.put(url, payload, format="json")
    second = client.put(url, payload, format="json")
    assert first.status_code == second.status_code == 200
    assert ConnectionCapability.objects.filter(authorization=authorization, capability_code="ORDER").count() == 1
    assert first.data["data"]["available_codes"] == list(ConnectionCapability.CapabilityCode.values)
    suggestions = {item["capability_code"]: item for item in first.data["data"]["suggestions"]}
    assert set(suggestions) == {"ORDER", "RETURN_REFUND"}
    assert suggestions["ORDER"]["read_enabled"] is True
    assert suggestions["ORDER"]["write_enabled"] is False
    assert suggestions["ORDER"]["scope_verification"] == "unverified"
    assert first.data["data"]["results"][0]["read_enabled"] is True

    payload["capabilities"][0]["write_enabled"] = True
    assert client.put(url, payload, format="json").status_code == 400
    payload["capabilities"][0] = {"capability_code": "UNKNOWN"}
    assert client.put(url, payload, format="json").status_code == 400


def test_capability_matrix_is_tenant_scoped_and_revoked_authorization_cannot_activate():
    _, owner, authorization = make_authorization("owner")
    _, outsider, _ = make_authorization("outsider")
    grant(owner, "integrations.store.view")
    grant(outsider, "integrations.store.view")
    client = APIClient(); client.force_authenticate(outsider)
    url = f"/api/internal/integrations/store-authorizations/{authorization.id}/capabilities/"
    assert client.get(url).status_code == 404

    _, _, revoked = make_authorization("revoked", MarketplaceStoreAuthorization.Status.REVOKED)
    item = ConnectionCapability(
        authorization=revoked, capability_code="ORDER", read_enabled=True, status=ConnectionCapability.Status.ACTIVE,
    )
    with pytest.raises(DjangoValidationError):
        item.full_clean()
