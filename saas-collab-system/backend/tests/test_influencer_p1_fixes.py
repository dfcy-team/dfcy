import importlib
import json

import pytest
from django.apps import apps as django_apps
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers.models import Influencer, InfluencerContact, InfluencerProfile
from apps.influencers.serializers import mask_handle
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.services import check_user_permission
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


INFLUENCER_CODES = (
    "influencers.view",
    "influencers.manage",
    "influencers.outreach.view",
    "influencers.outreach.manage",
    "influencers.fulfillment.view",
    "influencers.fulfillment.manage",
    "influencers.catalog.view",
)


def grant_permissions(tenant, username, *codes):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"role-{username}", name=username)
    permissions = []
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={
                "name": code,
                "module": "influencers",
                "action": code.split(".", 1)[1],
            },
        )
        permissions.append(permission)
    role.permissions.add(*permissions)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=DataScope.ScopeType.ALL,
        config={},
    )
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def test_0030_removes_all_influencer_permissions_from_role_001_and_preserves_manager_roles():
    tenant = Tenant.objects.create(name="Migration tenant", code="migration-p1")
    default_role = Role.objects.create(tenant=tenant, code="001", name="Default")
    manager_role = Role.objects.create(tenant=tenant, code="002", name="Influencer manager")
    permissions = [
        Permission.objects.get_or_create(
            code=code,
            defaults={
                "name": code,
                "module": "influencers",
                "action": code.split(".", 1)[1],
            },
        )[0]
        for code in INFLUENCER_CODES
    ]
    default_role.permissions.add(*permissions)
    manager_role.permissions.add(*permissions)

    migration = importlib.import_module(
        "apps.permissions.migrations.0030_remove_influencer_permissions_from_role_001"
    )
    migration.remove_influencer_permissions_from_role_001(django_apps, None)
    migration.remove_influencer_permissions_from_role_001(django_apps, None)

    assert set(default_role.permissions.values_list("code", flat=True)).isdisjoint(INFLUENCER_CODES)
    assert set(manager_role.permissions.values_list("code", flat=True)) == set(INFLUENCER_CODES)


def test_role_001_no_longer_grants_influencer_access_after_forward_migration():
    tenant = Tenant.objects.create(name="Permission tenant", code="permission-p1")
    user, _ = grant_permissions(tenant, "permission-p1-user", "influencers.view")
    role = user.user_roles.get().role
    role.code = "001"
    role.save(update_fields=["code"])

    migration = importlib.import_module(
        "apps.permissions.migrations.0030_remove_influencer_permissions_from_role_001"
    )
    migration.remove_influencer_permissions_from_role_001(django_apps, None)

    user.refresh_from_db()
    assert check_user_permission(user, "influencers.view") is False


def test_influencer_detail_contacts_and_resolve_responses_are_masked_and_audit_is_safe():
    tenant = Tenant.objects.create(name="Privacy tenant", code="privacy-p1")
    user, client = grant_permissions(
        tenant,
        "privacy-p1-user",
        "influencers.view",
        "influencers.manage",
        "influencers.fulfillment.manage",
    )
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="privacy-creator",
        name="Safe display name",
        platform="TikTok",
        handle="secret-handle",
        contact_name="Private contact",
        contact_phone="13800138000",
        contact_email="private@example.test",
        notes="private note",
    )
    InfluencerProfile.objects.create(
        tenant=tenant,
        influencer=influencer,
        external_influencer_id="external-secret-id",
        profile_url="https://example.test/private-profile",
        profile_notes="private profile note",
    )
    InfluencerContact.objects.create(
        tenant=tenant,
        influencer=influencer,
        channel="email",
        value="private-contact@example.test",
        created_by=user,
    )

    detail = client.get(f"/api/internal/influencers/{influencer.pk}/")
    assert detail.status_code == 200
    detail_payload = detail.data["data"]
    detail_text = json.dumps(detail_payload, ensure_ascii=False)
    for raw in (
        "secret-handle",
        "Private contact",
        "13800138000",
        "private@example.test",
        "private note",
        "external-secret-id",
        "https://example.test/private-profile",
        "private profile note",
        "private-contact@example.test",
    ):
        assert raw not in detail_text
    assert detail_payload["handle_masked"] == mask_handle("secret-handle")
    assert "handle" not in detail_payload
    assert "contact_phone" not in detail_payload
    assert "contact_email" not in detail_payload
    assert "external_influencer_id" not in detail_payload["profile"]
    assert "profile_url" not in detail_payload["profile"]
    assert "profile_notes" not in detail_payload["profile"]
    assert detail_payload["contacts"][0]["masked_value"]
    assert "value" not in detail_payload["contacts"][0]

    contact_response = client.get(f"/api/internal/influencers/{influencer.pk}/contacts/")
    assert contact_response.status_code == 200
    assert "value" not in contact_response.data["data"][0]
    assert contact_response.data["data"][0]["masked_value"]

    resolved = client.get("/api/internal/influencers/resolve/", {"q": "secret-handle"})
    assert resolved.status_code == 200
    assert "secret-handle" not in json.dumps(resolved.data, ensure_ascii=False)
    assert resolved.data["data"]["candidates"][0]["handle_masked"] == mask_handle("secret-handle")
    assert "handle" not in resolved.data["data"]["candidates"][0]

    created = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "new-secret-account"},
        format="json",
    )
    assert created.status_code == 201
    assert "new-secret-account" not in json.dumps(created.data, ensure_ascii=False)
    assert "handle" not in created.data["data"]
    assert created.data["data"]["handle_masked"] == mask_handle("new-secret-account")
    audit = OperationLog.objects.filter(action="create_from_fulfillment").latest("id")
    assert "new-secret-account" not in json.dumps(audit.after_data, ensure_ascii=False)
    assert "handle" not in audit.after_data


def _contact_client(code):
    tenant = Tenant.objects.create(name=f"Contact tenant {code}", code=f"contact-{code}")
    user, client = grant_permissions(tenant, f"contact-user-{code}", "influencers.view", "influencers.manage")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code=f"contact-creator-{code}",
        name="Contact creator",
        platform="TikTok",
    )
    return tenant, user, client, influencer


def test_contacts_patch_updates_rows_with_locks_and_masked_response():
    tenant, user, client, influencer = _contact_client("normal")
    old = InfluencerContact.objects.create(
        tenant=tenant,
        influencer=influencer,
        channel="email",
        value="old@example.test",
        is_primary=True,
        created_by=user,
    )

    response = client.patch(
        f"/api/internal/influencers/{influencer.pk}/contacts/",
        {"contacts": [{"channel": "phone", "value": "13800138000", "is_primary": True}]},
        format="json",
    )

    assert response.status_code == 200
    assert "value" not in response.data["data"][0]
    assert response.data["data"][0]["masked_value"] == "***8000"
    old.refresh_from_db()
    assert old.is_active is False
    assert old.is_primary is False
    assert InfluencerContact.objects.filter(
        influencer=influencer,
        value="13800138000",
        is_active=True,
        is_primary=True,
    ).exists()


def test_contacts_patch_empty_collection_deactivates_existing_rows_without_bulk_update():
    tenant, user, client, influencer = _contact_client("empty")
    contact = InfluencerContact.objects.create(
        tenant=tenant,
        influencer=influencer,
        channel="email",
        value="empty@example.test",
        is_primary=True,
        created_by=user,
    )

    response = client.patch(
        f"/api/internal/influencers/{influencer.pk}/contacts/",
        {"contacts": []},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["data"] == []
    contact.refresh_from_db()
    assert contact.is_active is False
    assert contact.is_primary is False


def test_contacts_patch_rolls_back_deactivation_and_new_rows_on_model_validation_failure():
    tenant, user, client, influencer = _contact_client("rollback")
    existing = InfluencerContact.objects.create(
        tenant=tenant,
        influencer=influencer,
        channel="email",
        value="rollback@example.test",
        is_primary=True,
        created_by=user,
    )

    response = client.patch(
        f"/api/internal/influencers/{influencer.pk}/contacts/",
        {
            "contacts": [
                {"channel": "phone", "value": "13800138000", "is_primary": True},
                {"channel": "whatsapp", "value": "rollback-contact", "is_primary": True},
            ]
        },
        format="json",
    )

    assert response.status_code == 422
    existing.refresh_from_db()
    assert existing.is_active is True
    assert existing.is_primary is True
    assert not InfluencerContact.objects.filter(
        influencer=influencer,
        value__in=("13800138000", "rollback-contact"),
    ).exists()
