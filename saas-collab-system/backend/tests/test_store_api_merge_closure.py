from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    SyncJob,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.integrations.serializers import IntegrationAuditLogSerializer, SyncJobSerializer
from apps.integrations.store_authorization_service import _audit
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.ui_p6_scopes import filter_store_authorizations
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _grant(user, codes, *, scope_config=None, scope_type=DataScope.ScopeType.ALL):
    suffix = Role.objects.filter(tenant=user.tenant).count() + 1
    role = Role.objects.create(
        tenant=user.tenant,
        code=f"store-api-merge-{user.username}-{suffix}",
        name="Store API merge test role",
        status=Role.Status.ACTIVE,
    )
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "integrations", "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config or {},
    )
    return role


def _context():
    tenant = Tenant.objects.create(name="Store API merge tenant", code="store-api-merge")
    user = CustomUser.objects.create_user(
        username="store-api-merge-user",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
        status=StatusChoices.ACTIVE,
    )
    store_a = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="STORE-MY-A",
        name="Shopee MY A",
        country_code="MY",
        currency="MYR",
        timezone="Asia/Kuala_Lumpur",
    )
    store_b = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="STORE-MY-B",
        name="Shopee MY B",
        country_code="MY",
        currency="MYR",
        timezone="Asia/Kuala_Lumpur",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="Shopee MY",
        environment=PlatformIntegrationConfig.Environment.PILOT,
        status=PlatformIntegrationConfig.Status.VERIFIED,
        regions=["MY"],
        platform_config={"api_type": "marketplace"},
        created_by=user,
    )
    now = timezone.now()
    authorizations = []
    for store, external_id in ((store_a, "store-a"), (store_b, "store-b")):
        identity = marketplace_identity_key("shopee", "MY", external_id)
        with authorization_service_write():
            authorization = MarketplaceStoreAuthorization.objects.create(
                tenant=tenant,
                integration_config=config,
                store=store,
                platform="shopee",
                region="MY",
                platform_store_id=external_id,
                platform_identity_key=identity,
                active_platform_identity_key=identity,
                active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
                merchant_subject_id=f"merchant-{external_id}",
                credential_id=f"synthetic-{external_id}-credential",
                token_id=f"synthetic-{external_id}-token",
                credential_mask={"token": "********"},
                status=MarketplaceStoreAuthorization.Status.ACTIVE,
                scopes=["marketplace"],
                authorized_at=now,
                created_by=user,
                updated_by=user,
            )
        authorizations.append(authorization)
    jobs = [
        SyncJob.objects.create(
            tenant=tenant,
            integration_config=config,
            store_authorization=authorization,
            resource_type=SyncJob.ResourceType.SALES_ORDER,
            schedule_type=SyncJob.ScheduleType.MANUAL,
        )
        for authorization in authorizations
    ]
    return {
        "tenant": tenant,
        "user": user,
        "config": config,
        "stores": (store_a, store_b),
        "authorizations": tuple(authorizations),
        "jobs": tuple(jobs),
    }


def _grant_all_integration_access(user):
    _grant(
        user,
        (
            "masterdata.view",
            "integrations.view",
            "integrations.manage",
            "integrations.run_live_readonly",
            "integrations.store.view",
            "integrations.store.authorize",
            "integrations.store.revoke",
            "integrations.credential.rotate",
        ),
    )


def test_store_readonly_check_selects_only_the_requested_authorization_and_audits_id(monkeypatch):
    context = _context()
    user = context["user"]
    config = context["config"]
    authorization_a, authorization_b = context["authorizations"]
    _grant_all_integration_access(user)

    class Custody:
        @staticmethod
        def retrieve_secret(_credential_id):
            return {"token": "masked"}

    seen = []

    class Adapter:
        @staticmethod
        def validate_configuration(job):
            seen.append(job.store_authorization_id)

        @staticmethod
        def fetch_page(_job, _cursor):
            return {"records": [{"order_id": "synthetic"}]}

    monkeypatch.setattr(
        "apps.integrations.views.get_runtime_setting",
        lambda _section, key, default=None: {
            "mode": "approved-live-test",
            "readonly_sync_enabled": True,
        }.get(key, default),
    )
    monkeypatch.setattr("apps.integrations.views.get_custody_backend", lambda: Custody())
    monkeypatch.setattr("apps.integrations.views.get_adapter_for_config", lambda _config, _resource: Adapter())
    client = APIClient()
    client.force_authenticate(user)

    first = client.post(
        f"/api/internal/integrations/configs/{config.id}/readonly-check/",
        {"store_authorization_id": authorization_a.id},
        format="json",
    )
    second = client.post(
        f"/api/internal/integrations/configs/{config.id}/readonly-check/",
        {"store_authorization_id": authorization_b.id},
        format="json",
    )
    both = client.post(
        f"/api/internal/integrations/configs/{config.id}/readonly-check/",
        {
            "store_authorization_id": authorization_a.id,
            "warehouse_authorization_id": authorization_b.id,
        },
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert both.status_code == 400
    assert seen == [authorization_a.id, authorization_b.id]
    audit = IntegrationAuditLog.objects.filter(
        integration_config=config,
        action="test_live_integration_connection",
    ).latest("id")
    assert audit.masked_detail["store_authorization_id"] == authorization_b.id


def test_store_readonly_check_requires_concrete_subject_and_store_view_intersection(monkeypatch):
    context = _context()
    user = CustomUser.objects.create_user(
        username="store-api-readonly-runner-only",
        password="not-a-real-password",
        tenant=context["tenant"],
        user_type=CustomUser.UserType.INTERNAL,
    )
    _grant(user, ("integrations.run_live_readonly",), scope_type=DataScope.ScopeType.ALL)
    runtime = {"mode": "", "readonly_sync_enabled": False}
    monkeypatch.setattr(
        "apps.integrations.views.get_runtime_setting",
        lambda _section, key, default=None: runtime.get(key, default),
    )
    client = APIClient()
    client.force_authenticate(user)

    missing_subject = client.post(
        f"/api/internal/integrations/configs/{context['config'].id}/readonly-check/",
        {},
        format="json",
    )
    assert missing_subject.status_code == 400
    assert "具体的店铺授权或仓库授权" in str(missing_subject.data)

    runtime.update(mode="approved-live-test", readonly_sync_enabled=True)
    missing_subject_with_switches = client.post(
        f"/api/internal/integrations/configs/{context['config'].id}/readonly-check/",
        {},
        format="json",
    )
    assert missing_subject_with_switches.status_code == 400
    assert "具体的店铺授权或仓库授权" in str(missing_subject_with_switches.data)

    custody_calls = []
    monkeypatch.setattr(
        "apps.integrations.views.get_custody_backend",
        lambda: SimpleNamespace(retrieve_secret=lambda _credential_id: custody_calls.append(True)),
    )
    blocked = client.post(
        f"/api/internal/integrations/configs/{context['config'].id}/readonly-check/",
        {"store_authorization_id": context["authorizations"][0].id},
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.data["code"] == "PERMISSION_DENIED"
    assert custody_calls == []


def test_store_readonly_check_applies_resource_scope_to_jobs_only(monkeypatch):
    context = _context()
    user = CustomUser.objects.create_user(
        username="store-api-readonly-resource-scope",
        password="not-a-real-password",
        tenant=context["tenant"],
        user_type=CustomUser.UserType.INTERNAL,
    )
    authorization = context["authorizations"][0]
    _grant(
        user,
        ("integrations.run_live_readonly",),
        scope_config={
            "platforms": ["shopee"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "integration_config_ids": [context["config"].id],
            "resource_types": [SyncJob.ResourceType.SALES_ORDER],
            "store_ids": [authorization.store_id],
        },
        scope_type=DataScope.ScopeType.CUSTOM,
    )
    _grant(
        user,
        ("integrations.store.view",),
        scope_config={
            "platforms": ["shopee"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "integration_config_ids": [context["config"].id],
            "store_ids": [authorization.store_id],
        },
        scope_type=DataScope.ScopeType.CUSTOM,
    )

    runtime = {"mode": "approved-live-test", "readonly_sync_enabled": True}
    monkeypatch.setattr(
        "apps.integrations.views.get_runtime_setting",
        lambda _section, key, default=None: runtime.get(key, default),
    )
    monkeypatch.setattr(
        "apps.integrations.views.get_custody_backend",
        lambda: SimpleNamespace(retrieve_secret=lambda _credential_id: {"token": "masked"}),
    )
    monkeypatch.setattr(
        "apps.integrations.views.get_adapter_for_config",
        lambda _config, _resource: SimpleNamespace(
            validate_configuration=lambda _job: None,
            fetch_page=lambda _job, _cursor: {"records": [{"order_id": "synthetic"}]},
        ),
    )
    client = APIClient()
    client.force_authenticate(user)

    allowed = client.post(
        f"/api/internal/integrations/configs/{context['config'].id}/readonly-check/",
        {"store_authorization_id": authorization.id},
        format="json",
    )
    assert allowed.status_code == 200

    run_scope = DataScope.objects.filter(
        role__user_roles__user=user,
        role__user_roles__tenant=user.tenant,
        role__permissions__code="integrations.run_live_readonly",
    ).get()
    run_scope.config["resource_types"] = [SyncJob.ResourceType.REFUND_RETURN]
    run_scope.save(update_fields=["config"])
    wrong_resource = client.post(
        f"/api/internal/integrations/configs/{context['config'].id}/readonly-check/",
        {"store_authorization_id": authorization.id},
        format="json",
    )
    assert wrong_resource.status_code == 400
    assert "没有可用于只读检查" in str(wrong_resource.data)


def test_store_sync_job_requires_active_authorization_and_store_scope():
    context = _context()
    user = context["user"]
    config = context["config"]
    authorization_a, authorization_b = context["authorizations"]
    authorization_b.status = MarketplaceStoreAuthorization.Status.EXPIRED
    with authorization_service_write():
        authorization_b.save(update_fields=["status", "updated_at"])

    serializer = SyncJobSerializer(
        data={
            "integration_config_id": config.id,
            "store_authorization_id": authorization_b.id,
            "resource_type": SyncJob.ResourceType.REFUND_RETURN,
            "schedule_type": SyncJob.ScheduleType.MANUAL,
        },
        context={"request": SimpleNamespace(user=user)},
    )
    assert serializer.is_valid() is False
    assert "store_authorization_id" in serializer.errors

    scoped_user = CustomUser.objects.create_user(
        username="store-api-manage-scoped",
        password="not-a-real-password",
        tenant=context["tenant"],
        user_type=CustomUser.UserType.INTERNAL,
    )
    _grant(
        scoped_user,
        ("integrations.manage",),
        scope_config={"store_ids": [authorization_a.store_id]},
        scope_type=DataScope.ScopeType.CUSTOM,
    )
    # Make the second authorization active again for the endpoint scope test.
    authorization_b.status = MarketplaceStoreAuthorization.Status.ACTIVE
    with authorization_service_write():
        authorization_b.save(update_fields=["status", "updated_at"])
    client = APIClient()
    client.force_authenticate(scoped_user)
    blocked = client.post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": config.id,
            "store_authorization_id": authorization_b.id,
            "resource_type": SyncJob.ResourceType.REFUND_RETURN,
            "schedule_type": SyncJob.ScheduleType.MANUAL,
        },
        format="json",
    )
    assert blocked.status_code == 403
    assert blocked.data["code"] == "DATA_SCOPE_FORBIDDEN"

    missing_subject = SyncJobSerializer(
        data={
            "integration_config_id": config.id,
            "resource_type": SyncJob.ResourceType.SALES_ORDER,
            "schedule_type": SyncJob.ScheduleType.MANUAL,
        },
        context={"request": SimpleNamespace(user=user)},
    )
    assert missing_subject.is_valid() is False
    assert "concrete store or warehouse authorization" in str(missing_subject.errors)


def test_store_refresh_requires_intersection_of_authorize_and_credential_scopes(monkeypatch):
    context = _context()
    user = CustomUser.objects.create_user(
        username="store-api-refresh-scoped",
        password="not-a-real-password",
        tenant=context["tenant"],
        user_type=CustomUser.UserType.INTERNAL,
    )
    authorization_a, authorization_b = context["authorizations"]
    _grant(
        user,
        ("integrations.store.authorize",),
        scope_config={"store_ids": [authorization_a.store_id]},
        scope_type=DataScope.ScopeType.CUSTOM,
    )
    _grant(
        user,
        ("integrations.credential.rotate",),
        scope_config={"store_ids": [authorization_b.store_id]},
        scope_type=DataScope.ScopeType.CUSTOM,
    )
    monkeypatch.setattr("apps.integrations.views.refresh_marketplace_authorization", lambda record, actor: record)
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        f"/api/internal/integrations/store-authorizations/{authorization_a.id}/refresh/",
        {},
        format="json",
    )
    assert response.status_code == 404


def test_store_authorization_scope_uses_all_dimensions_and_fails_closed_for_resource_type():
    context = _context()
    user = CustomUser.objects.create_user(
        username="store-api-scope-filter",
        password="not-a-real-password",
        tenant=context["tenant"],
        user_type=CustomUser.UserType.INTERNAL,
    )
    authorization_a, _authorization_b = context["authorizations"]
    role = _grant(
        user,
        ("integrations.store.view",),
        scope_config={
            "platforms": ["shopee"],
            "environments": ["pilot"],
            "regions": ["MY"],
            "integration_config_ids": [context["config"].id],
            "store_ids": [authorization_a.store_id],
        },
        scope_type=DataScope.ScopeType.CUSTOM,
    )
    queryset = MarketplaceStoreAuthorization.objects.filter(tenant=context["tenant"])
    assert list(filter_store_authorizations(user, queryset, "integrations.store.view")) == [authorization_a]

    scope = DataScope.objects.get(role=role)
    scope.config = {"resource_types": [SyncJob.ResourceType.SALES_ORDER]}
    scope.save(update_fields=["config"])
    assert not filter_store_authorizations(user, queryset, "integrations.store.view").exists()


def test_store_authorization_audits_and_serializes_nested_sensitive_history_without_mutation():
    context = _context()
    authorization = context["authorizations"][0]
    user = context["user"]
    created = _audit(
        authorization,
        user,
        "test_sensitive_audit",
        extra={
            "nested": {
                "credential_id": "synthetic-leak-credential",
                "token_id": "synthetic-leak-token",
                "access_token": "raw-access-token",
                "api_key": "raw-api-key",
                "secret": "raw-secret",
                "cookie": "raw-cookie",
                "session": "raw-session",
                "bearer": "raw-bearer",
                "bearer_token": "raw-bearer-token",
                "X-Api-Key": "raw-x-api-key",
                "Set-Cookie": "raw-set-cookie",
                "Proxy-Authorization": "raw-proxy-authorization",
                "safe_sibling": "kept",
                "token_refreshed": "state-kept",
                "authorization_status": "state-kept",
                "session_status": "state-kept",
                "items": [
                    {
                        "client_secret": "raw-client-secret",
                        "api_secret": "raw-api-secret",
                        "app_secret": "raw-app-secret",
                        "partner_key": "raw-partner-key",
                        "credential_ciphertext": "raw-ciphertext",
                        "safe": True,
                    }
                ],
            }
        },
    )
    assert "credential_id" not in str(created.masked_detail)
    assert "token_id" not in str(created.masked_detail)
    assert "synthetic-leak-credential" not in str(created.masked_detail)
    assert "raw-api-key" not in str(created.masked_detail)
    assert "raw-secret" not in str(created.masked_detail)
    assert "raw-cookie" not in str(created.masked_detail)
    assert "raw-session" not in str(created.masked_detail)
    assert "raw-bearer" not in str(created.masked_detail)
    assert "raw-x-api-key" not in str(created.masked_detail)
    assert "raw-set-cookie" not in str(created.masked_detail)
    assert "raw-proxy-authorization" not in str(created.masked_detail)
    assert created.masked_detail["nested"]["safe_sibling"] == "kept"
    assert created.masked_detail["nested"]["token_refreshed"] == "state-kept"
    assert created.masked_detail["nested"]["authorization_status"] == "state-kept"
    assert created.masked_detail["nested"]["session_status"] == "state-kept"

    historical = IntegrationAuditLog(
        tenant=context["tenant"],
        integration_config=context["config"],
        store_authorization=authorization,
        action="historical_sensitive_audit",
        actor=user,
        result=IntegrationAuditLog.Result.SUCCESS,
        masked_detail={
            "outer": {
                "credential_id": "historical-credential",
                "items": [
                    {
                        "refresh_token": "historical-refresh",
                        "signing_secret": "historical-signing-secret",
                        "webhook_secret": "historical-webhook-secret",
                        "api_key": "historical-api-key",
                        "secret": "historical-secret",
                        "cookie": "historical-cookie",
                        "session": "historical-session",
                        "bearer": "historical-bearer",
                        "X-Api-Key": "historical-x-api-key",
                        "Set-Cookie": "historical-set-cookie",
                        "Proxy-Authorization": "historical-proxy-authorization",
                        "safe": "kept",
                        "token_refreshed": "state-kept",
                        "authorization_status": "state-kept",
                        "session_status": "state-kept",
                    }
                ],
            }
        },
    )
    # Simulate a legacy row written before the shared write-time sanitizer;
    # the serializer must still redact it without mutating the stored detail.
    IntegrationAuditLog.objects.bulk_create([historical])
    historical.refresh_from_db()
    before = historical.masked_detail
    payload = IntegrationAuditLogSerializer(historical).data["masked_detail"]
    assert payload == {
        "outer": {
            "items": [
                {
                    "safe": "kept",
                    "token_refreshed": "state-kept",
                    "authorization_status": "state-kept",
                    "session_status": "state-kept",
                }
            ]
        }
    }
    historical.refresh_from_db()
    assert historical.masked_detail == before
