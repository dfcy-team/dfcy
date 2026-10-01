"""Regression cases from the independent authorization review."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.permissions.authorization import apply_batch, load_preview
from apps.permissions.models import PermissionChange, UserRole
from apps.accounts.models import CustomUser
from tests.test_authorization_workbench import setup_tenant, user, role, preview, apply

pytestmark = pytest.mark.django_db


def test_expired_administrator_cannot_allow_last_effective_admin_removal():
    tenant, actor, client = setup_tenant("expired-admin")
    admin_role = role(tenant, "administrator")
    active, expired = user(tenant, "active-admin"), user(tenant, "expired-admin")
    UserRole.objects.create(tenant=tenant, user=active, role=admin_role)
    UserRole.objects.create(tenant=tenant, user=expired, role=admin_role, valid_until=timezone.now()-timedelta(seconds=1))
    assert preview(client, [active.pk], [], operation="offboard").status_code == 409
    result = client.post(f"/api/internal/system/users/{active.pk}/status/", {"is_active": False}, format="json")
    assert result.status_code == 409
    active.refresh_from_db()
    assert active.is_active


def test_two_valid_previews_cannot_remove_all_administrators():
    tenant, actor, client = setup_tenant("two-admin-batches")
    admin_role = role(tenant, "administrator")
    admins = [user(tenant, f"admin-{i}") for i in range(2)]
    for member in admins:
        UserRole.objects.create(tenant=tenant, user=member, role=admin_role)
    plans = [preview(client, [member.pk], [], operation="offboard") for member in admins]
    assert all(response.status_code == 200 for response in plans)
    assert apply(client, plans[0].json()["data"]["preview_token"]).status_code == 200
    assert apply(client, plans[1].json()["data"]["preview_token"]).status_code == 409
    assert CustomUser.objects.filter(pk__in=[member.pk for member in admins], is_active=True).count() == 1


def test_retry_rechecks_audit_after_target_locks_before_stale_version():
    tenant, actor, client = setup_tenant("concurrent-replay")
    member = user(tenant, "member")
    replacement = role(tenant, "new-position", ["catalog.view"])
    response = preview(client, [member.pk], [replacement.code])
    plan = load_preview(actor, response.json()["data"]["preview_token"])
    assert apply(client, response.json()["data"]["preview_token"]).status_code == 200
    audit = PermissionChange.objects.get(batch_id=plan["batch_id"])
    query = PermissionChange.objects.filter(batch_id=plan["batch_id"])
    # Model the first query occurring before the competing commit, then the
    # second query after waiting for its user lock. No SQLite thread timing.
    with patch("apps.permissions.authorization.PermissionChange.objects.filter", return_value=query), patch.object(type(query), "first", side_effect=[None, audit]):
        result = apply_batch(actor, plan, CustomUser.objects.filter(pk=member.pk), [replacement])
    assert result["replayed"] is True
    assert PermissionChange.objects.filter(tenant=tenant).count() == 1
