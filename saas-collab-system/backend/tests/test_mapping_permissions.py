import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    MarketplaceProductMapping,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformIntegrationConfig,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
    product_mapping_service_write,
    store_mapping_service_write,
)
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
from apps.listings.models import PlatformProductDetail
from apps.permissions.api_permissions import (
    IsMarketplaceProductMappingManager,
    IsMarketplaceStoreAuthorizer,
    IsMarketplaceStoreMappingManager,
)
from apps.permissions.catalog import PERMISSION_DEFINITIONS
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.ui_p6_scopes import (
    filter_platform_product_details,
    filter_product_mappings,
    filter_store_mappings,
)
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db

MIGRATION = importlib.import_module("apps.permissions.migrations.0041_register_mapping_permissions")
MAPPING_CODES = set(MIGRATION.PERMISSION_CODES)


def _permission(code):
    permission, _ = Permission.objects.update_or_create(
        code=code,
        defaults={
            "name": code,
            "module": code.split(".", 1)[0],
            "action": code.rsplit(".", 1)[-1],
            "permission_type": Permission.PermissionType.ACTION,
            "metadata": {},
        },
    )
    return permission


def _user_with_role(*codes, scope_config=None, scope_type=DataScope.ScopeType.ALL, username="mapping-user"):
    tenant = Tenant.objects.create(name=f"Mapping tenant {username}", code=f"mapping-{username}")
    user = CustomUser.objects.create_user(
        username=username,
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(
        tenant=tenant,
        name="映射测试角色",
        code=f"mapping-role-{username}",
        status=Role.Status.ACTIVE,
    )
    role.permissions.add(*[_permission(code) for code in codes])
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config or {},
    )
    return user, role


def test_mapping_permission_catalog_has_chinese_action_contract():
    definitions = {item["code"]: item for item in PERMISSION_DEFINITIONS}
    assert MAPPING_CODES <= definitions.keys()
    for code in MAPPING_CODES:
        definition = definitions[code]
        assert definition["module"] == "integrations"
        assert definition.get("permission_type", "action") == "action"
        assert definition["name"]
        assert definition["description"]


def test_mapping_migration_is_idempotent_and_preserves_custom_scope_without_all_expansion():
    tenant = Tenant.objects.create(name="Mapping migration tenant", code="mapping-migration")
    role = Role.objects.create(
        tenant=tenant,
        name="映射操作员",
        code="mapping-operator",
        status=Role.Status.ACTIVE,
    )
    role.permissions.add(_permission("integrations.store.view"), _permission("integrations.store.authorize"))
    custom = DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"platforms": ["shopee"], "store_ids": [101]},
    )
    admin = Role.objects.create(
        tenant=tenant,
        name="管理员",
        code="administrator",
        status=Role.Status.ACTIVE,
    )

    MIGRATION.register_mapping_permissions(django_apps, None)
    MIGRATION.register_mapping_permissions(django_apps, None)

    assert MAPPING_CODES <= set(role.permissions.values_list("code", flat=True))
    assert MAPPING_CODES <= set(admin.permissions.values_list("code", flat=True))
    custom.refresh_from_db()
    assert custom.scope_type == DataScope.ScopeType.CUSTOM
    assert custom.config == {"platforms": ["shopee"], "store_ids": [101]}
    assert not DataScope.objects.filter(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL).exists()
    assert Permission.objects.filter(code__in=MAPPING_CODES).count() == len(MAPPING_CODES)


def test_mapping_permission_classes_have_separate_read_manage_confirm_and_oauth_boundaries():
    viewer, _ = _user_with_role("integrations.store_mapping.view", "integrations.product_mapping.view", username="viewer")
    manager, _ = _user_with_role("integrations.store_mapping.manage", "integrations.product_mapping.manage", username="manager")
    confirmer, _ = _user_with_role("integrations.product_mapping.confirm", username="confirmer")
    legacy, _ = _user_with_role("integrations.store.authorize", username="legacy")
    legacy_view, _ = _user_with_role("integrations.store.view", username="legacy-view")

    store_permission = IsMarketplaceStoreMappingManager()
    product_permission = IsMarketplaceProductMappingManager()

    def request(user, method, data=None):
        return SimpleNamespace(user=user, method=method, data=data or {})

    assert store_permission.has_permission(request(viewer, "GET"), None)
    assert not store_permission.has_permission(request(viewer, "POST", {}), None)
    assert store_permission.has_permission(request(manager, "POST", {}), None)
    assert not store_permission.has_permission(request(legacy, "POST", {}), None)
    assert not store_permission.has_permission(request(legacy_view, "GET"), None)
    assert not IsMarketplaceStoreAuthorizer().has_permission(request(manager, "POST", {}), None)
    assert IsMarketplaceStoreAuthorizer().has_permission(request(legacy, "POST", {}), None)

    assert product_permission.has_permission(request(viewer, "GET"), None)
    assert product_permission.has_permission(request(manager, "POST", {}), None)
    assert product_permission.has_permission(request(manager, "POST", {"manually_confirmed": True}), None)
    assert not product_permission.has_permission(request(confirmer, "POST", {"manually_confirmed": True}), None)
    assert not product_permission.has_permission(request(manager, "PATCH", {"manually_confirmed": True}), None)
    assert product_permission.has_permission(request(confirmer, "PATCH", {"manually_confirmed": True}), None)
    assert not product_permission.has_permission(request(confirmer, "PATCH", {"manually_confirmed": False}), None)
    assert not product_permission.has_permission(request(confirmer, "PATCH", {"manually_confirmed": "true"}), None)
    assert not product_permission.has_permission(request(confirmer, "PATCH", {"manually_confirmed": 1}), None)


def test_platform_product_detail_scope_aligns_platform_and_store_and_fails_closed_on_empty_custom_scope():
    user, _ = _user_with_role(
        "integrations.product_mapping.view",
        scope_config={},
        scope_type=DataScope.ScopeType.CUSTOM,
        username="detail-scope",
    )
    platform = PlatformMaster.objects.create(
        tenant=user.tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
        status=StatusChoices.ACTIVE,
    )
    other_platform = PlatformMaster.objects.create(
        tenant=user.tenant,
        code="tiktok",
        name="TikTok",
        platform_type="tiktok",
        status=StatusChoices.ACTIVE,
    )
    store_a = StoreMaster.objects.create(
        tenant=user.tenant,
        platform=platform,
        code="store-a",
        name="Store A",
        country_code="MY",
        currency="MYR",
    )
    store_b = StoreMaster.objects.create(
        tenant=user.tenant,
        platform=other_platform,
        code="store-b",
        name="Store B",
        country_code="MY",
        currency="MYR",
    )
    detail_a = PlatformProductDetail.objects.create(
        tenant=user.tenant,
        platform=platform,
        store=store_a,
        platform_variant_id="variant-a",
    )
    detail_b = PlatformProductDetail.objects.create(
        tenant=user.tenant,
        platform=other_platform,
        store=store_b,
        platform_variant_id="variant-b",
    )
    scope = DataScope.objects.get(role__user_roles__user=user)
    queryset = PlatformProductDetail.objects.all()

    scope.config = {"platforms": ["shopee"], "store_ids": [store_a.id]}
    scope.save(update_fields=["config"])
    assert list(filter_platform_product_details(user, queryset, "integrations.product_mapping.view")) == [detail_a]

    scope.config = {"platforms": ["shopee"], "store_ids": [store_b.id]}
    scope.save(update_fields=["config"])
    assert not filter_platform_product_details(user, queryset, "integrations.product_mapping.view").exists()

    scope.config = {}
    scope.save(update_fields=["config"])
    assert not filter_platform_product_details(user, queryset, "integrations.product_mapping.view").exists()


def test_mapping_scopes_inherit_authorization_environment_region_and_config_without_cross_tenant_leak():
    user, role = _user_with_role(
        "integrations.store_mapping.view",
        "integrations.product_mapping.view",
        scope_config={"platforms": ["shopee"]},
        scope_type=DataScope.ScopeType.CUSTOM,
        username="mapping-scope-chain",
    )
    tenant = user.tenant
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
        status=StatusChoices.ACTIVE,
    )
    stores = {}
    configs = {}
    authorizations = {}
    store_mappings = {}
    product_mappings = {}

    def make_binding(label, *, environment, config_regions, region):
        store = StoreMaster.objects.create(
            tenant=tenant,
            platform=platform,
            code=f"scope-{label}",
            name=f"Scope {label}",
            country_code=region,
            currency="MYR" if region == "MY" else "THB",
        )
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="shopee",
            account_alias=f"scope-{label}",
            environment=environment,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=config_regions,
            created_by=user,
        )
        external_id = f"scope-{label}-external"
        identity = marketplace_identity_key("shopee", region, external_id)
        with authorization_service_write():
            authorization = MarketplaceStoreAuthorization.objects.create(
                tenant=tenant,
                integration_config=config,
                store=store,
                platform="shopee",
                region=region,
                platform_store_id=external_id,
                platform_identity_key=identity,
                active_platform_identity_key=identity,
                active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
                merchant_subject_id=f"merchant-{label}",
                credential_id=f"credential-{label}",
                token_id=f"token-{label}",
                credential_mask={"token": "********"},
                status=MarketplaceStoreAuthorization.Status.ACTIVE,
                authorized_at=timezone.now(),
                created_by=user,
                updated_by=user,
            )
        store_mapping = MarketplaceStoreMapping(
            tenant=tenant,
            platform="shopee",
            store=store,
            authorization=authorization,
            platform_store_id=external_id,
            platform_identity_key=identity,
            platform_subject_id=f"subject-{label}",
            region=region,
            timezone="Asia/Kuala_Lumpur",
            currency="MYR" if region == "MY" else "THB",
            status=MarketplaceStoreMapping.Status.ACTIVE,
            mapping_source=MarketplaceStoreMapping.MappingSource.SYNTHETIC_FIXTURE,
            mapped_by=user,
        )
        with store_mapping_service_write():
            store_mapping.save()
        product_mapping = MarketplaceProductMapping(
            tenant=tenant,
            platform="shopee",
            store_mapping=store_mapping,
            platform_product_id=f"P-{label}",
            platform_variant_id=f"V-{label}",
            platform_sku=f"SKU-{label}",
            status=MarketplaceProductMapping.Status.UNMAPPED,
            mapping_source=MarketplaceProductMapping.MappingSource.MANUAL,
            created_by=user,
            updated_by=user,
        )
        with product_mapping_service_write():
            product_mapping.save()
        stores[label] = store
        configs[label] = config
        authorizations[label] = authorization
        store_mappings[label] = store_mapping
        product_mappings[label] = product_mapping

    make_binding("allowed", environment=PlatformIntegrationConfig.Environment.PRODUCTION, config_regions=["MY"], region="MY")
    make_binding("wrong-environment", environment=PlatformIntegrationConfig.Environment.SANDBOX, config_regions=["MY"], region="MY")
    make_binding("wrong-region", environment=PlatformIntegrationConfig.Environment.PRODUCTION, config_regions=["TH"], region="TH")
    make_binding("wrong-config", environment=PlatformIntegrationConfig.Environment.PRODUCTION, config_regions=["MY"], region="MY")

    scope = DataScope.objects.get(role=role)
    scope.config = {
        "platforms": ["shopee"],
        "environments": ["production"],
        "regions": ["MY"],
        "integration_config_ids": [configs["allowed"].id],
    }
    scope.save(update_fields=["config"])

    store_queryset = MarketplaceStoreMapping.objects.all()
    product_queryset = MarketplaceProductMapping.objects.all()
    visible_stores = set(
        filter_store_mappings(user, store_queryset, "integrations.store_mapping.view").values_list("id", flat=True)
    )
    visible_products = set(
        filter_product_mappings(user, product_queryset, "integrations.product_mapping.view").values_list("id", flat=True)
    )
    assert visible_stores == {store_mappings["allowed"].id}
    assert visible_products == {product_mappings["allowed"].id}
    assert store_mappings["wrong-environment"].id not in visible_stores
    assert store_mappings["wrong-region"].id not in visible_stores
    assert store_mappings["wrong-config"].id not in visible_stores

    foreign_tenant = Tenant.objects.create(name="Foreign scope tenant", code="foreign-scope-tenant")
    foreign_user = CustomUser.objects.create_user(
        username="foreign-scope-user",
        password="not-a-real-password",
        tenant=foreign_tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    foreign_platform = PlatformMaster.objects.create(
        tenant=foreign_tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
        status=StatusChoices.ACTIVE,
    )
    foreign_store = StoreMaster.objects.create(
        tenant=foreign_tenant,
        platform=foreign_platform,
        code="foreign-scope-store",
        name="Foreign scope store",
        country_code="MY",
        currency="MYR",
    )
    foreign_config = PlatformIntegrationConfig.objects.create(
        tenant=foreign_tenant,
        platform="shopee",
        account_alias="foreign-scope-config",
        environment=PlatformIntegrationConfig.Environment.PRODUCTION,
        status=PlatformIntegrationConfig.Status.VERIFIED,
        regions=["MY"],
        created_by=foreign_user,
    )
    foreign_external_id = "foreign-scope-external"
    foreign_identity = marketplace_identity_key("shopee", "MY", foreign_external_id)
    with authorization_service_write():
        foreign_authorization = MarketplaceStoreAuthorization.objects.create(
            tenant=foreign_tenant,
            integration_config=foreign_config,
            store=foreign_store,
            platform="shopee",
            region="MY",
            platform_store_id=foreign_external_id,
            platform_identity_key=foreign_identity,
            active_platform_identity_key=foreign_identity,
            active_store_binding_key=marketplace_store_binding_key(foreign_tenant.id, "shopee", foreign_store.id),
            merchant_subject_id="foreign-scope-merchant",
            credential_id="foreign-scope-credential",
            token_id="foreign-scope-token",
            credential_mask={"token": "********"},
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
            authorized_at=timezone.now(),
            created_by=foreign_user,
            updated_by=foreign_user,
        )
    foreign_mapping = MarketplaceStoreMapping(
        tenant=foreign_tenant,
        platform="shopee",
        store=foreign_store,
        authorization=foreign_authorization,
        platform_store_id=foreign_external_id,
        platform_identity_key=foreign_identity,
        platform_subject_id="foreign-scope-subject",
        region="MY",
        timezone="Asia/Kuala_Lumpur",
        currency="MYR",
        status=MarketplaceStoreMapping.Status.ACTIVE,
        mapping_source=MarketplaceStoreMapping.MappingSource.SYNTHETIC_FIXTURE,
        mapped_by=foreign_user,
    )
    with store_mapping_service_write():
        foreign_mapping.save()

    # Removing the config-id dimension makes the foreign row match every
    # integration dimension except tenant; the tenant predicate must still
    # keep it out of the current user's result.
    scope.config.pop("integration_config_ids")
    scope.save(update_fields=["config"])
    visible_with_foreign = set(
        filter_store_mappings(user, store_queryset, "integrations.store_mapping.view").values_list("id", flat=True)
    )
    assert foreign_mapping.id not in visible_with_foreign
