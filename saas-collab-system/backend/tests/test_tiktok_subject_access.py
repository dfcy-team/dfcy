import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    TikTokAdsAdvertiserMapping,
    authorization_service_write,
    marketplace_active_identity_key,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, RoleResourcePolicy, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _platform(tenant):
    return PlatformMaster.objects.create(
        tenant=tenant,
        code="tiktok",
        name="TikTok",
        platform_type="tiktok",
        status=StatusChoices.ACTIVE,
    )


def _store(tenant, platform, *, code="TK-PH-01", country="PH"):
    return StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=code,
        name=f"{code} Shop",
        country_code=country,
        currency="PHP",
        timezone="Asia/Manila",
    )


def _config(
    tenant,
    user,
    *,
    api_type="advertising",
    alias="TikTok Ads PH",
    regions=None,
    network_enabled=False,
    sync_read_enabled=False,
    sync_write_enabled=False,
):
    return PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="tiktok",
        account_alias=alias,
        environment="pilot",
        status="verified",
        regions=regions if regions is not None else ["PH"],
        scopes=["advertiser.read"],
        platform_config={"api_type": api_type},
        network_enabled=network_enabled,
        sync_read_enabled=sync_read_enabled,
        sync_write_enabled=sync_write_enabled,
        created_by=user,
    )


def _mapping(tenant, store, config, advertiser_id, *, enabled=False, mapping_id=None):
    values = dict(
        tenant=tenant,
        store=store,
        integration_config=config,
        advertiser_id=advertiser_id,
        token_id="tok_" + advertiser_id.zfill(32),
        currency="PHP",
        timezone="Asia/Manila",
        enabled=enabled,
    )
    if mapping_id is not None:
        values["id"] = mapping_id
    return TikTokAdsAdvertiserMapping.objects.create(**values)


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _base(*, superuser=True, mapping_id=None):
    tenant = Tenant.objects.create(name="Ads tenant", code="tiktok-subject-access")
    user = CustomUser.objects.create_user(
        username=f"tiktok-subject-{tenant.pk}",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=superuser,
    )
    platform = _platform(tenant)
    store = _store(tenant, platform)
    ads_config = _config(tenant, user)
    mapping = _mapping(tenant, store, ads_config, "123456789", mapping_id=mapping_id)
    return tenant, user, platform, store, ads_config, mapping


def _marketplace_authorization(tenant, user, store, config, *, authorization_id=None):
    platform_store_id = "tiktok-shop-subject-01"
    identity = marketplace_identity_key("tiktok", "PH", platform_store_id)
    with authorization_service_write():
        values = dict(
            tenant=tenant,
            integration_config=config,
            store=store,
            platform="tiktok",
            region="PH",
            platform_store_id=platform_store_id,
            platform_identity_key=identity,
            active_platform_identity_key=marketplace_active_identity_key(
                "tiktok", "PH", platform_store_id, "marketplace",
            ),
            active_store_binding_key=marketplace_store_binding_key(
                tenant.id, "tiktok", store.id, "marketplace",
            ),
            merchant_subject_id="merchant-subject-01",
            shop_cipher="synthetic-shop-cipher",
            credential_id="synthetic-marketplace-credential-ref",
            token_id="synthetic-marketplace-token-ref",
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
            scopes=["shop.read"],
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )
        if authorization_id is not None:
            values["id"] = authorization_id
        return MarketplaceStoreAuthorization.objects.create(**values)


def test_tiktok_ads_mappings_are_separate_from_marketplace_bindings_and_safe(monkeypatch):
    tenant, user, _platform_row, store, ads_config, first_mapping = _base(mapping_id=9001)
    ads_config.network_enabled = True
    ads_config.sync_read_enabled = True
    ads_config.save(update_fields=["network_enabled", "sync_read_enabled"])
    marketplace_config = _config(
        tenant, user, api_type="marketplace", alias="TikTok Shop PH",
    )
    authorization = _marketplace_authorization(
        tenant, user, store, marketplace_config, authorization_id=first_mapping.pk,
    )
    # The two independent tables may have the same integer primary key.
    assert first_mapping.pk == authorization.pk
    second_mapping = _mapping(tenant, store, ads_config, "987654321", enabled=False)

    refresh_calls = []

    def refresh_state(record):
        refresh_calls.append(record.pk)
        return {
            "enabled": True,
            "state": "due",
            "renewal_mode": "per-binding",
            "expires_at": "2026-10-10T00:00:00+00:00",
            "next_refresh_due_at": "2026-10-09T00:00:00+00:00",
            "last_refreshed_at": "2026-10-01T00:00:00+00:00",
            "scheduler_metadata": {"heartbeat_state": "recent"},
        }

    monkeypatch.setattr(
        "apps.integrations.subject_access_service.credential_refresh_state",
        refresh_state,
    )
    response = _client(user).get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "store", "subject_id": store.id},
    )

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["token_policy"] == "tiktok-per-binding-policy"
    assert [binding["id"] for binding in payload["bindings"]] == [authorization.id]
    marketplace_binding = payload["bindings"][0]
    assert marketplace_binding["renewal_owner"] == "saas"
    assert marketplace_binding["renewal"]["renewal_mode"] == "per-binding"
    assert marketplace_binding["renewal"]["scheduler_metadata"] == {"heartbeat_state": "recent"}
    assert refresh_calls == [authorization.id]

    ads_rows = payload["ads_mappings"]
    assert {row["mapping_id"] for row in ads_rows} == {first_mapping.id, second_mapping.id}
    assert all(row["state"] == "mapped" for row in ads_rows)
    assert all(row["binding_kind"] == "tiktok_ads_mapping" for row in ads_rows)
    assert all(row["mapping_enabled"] is False and row["sync_enabled"] is False for row in ads_rows)
    assert all(row["network_enabled"] is True and row["read_enabled"] is True for row in ads_rows)
    assert all(row["credential_configured"] is True for row in ads_rows)
    assert all(row["store_id"] == store.id for row in ads_rows)
    assert all(row["integration_config_id"] == ads_config.id for row in ads_rows)
    assert all(row["account_alias"] == ads_config.account_alias for row in ads_rows)
    assert all("status" not in row for row in ads_rows)
    assert all("authorized_at" not in row and "last_verified_at" not in row for row in ads_rows)
    assert all("expires_at" not in row and "refreshed_at" not in row for row in ads_rows)
    assert all("token_id" not in row and "credential_id" not in row for row in ads_rows)
    assert "synthetic" not in str(ads_rows)


@pytest.mark.parametrize(("network", "read", "write", "mapping_enabled", "expected_sync"), [
    (False, True, False, True, False),
    (True, False, False, True, False),
    (True, True, True, True, False),
    (True, True, False, False, False),
    (True, True, False, True, True),
])
def test_tiktok_ads_mapping_flags_follow_config_gates_and_never_enable_writes(
    network, read, write, mapping_enabled, expected_sync,
):
    tenant = Tenant.objects.create(name="Ads gates", code=f"tiktok-gates-{network}-{read}-{write}-{mapping_enabled}")
    user = CustomUser.objects.create_user(
        username=f"tiktok-gates-{tenant.pk}",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    platform = _platform(tenant)
    store = _store(tenant, platform)
    config = _config(
        tenant,
        user,
        network_enabled=network,
        sync_read_enabled=read,
        sync_write_enabled=False,
    )
    mapping = _mapping(
        tenant,
        store,
        config,
        "123456789",
        enabled=mapping_enabled,
    )
    if write:
        # Simulate a later unsafe config change, not an invalid mapping creation.
        config.sync_write_enabled = True
        config.save(update_fields=["sync_write_enabled"])

    response = _client(user).get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "store", "subject_id": store.id},
    )

    assert response.status_code == 200
    [row] = response.data["data"]["ads_mappings"]
    assert row["mapping_id"] == mapping.id
    assert row["state"] == "mapped"
    assert row["mapping_enabled"] is mapping_enabled
    assert row["network_enabled"] is network
    assert row["read_enabled"] is read
    assert row["sync_enabled"] is expected_sync
    assert "sync_write_enabled" not in row


def test_tiktok_subject_reports_real_stale_renewal_scheduler():
    from datetime import timedelta
    from apps.integrations.models import SyncSchedulerHeartbeat
    _, user, _, store, _, _ = _base()
    SyncSchedulerHeartbeat.objects.create(
        key="credential-refresh", last_seen_at=timezone.now() - timedelta(minutes=10),
    )
    response = _client(user).get("/api/internal/integrations/subject-api-access/", {
        "subject_type": "store", "subject_id": store.id,
    })
    assert response.status_code == 200
    state = response.data["data"]["renewal_scheduler"]
    assert state["heartbeat_state"] == "stale"
    assert state["age_seconds"] >= 600
    assert state["queue"] == "credential-refresh"


def test_tiktok_ads_collection_is_tenant_store_config_and_region_scoped():
    tenant, user, platform, store, ads_config, mapping = _base()
    other_store = _store(tenant, platform, code="TK-PH-02")
    _mapping(tenant, other_store, ads_config, "234567890")
    wrong_region_config = _config(
        tenant, user, alias="TikTok Ads MY", regions=["MY"],
    )
    # Model validation permits the config/store region mismatch; the subject
    # API must still exclude this mapping because that config is not visible.
    _mapping(tenant, store, wrong_region_config, "345678901")
    marketplace_config = _config(
        tenant, user, api_type="marketplace", alias="TikTok Shop config",
    )

    other_tenant = Tenant.objects.create(name="Other tenant", code="tiktok-subject-other")
    other_user = CustomUser.objects.create_user(
        username=f"tiktok-subject-other-{other_tenant.pk}",
        password="not-a-real-password",
        tenant=other_tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    other_platform = _platform(other_tenant)
    other_tenant_config = _config(other_tenant, other_user)
    # Simulate legacy/corrupt rows inserted outside model validation. These
    # cross-tenant or mismatched records must never enter the response.
    TikTokAdsAdvertiserMapping.objects.bulk_create([
        TikTokAdsAdvertiserMapping(
            tenant=other_tenant,
            store=store,
            integration_config=other_tenant_config,
            advertiser_id="456789012",
            token_id="tok_" + "4".zfill(32),
            currency="PHP",
            timezone="Asia/Manila",
        ),
        TikTokAdsAdvertiserMapping(
            tenant=tenant,
            store=store,
            integration_config=marketplace_config,
            advertiser_id="789012345",
            token_id="tok_" + "7".zfill(32),
            currency="PHP",
            timezone="Asia/Manila",
        ),
        TikTokAdsAdvertiserMapping(
            tenant=tenant,
            store=store,
            integration_config=other_tenant_config,
            advertiser_id="567890123",
            token_id="tok_" + "5".zfill(32),
            currency="PHP",
            timezone="Asia/Manila",
        ),
        TikTokAdsAdvertiserMapping(
            tenant=tenant,
            store=_store(other_tenant, other_platform, code="TK-OTHER-01"),
            integration_config=ads_config,
            advertiser_id="678901234",
            token_id="tok_" + "6".zfill(32),
            currency="PHP",
            timezone="Asia/Manila",
        ),
    ])

    response = _client(user).get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "store", "subject_id": store.id},
    )

    assert response.status_code == 200
    rows = response.data["data"]["ads_mappings"]
    assert [row["mapping_id"] for row in rows] == [mapping.id]
    assert {row["advertiser_id"] for row in rows} == {mapping.advertiser_id}


def _scoped_viewer(tenant, store, scope):
    user = CustomUser.objects.create_user(
        username=f"tiktok-scoped-{tenant.pk}-{len(scope)}-{abs(hash(str(scope))) % 100000}",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(
        tenant=tenant,
        code=f"tiktok-scoped-{user.pk}",
        name="TikTok scoped viewer",
        status=Role.Status.ACTIVE,
    )
    for code in ("integrations.view", "integrations.store.view", "masterdata.view"):
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "integrations", "action": "view"},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config=scope,
    )
    RoleResourcePolicy.objects.create(
        tenant=tenant,
        role=role,
        resource_code="masterdata.stores",
        permission_code="masterdata.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"store_ids": [store.id]},
    )
    return user


@pytest.mark.parametrize("scope", [
    {"integration_config_ids": [999999]},
    {"regions": ["MY"]},
    {"store_ids": [999999]},
])
def test_tiktok_ads_mapping_requires_matching_config_region_and_store_scope(scope):
    tenant, _admin, platform, store, _ads_config, mapping = _base()
    scope = dict(scope)
    if "store_ids" in scope:
        other_store = _store(tenant, platform, code="TK-PH-02")
        scope["store_ids"] = [other_store.id]
    viewer = _scoped_viewer(tenant, store, scope)

    response = _client(viewer).get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "store", "subject_id": store.id},
    )

    assert response.status_code == 200
    payload = response.data["data"]
    assert payload["ads_mappings"] == []
    assert all(row["mapping_id"] != mapping.id for row in payload["ads_mappings"])


def test_tiktok_ads_mapping_requires_store_authorization_view_permission():
    tenant, _admin, _platform_row, store, _ads_config, _mapping_row = _base()
    viewer = CustomUser.objects.create_user(
        username=f"tiktok-no-store-view-{tenant.pk}",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(
        tenant=tenant,
        code=f"tiktok-no-store-view-{tenant.pk}",
        name="Integration viewer only",
        status=Role.Status.ACTIVE,
    )
    for code in ("integrations.view", "masterdata.view"):
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "integrations", "action": "view"},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=viewer, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})

    response = _client(viewer).get(
        "/api/internal/integrations/subject-api-access/",
        {"subject_type": "store", "subject_id": store.id},
    )

    assert response.status_code == 403
    assert response.data["code"] == "PERMISSION_DENIED"
