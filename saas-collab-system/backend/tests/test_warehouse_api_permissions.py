import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
    WarehouseAuthorization,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.permissions.catalog import PERMISSION_DEFINITIONS
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.ui_p6_scopes import (
    filter_sync_jobs,
    filter_sync_runs,
    filter_warehouse_authorizations,
)
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster, WarehouseMaster
from apps.tenants.models import Tenant


MIGRATION = importlib.import_module(
    "apps.permissions.migrations.0040_register_warehouse_api_authorization_permissions"
)
WAREHOUSE_PERMISSION_CODES = {
    "integrations.warehouse.view",
    "integrations.warehouse.authorize",
    "integrations.warehouse.revoke",
}
WAREHOUSE_ADMIN_DEPENDENCY_CODES = {
    "integrations.view",
    "integrations.manage",
    "integrations.run_live_readonly",
    "integrations.credential.rotate",
}
STORE_PERMISSION_CODES = {
    "integrations.store.view",
    "integrations.store.authorize",
    "integrations.store.revoke",
}


def _grant(user, permission_codes, *, scope_config, scope_type=DataScope.ScopeType.CUSTOM):
    role_suffix = Role.objects.filter(tenant=user.tenant).count() + 1
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"Warehouse scoped {user.username}",
        code=f"warehouse-scoped-{user.username}-{user.id}-{role_suffix}",
        status=Role.Status.ACTIVE,
    )
    permissions = []
    for code in permission_codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={
                "name": code,
                "module": "integrations",
                "action": code.rsplit(".", 1)[-1],
            },
        )
        permissions.append(permission)
    role.permissions.add(*permissions)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config,
    )
    return role


def _warehouse_scope_fixture():
    tenant = Tenant.objects.create(name="Warehouse scope tenant", code="warehouse-scope-tenant")
    user = CustomUser.objects.create_user(
        username="warehouse-scope-user",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    warehouse_platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="myjf",
        name="马来极风",
        platform_type="warehouse_third_party",
        status=StatusChoices.ACTIVE,
    )
    shopee_platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
        status=StatusChoices.ACTIVE,
    )
    warehouse_my = WarehouseMaster.objects.create(
        tenant=tenant,
        code="scope-my-warehouse",
        name="MY warehouse",
        country_code="MY",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        service_platform=warehouse_platform,
        status=StatusChoices.ACTIVE,
    )
    warehouse_sg = WarehouseMaster.objects.create(
        tenant=tenant,
        code="scope-sg-warehouse",
        name="SG warehouse",
        country_code="SG",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        service_platform=warehouse_platform,
        status=StatusChoices.ACTIVE,
    )
    now = timezone.now()
    with authorization_service_write():
        config_allowed = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="MY pilot inventory",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["MY"],
            platform_config={"api_type": "inventory"},
            credential_id="scope-credential-my",
            token_id="scope-token-my",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
        config_production = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="MY production inventory",
            environment=PlatformIntegrationConfig.Environment.PRODUCTION,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["MY"],
            platform_config={"api_type": "inventory"},
            credential_id="scope-credential-production",
            token_id="scope-token-production",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
        config_sg = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="SG pilot inventory",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["SG"],
            platform_config={"api_type": "inventory"},
            credential_id="scope-credential-sg",
            token_id="scope-token-sg",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
        config_other_platform = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="shopee",
            account_alias="Shopee pilot",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["MY"],
            platform_config={"api_type": "marketplace"},
            credential_id="scope-credential-shopee",
            token_id="scope-token-shopee",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
        auth_allowed = WarehouseAuthorization.objects.create(
            tenant=tenant,
            integration_config=config_allowed,
            warehouse=warehouse_my,
            provider="jifeng_wms",
            credential_id="scope-credential-my",
            token_id="scope-token-my",
            credential_mask={"token": "********"},
            status=WarehouseAuthorization.Status.ACTIVE,
            authorized_at=now,
            created_by=user,
            updated_by=user,
        )
        auth_production = WarehouseAuthorization.objects.create(
            tenant=tenant,
            integration_config=config_production,
            warehouse=warehouse_my,
            provider="jifeng_wms",
            credential_id="scope-credential-production",
            token_id="scope-token-production",
            credential_mask={"token": "********"},
            status=WarehouseAuthorization.Status.ACTIVE,
            authorized_at=now,
            created_by=user,
            updated_by=user,
        )
        auth_sg = WarehouseAuthorization.objects.create(
            tenant=tenant,
            integration_config=config_sg,
            warehouse=warehouse_sg,
            provider="jifeng_wms",
            credential_id="scope-credential-sg",
            token_id="scope-token-sg",
            credential_mask={"token": "********"},
            status=WarehouseAuthorization.Status.ACTIVE,
            authorized_at=now,
            created_by=user,
            updated_by=user,
        )
        auth_other_platform = WarehouseAuthorization.objects.create(
            tenant=tenant,
            integration_config=config_other_platform,
            warehouse=warehouse_my,
            provider="shopee",
            credential_id="scope-credential-shopee",
            token_id="scope-token-shopee",
            credential_mask={"token": "********"},
            status=WarehouseAuthorization.Status.ACTIVE,
            authorized_at=now,
            created_by=user,
            updated_by=user,
        )
    return {
        "tenant": tenant,
        "user": user,
        "warehouse_my": warehouse_my,
        "warehouse_sg": warehouse_sg,
        "config_allowed": config_allowed,
        "config_production": config_production,
        "config_sg": config_sg,
        "config_other_platform": config_other_platform,
        "auth_allowed": auth_allowed,
        "auth_production": auth_production,
        "auth_sg": auth_sg,
        "auth_other_platform": auth_other_platform,
        "shopee_platform": shopee_platform,
    }


@pytest.mark.django_db
def test_warehouse_api_permissions_are_catalogued_and_granted_to_active_administrator():
    definitions = {item["code"]: item for item in PERMISSION_DEFINITIONS}
    assert WAREHOUSE_PERMISSION_CODES <= definitions.keys()

    tenant = Tenant.objects.create(name="Warehouse permission tenant", code="warehouse-permission-tenant")
    administrator = Role.objects.create(
        tenant=tenant,
        name="系统管理员",
        code="administrator",
        status=Role.Status.ACTIVE,
    )
    ordinary = Role.objects.create(
        tenant=tenant,
        name="仓库查看员",
        code="warehouse_viewer",
        status=Role.Status.ACTIVE,
    )
    Permission.objects.filter(code__in=WAREHOUSE_PERMISSION_CODES).delete()

    MIGRATION.register_warehouse_api_permissions(django_apps, None)

    administrator_codes = set(administrator.permissions.values_list("code", flat=True))
    assert WAREHOUSE_PERMISSION_CODES <= administrator_codes
    assert STORE_PERMISSION_CODES <= administrator_codes
    assert WAREHOUSE_ADMIN_DEPENDENCY_CODES <= administrator_codes
    assert not WAREHOUSE_PERMISSION_CODES & set(ordinary.permissions.values_list("code", flat=True))
    assert DataScope.objects.filter(
        tenant=tenant,
        role=administrator,
        scope_type=DataScope.ScopeType.ALL,
        config={},
    ).exists()


@pytest.mark.django_db
def test_warehouse_authorization_custom_scope_applies_all_dimensions_and_inventory_resource():
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    queryset = WarehouseAuthorization.objects.filter(tenant=user.tenant)
    role = _grant(
        user,
        ("integrations.warehouse.view",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "integration_config_ids": [fixture["config_allowed"].id],
            "resource_types": ["inventory_snapshot"],
            "warehouse_ids": [fixture["warehouse_my"].id],
        },
    )

    scoped = filter_warehouse_authorizations(user, queryset, "integrations.warehouse.view")
    assert list(scoped.values_list("id", flat=True)) == [fixture["auth_allowed"].id]

    # Each legal dimension is independently meaningful; in particular, a
    # region/environment-only scope is applicable and does not fail closed as
    # a missing scope.
    scope = DataScope.objects.get(role=role)
    scope.config = {"regions": ["MY"]}
    scope.save(update_fields=["config"])
    assert set(filter_warehouse_authorizations(user, queryset, "integrations.warehouse.view").values_list("id", flat=True)) == {
        fixture["auth_allowed"].id,
        fixture["auth_production"].id,
        fixture["auth_other_platform"].id,
    }

    scope.config = {"environments": ["pilot"]}
    scope.save(update_fields=["config"])
    assert set(filter_warehouse_authorizations(user, queryset, "integrations.warehouse.view").values_list("id", flat=True)) == {
        fixture["auth_allowed"].id,
        fixture["auth_sg"].id,
        fixture["auth_other_platform"].id,
    }

    scope.config = {"resource_types": ["sales_order"]}
    scope.save(update_fields=["config"])
    assert not filter_warehouse_authorizations(user, queryset, "integrations.warehouse.view").exists()


@pytest.mark.django_db
def test_ordinary_role_subject_access_returns_only_exact_warehouse_config_and_sync_job_state():
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    _grant(
        user,
        ("masterdata.view",),
        scope_type=DataScope.ScopeType.ALL,
        scope_config={},
    )
    _grant(
        user,
        ("integrations.view",),
        scope_config={"platforms": ["jifeng_wms"], "resource_types": ["inventory_snapshot"]},
    )
    _grant(
        user,
        ("integrations.warehouse.view",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "integration_config_ids": [fixture["config_allowed"].id],
            "resource_types": ["inventory_snapshot"],
            "warehouse_ids": [fixture["warehouse_my"].id],
        },
    )
    sync_job = SyncJob.objects.create(
        tenant=user.tenant,
        integration_config=fixture["config_allowed"],
        warehouse_authorization=fixture["auth_allowed"],
        resource_type=SyncJob.ResourceType.INVENTORY_SNAPSHOT,
        schedule_type=SyncJob.ScheduleType.MANUAL,
        is_enabled=True,
    )

    client = APIClient()
    client.force_authenticate(user)
    response = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_my"].id},
    )
    assert response.status_code == 200
    payload = response.data["data"]
    assert [item["id"] for item in payload["configs"]] == [fixture["config_allowed"].id]
    assert [item["id"] for item in payload["bindings"]] == [fixture["auth_allowed"].id]
    assert payload["bindings"][0]["has_sync_job"] is True
    assert payload["bindings"][0]["sync_job_id"] == sync_job.id

    # The same role cannot use the MY-scoped warehouse permission to inspect an
    # SG warehouse, even though the generic page/master-data permission can
    # see both warehouse records.
    blocked = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_sg"].id},
    )
    assert blocked.status_code == 403

    # A binding without an inventory snapshot job is explicitly represented so
    # the page can guide the operator to create the missing prerequisite.
    fixture["auth_allowed"].integration_config = fixture["config_sg"]
    fixture["auth_allowed"].warehouse = fixture["warehouse_sg"]
    fixture["auth_allowed"].save(update_fields=["integration_config", "warehouse"])
    scope = DataScope.objects.filter(
        role__user_roles__user=user,
        role__user_roles__tenant=user.tenant,
        role__permissions__code="integrations.warehouse.view",
    ).get()
    scope.config = {
        "platforms": ["jifeng_wms"],
        "environments": ["pilot"],
        "regions": ["SG"],
        "integration_config_ids": [fixture["config_sg"].id],
        "resource_types": ["inventory_snapshot"],
        "warehouse_ids": [fixture["warehouse_sg"].id],
    }
    scope.save(update_fields=["config"])
    moved = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_sg"].id},
    )
    assert moved.status_code == 200
    assert moved.data["data"]["bindings"][0]["has_sync_job"] is False
    assert moved.data["data"]["bindings"][0]["sync_job_id"] is None


@pytest.mark.django_db
def test_global_warehouse_config_uses_concrete_subject_region_for_both_view_scopes():
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    with authorization_service_write():
        global_config = PlatformIntegrationConfig.objects.create(
            tenant=user.tenant,
            platform="jifeng_wms",
            account_alias="Global inventory",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=[],
            platform_config={"api_type": "inventory"},
            credential_id="scope-credential-global",
            token_id="scope-token-global",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
    _grant(
        user,
        ("masterdata.view",),
        scope_config={},
        scope_type=DataScope.ScopeType.ALL,
    )
    _grant(
        user,
        ("integrations.view",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "regions": ["MY"],
            "resource_types": ["inventory_snapshot"],
        },
    )
    _grant(
        user,
        ("integrations.warehouse.view",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "resource_types": ["inventory_snapshot"],
        },
    )
    client = APIClient()
    client.force_authenticate(user)

    same_region = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_my"].id},
    )
    assert same_region.status_code == 200
    assert global_config.id in {item["id"] for item in same_region.data["data"]["configs"]}

    cross_region = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_sg"].id},
    )
    assert cross_region.status_code == 403
    assert cross_region.data["code"] == "DATA_SCOPE_FORBIDDEN"


@pytest.mark.django_db
def test_global_warehouse_sync_job_scope_uses_warehouse_country_and_requires_subject():
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    with authorization_service_write():
        global_config = PlatformIntegrationConfig.objects.create(
            tenant=user.tenant,
            platform="jifeng_wms",
            account_alias="Global sync inventory",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=[],
            platform_config={"api_type": "inventory"},
            credential_id="scope-credential-global-sync",
            token_id="scope-token-global-sync",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
        global_auth = WarehouseAuthorization.objects.create(
            tenant=user.tenant,
            integration_config=global_config,
            warehouse=fixture["warehouse_sg"],
            provider="jifeng_wms",
            credential_id="scope-credential-global-sync",
            token_id="scope-token-global-sync",
            credential_mask={"token": "********"},
            status=WarehouseAuthorization.Status.ACTIVE,
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )
    _grant(
        user,
        ("integrations.manage",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "regions": ["MY"],
            "resource_types": ["inventory_snapshot"],
        },
    )
    client = APIClient()
    client.force_authenticate(user)
    blocked = client.post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": global_config.id,
            "warehouse_authorization_id": global_auth.id,
            "resource_type": "inventory_snapshot",
            "schedule_type": "manual",
        },
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.data["code"] == "DATA_SCOPE_FORBIDDEN"

    missing_subject = client.post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": global_config.id,
            "resource_type": "inventory_snapshot",
            "schedule_type": "manual",
        },
        format="json",
    )
    assert missing_subject.status_code == 400
    assert "concrete store or warehouse authorization" in str(missing_subject.data)


@pytest.mark.django_db
def test_warehouse_subject_requires_warehouse_view_even_without_managed_config():
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    PlatformIntegrationConfig.objects.filter(tenant=user.tenant).update(
        status=PlatformIntegrationConfig.Status.DISABLED,
    )
    _grant(
        user,
        ("masterdata.view",),
        scope_config={},
        scope_type=DataScope.ScopeType.ALL,
    )
    _grant(
        user,
        ("integrations.view",),
        scope_config={},
        scope_type=DataScope.ScopeType.ALL,
    )
    client = APIClient()
    client.force_authenticate(user)
    response = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_my"].id},
    )
    assert response.status_code == 403
    assert response.data["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_empty_warehouse_configs_still_enforce_concrete_warehouse_scope():
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    PlatformIntegrationConfig.objects.filter(tenant=user.tenant).update(
        status=PlatformIntegrationConfig.Status.DISABLED,
    )
    _grant(
        user,
        ("masterdata.view", "integrations.view"),
        scope_config={},
        scope_type=DataScope.ScopeType.ALL,
    )
    _grant(
        user,
        ("integrations.warehouse.view",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "regions": ["MY"],
            "resource_types": ["inventory_snapshot"],
            "warehouse_ids": [fixture["warehouse_my"].id],
        },
    )
    client = APIClient()
    client.force_authenticate(user)

    allowed = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_my"].id},
    )
    assert allowed.status_code == 200
    assert allowed.data["data"]["configs"] == []

    blocked = client.get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "warehouse", "subject_id": fixture["warehouse_sg"].id},
    )
    assert blocked.status_code == 403
    assert blocked.data["code"] == "DATA_SCOPE_FORBIDDEN"


@pytest.mark.django_db
def test_warehouse_readonly_check_applies_resource_scope_to_jobs_only(monkeypatch):
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    config = fixture["config_allowed"]
    authorization = fixture["auth_allowed"]
    _grant(
        user,
        ("integrations.run_live_readonly",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "integration_config_ids": [config.id],
            "resource_types": [SyncJob.ResourceType.INVENTORY_SNAPSHOT],
            "warehouse_ids": [fixture["warehouse_my"].id],
        },
    )
    _grant(
        user,
        ("integrations.warehouse.view",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "integration_config_ids": [config.id],
            "warehouse_ids": [fixture["warehouse_my"].id],
        },
    )
    SyncJob.objects.create(
        tenant=user.tenant,
        integration_config=config,
        warehouse_authorization=authorization,
        resource_type=SyncJob.ResourceType.INVENTORY_SNAPSHOT,
        schedule_type=SyncJob.ScheduleType.MANUAL,
        is_enabled=True,
    )
    monkeypatch.setattr(
        "apps.integrations.views.get_runtime_setting",
        lambda _section, key, default=None: {
            "mode": "approved-live-test",
            "readonly_sync_enabled": True,
        }.get(key, default),
    )
    monkeypatch.setattr(
        "apps.integrations.views.get_custody_backend",
        lambda: SimpleNamespace(retrieve_secret=lambda _credential_id: {"token": "masked"}),
    )
    monkeypatch.setattr(
        "apps.integrations.views.get_adapter_for_config",
        lambda _config, _resource: SimpleNamespace(
            validate_configuration=lambda _job: None,
            fetch_page=lambda _job, _cursor: {"records": [{"sku": "synthetic"}]},
        ),
    )
    client = APIClient()
    client.force_authenticate(user)

    allowed = client.post(
        f"/api/internal/integrations/configs/{config.id}/readonly-check/",
        {"warehouse_authorization_id": authorization.id},
        format="json",
    )
    assert allowed.status_code == 200

    run_scope = DataScope.objects.filter(
        role__user_roles__user=user,
        role__user_roles__tenant=user.tenant,
        role__permissions__code="integrations.run_live_readonly",
    ).get()
    run_scope.config["resource_types"] = [SyncJob.ResourceType.SALES_ORDER]
    run_scope.save(update_fields=["config"])
    wrong_resource = client.post(
        f"/api/internal/integrations/configs/{config.id}/readonly-check/",
        {"warehouse_authorization_id": authorization.id},
        format="json",
    )
    assert wrong_resource.status_code == 400
    assert "没有可用于只读检查" in str(wrong_resource.data)


@pytest.mark.django_db
def test_sync_job_and_run_scopes_honor_store_warehouse_environment_and_region_dimensions():
    fixture = _warehouse_scope_fixture()
    user = fixture["user"]
    store = StoreMaster.objects.create(
        tenant=user.tenant,
        platform=fixture["shopee_platform"],
        code="scope-store-my",
        name="Scope MY store",
        country_code="MY",
        currency="MYR",
        timezone="Asia/Kuala_Lumpur",
    )
    identity = marketplace_identity_key("shopee", "MY", "scope-store")
    with authorization_service_write():
        store_auth = MarketplaceStoreAuthorization.objects.create(
            tenant=user.tenant,
            integration_config=fixture["config_other_platform"],
            store=store,
            platform="shopee",
            region="MY",
            platform_store_id="scope-store",
            platform_identity_key=identity,
            active_platform_identity_key=identity,
            active_store_binding_key=marketplace_store_binding_key(user.tenant_id, "shopee", store.id),
            merchant_subject_id="scope-merchant",
            credential_id="scope-store-credential",
            token_id="scope-store-token",
            credential_mask={"token": "********"},
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
            scopes=["marketplace"],
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )
    warehouse_job = SyncJob.objects.create(
        tenant=user.tenant,
        integration_config=fixture["config_allowed"],
        warehouse_authorization=fixture["auth_allowed"],
        resource_type=SyncJob.ResourceType.INVENTORY_SNAPSHOT,
        schedule_type=SyncJob.ScheduleType.MANUAL,
    )
    store_job = SyncJob.objects.create(
        tenant=user.tenant,
        integration_config=fixture["config_other_platform"],
        store_authorization=store_auth,
        resource_type=SyncJob.ResourceType.SALES_ORDER,
        schedule_type=SyncJob.ScheduleType.MANUAL,
    )
    warehouse_run = SyncRun.objects.create(
        tenant=user.tenant,
        sync_job=warehouse_job,
        run_id="scope-warehouse-run",
        idempotency_key="scope-warehouse-run-key",
        status=SyncRun.Status.SUCCESS,
    )
    store_run = SyncRun.objects.create(
        tenant=user.tenant,
        sync_job=store_job,
        run_id="scope-store-run",
        idempotency_key="scope-store-run-key",
        status=SyncRun.Status.SUCCESS,
    )
    _grant(
        user,
        ("integrations.view",),
        scope_config={
            "platforms": ["jifeng_wms"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "resource_types": ["inventory_snapshot"],
            "warehouse_ids": [fixture["warehouse_my"].id],
        },
    )
    assert list(filter_sync_jobs(user, SyncJob.objects.filter(tenant=user.tenant), "integrations.view")) == [warehouse_job]
    assert list(filter_sync_runs(user, SyncRun.objects.filter(tenant=user.tenant), "integrations.view")) == [warehouse_run]

    # store_ids is also a supported sync scope dimension and must not be
    # ignored merely because the same scope includes a platform.
    scope = DataScope.objects.filter(role__user_roles__user=user, role__permissions__code="integrations.view").get()
    scope.config = {"platforms": ["shopee"], "store_ids": [store.id], "resource_types": ["sales_order"]}
    scope.save(update_fields=["config"])
    assert list(filter_sync_jobs(user, SyncJob.objects.filter(tenant=user.tenant), "integrations.view")) == [store_job]
    assert list(filter_sync_runs(user, SyncRun.objects.filter(tenant=user.tenant), "integrations.view")) == [store_run]
