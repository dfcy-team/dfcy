from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.configcenter.models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion
from apps.configcenter.services import approve_config_version, create_config_version, rollback_config_version
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, code):
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.id}")
    role.permissions.add(Permission.objects.get(code=code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def definition(key="inventory.safety_days", *, scope="tenant", value_type="integer", sensitive=False, approval=False):
    return SystemConfigDefinition.objects.create(
        config_key=key,
        scope_type=scope,
        value_type=value_type,
        default_value=None if sensitive else 7,
        is_sensitive=sensitive,
        requires_approval=approval,
        description="Demo configuration only.",
    )


@pytest.mark.django_db
def test_config_versions_increment_and_supersede_effective_values():
    tenant = Tenant.objects.create(name="Tenant", code="config-version")
    actor = create_user(tenant, "config-manager")
    grant(actor, "config.manage")
    item = definition()
    now = timezone.now()

    first = create_config_version(definition=item, actor=actor, value=7, effective_at=now)
    second = create_config_version(definition=item, actor=actor, value=10, effective_at=now)

    first.refresh_from_db()
    assert first.status == TenantConfigVersion.Status.SUPERSEDED
    assert second.version == 2
    assert second.status == TenantConfigVersion.Status.EFFECTIVE
    assert second.scope_key == f"tenant:{tenant.id}"
    assert ConfigChangeLog.objects.filter(tenant=tenant, config_key=item.config_key).count() == 2


@pytest.mark.django_db
def test_config_approval_requires_separate_authorized_actor():
    tenant = Tenant.objects.create(name="Tenant", code="config-approval")
    creator = create_user(tenant, "creator")
    approver = create_user(tenant, "approver")
    grant(creator, "config.manage")
    grant(creator, "config.approve")
    grant(approver, "config.approve")
    item = definition(key="lifecycle.high_risk_threshold", approval=True)
    version = create_config_version(definition=item, actor=creator, value=5, effective_at=timezone.now())
    assert version.status == TenantConfigVersion.Status.PENDING_APPROVAL

    with pytest.raises(ValidationError, match="creator cannot approve"):
        approve_config_version(version=version, actor=creator)
    version = approve_config_version(version=version, actor=approver)
    assert version.status == TenantConfigVersion.Status.EFFECTIVE
    assert version.approved_by == approver


@pytest.mark.django_db
def test_config_stale_pending_version_cannot_override_latest_version():
    tenant = Tenant.objects.create(name="Tenant", code="config-stale-approval")
    creator = create_user(tenant, "creator-stale")
    approver = create_user(tenant, "approver-stale")
    grant(creator, "config.manage")
    grant(approver, "config.approve")
    item = definition(key="lifecycle.review_threshold", approval=True)
    stale = create_config_version(definition=item, actor=creator, value=5, effective_at=timezone.now())
    latest = create_config_version(definition=item, actor=creator, value=8, effective_at=timezone.now())

    with pytest.raises(ValidationError, match="latest config version"):
        approve_config_version(version=stale, actor=approver)
    latest = approve_config_version(version=latest, actor=approver)
    assert latest.status == TenantConfigVersion.Status.EFFECTIVE
    stale.refresh_from_db()
    assert stale.status == TenantConfigVersion.Status.PENDING_APPROVAL


@pytest.mark.django_db
def test_config_rollback_creates_new_version_without_mutating_history():
    tenant = Tenant.objects.create(name="Tenant", code="config-rollback")
    actor = create_user(tenant, "rollback-manager")
    grant(actor, "config.manage")
    grant(actor, "config.rollback")
    item = definition(key="inventory.overstock_days")
    first = create_config_version(definition=item, actor=actor, value=45, effective_at=timezone.now())
    create_config_version(definition=item, actor=actor, value=60, effective_at=timezone.now())

    rolled_back = rollback_config_version(target_version=first, actor=actor)

    first.refresh_from_db()
    assert rolled_back.version == 3
    assert rolled_back.value == 45
    assert first.version == 1
    assert ConfigChangeLog.objects.get(action=ConfigChangeLog.Action.ROLLBACK).from_version == 1


@pytest.mark.django_db
def test_sensitive_config_is_placeholder_only_and_masked_in_api():
    tenant = Tenant.objects.create(name="Tenant", code="config-sensitive")
    actor = create_user(tenant, "sensitive-manager")
    viewer = create_user(tenant, "sensitive-viewer")
    grant(actor, "config.manage")
    grant(viewer, "config.view")
    item = definition(key="restricted.integration_reference", value_type="json", sensitive=True)
    with pytest.raises(ValidationError, match="placeholder reference"):
        create_config_version(definition=item, actor=actor, value={"reference": "real://credential"}, effective_at=timezone.now())
    version = create_config_version(
        definition=item,
        actor=actor,
        value={"reference": "placeholder://not-configured", "masked_metadata": {"provider": "demo"}},
        effective_at=timezone.now(),
    )

    response = client_for(viewer).get("/api/internal/config/values/")
    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["id"] == version.id
    assert response.json()["data"]["items"][0]["value"] == "***"
    assert "placeholder" not in str(ConfigChangeLog.objects.get().masked_detail)


@pytest.mark.django_db
@pytest.mark.parametrize("key", ["platform.api_key", "shop-token", "browser.cookie", "auth.session", "bank.password"])
def test_config_definition_rejects_credential_key_types(key):
    with pytest.raises(ValidationError, match="prohibited"):
        definition(key=key)


@pytest.mark.django_db
def test_config_rejects_credential_values_and_direct_persistence_bypass():
    tenant = Tenant.objects.create(name="Tenant", code="config-guard")
    actor = create_user(tenant, "guard-manager")
    grant(actor, "config.manage")
    item = definition(key="report.display_options", value_type="json")
    with pytest.raises(ValidationError, match="prohibited"):
        create_config_version(
            definition=item,
            actor=actor,
            value={"api_secret": "not-a-real-secret"},
            effective_at=timezone.now(),
        )
    forged = TenantConfigVersion(
        tenant=tenant, definition=item, config_key=item.config_key, scope_key=f"tenant:{tenant.id}",
        version=1, value={}, status=TenantConfigVersion.Status.EFFECTIVE,
        effective_at=timezone.now(), created_by=actor,
    )
    with pytest.raises(ValidationError, match="version service"):
        forged.save()
    forged_log = ConfigChangeLog(
        tenant=tenant, config_key=item.config_key, scope_key=f"tenant:{tenant.id}",
        to_version=1, actor=actor, action=ConfigChangeLog.Action.CREATE_VERSION,
    )
    with pytest.raises(ValidationError, match="config service"):
        forged_log.save()


@pytest.mark.django_db
def test_system_config_requires_system_permission_and_is_visible_only_to_system_manager():
    tenant = Tenant.objects.create(name="Tenant", code="config-system")
    manager = create_user(tenant, "tenant-manager")
    system_manager = create_user(tenant, "system-manager")
    viewer = create_user(tenant, "viewer")
    for user in (manager, system_manager):
        grant(user, "config.manage")
    grant(system_manager, "config.system.manage")
    grant(system_manager, "config.view")
    grant(viewer, "config.view")
    item = definition(key="system.minimum_safety_days", scope="system")
    with pytest.raises(PermissionDenied, match="System configuration"):
        create_config_version(definition=item, actor=manager, value=3, effective_at=timezone.now())
    version = create_config_version(definition=item, actor=system_manager, value=3, effective_at=timezone.now())
    assert version.tenant is None
    assert client_for(viewer).get("/api/internal/config/values/").json()["data"]["items"] == []
    assert client_for(system_manager).get("/api/internal/config/values/").json()["data"]["items"][0]["scope_key"] == "system"


@pytest.mark.django_db
def test_config_api_tenant_isolation_and_action_permissions():
    tenant = Tenant.objects.create(name="Tenant", code="config-api")
    other = Tenant.objects.create(name="Other", code="config-api-other")
    manager = create_user(tenant, "manager")
    other_manager = create_user(other, "other-manager")
    viewer = create_user(tenant, "viewer")
    grant(manager, "config.manage")
    grant(other_manager, "config.manage")
    grant(viewer, "config.view")
    item = definition(key="inventory.api_safety_days")
    own = create_config_version(definition=item, actor=manager, value=7, effective_at=timezone.now())
    create_config_version(definition=item, actor=other_manager, value=9, effective_at=timezone.now())

    response = client_for(viewer).get("/api/internal/config/values/")
    assert [row["id"] for row in response.json()["data"]["items"]] == [own.id]
    payload = {"config_key": item.config_key, "value": 10, "effective_at": str(timezone.now())}
    assert client_for(viewer).post("/api/internal/config/values/", payload, format="json").status_code == 403
    assert client_for(manager).post("/api/internal/config/values/", payload, format="json").status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_config_api_rejects_external_and_rpa(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"config-deny-{user_type}")
    user = create_user(tenant, f"deny-{user_type}", user_type)
    grant(user, "config.view")
    assert client_for(user).get("/api/internal/config/values/").status_code == 403
