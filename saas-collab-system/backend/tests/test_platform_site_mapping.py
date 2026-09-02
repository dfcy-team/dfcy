import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import PlatformMaster, PlatformSiteMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def grant(user, *codes):
    role = Role.objects.create(tenant=user.tenant, code="mapping-role", name="Mapping role")
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code, "module": "masterdata", "action": code.rsplit(".", 1)[-1]}
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def test_mapping_preview_and_confirmed_apply_are_safe_and_idempotent():
    tenant = Tenant.objects.create(name="Mapping", code="mapping")
    user = CustomUser.objects.create_user(username="mapper", password="not-real", tenant=tenant, user_type="internal")
    grant(user, "masterdata.view", "masterdata.manage")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    exact_site = PlatformSiteMaster.objects.create(
        tenant=tenant, platform=platform, site_code="PH", name="Philippines", country_code="PH", currency_code="PHP"
    )
    PlatformSiteMaster.objects.create(
        tenant=tenant, platform=platform, site_code="SG-A", name="Singapore A", country_code="SG", currency_code="SGD"
    )
    PlatformSiteMaster.objects.create(
        tenant=tenant, platform=platform, site_code="SG-B", name="Singapore B", country_code="SG", currency_code="SGD"
    )
    exact = StoreMaster.objects.create(tenant=tenant, platform=platform, code="exact", name="Exact", country_code="PH", currency="PHP")
    ambiguous = StoreMaster.objects.create(tenant=tenant, platform=platform, code="ambiguous", name="Ambiguous", country_code="SG", currency="SGD")
    unmatched = StoreMaster.objects.create(tenant=tenant, platform=platform, code="unmatched", name="Unmatched", country_code="MY", currency="MYR")

    client = APIClient(); client.force_authenticate(user)
    url = "/api/internal/master-data/platform-sites/migration-preview/"
    preview = client.get(url)
    assert preview.status_code == 200
    assert preview.data["data"]["exact"] == 1
    assert preview.data["data"]["ambiguous"] == 1
    assert preview.data["data"]["unmatched"] == 1
    rows = {row["store_code"]: row for row in preview.data["data"]["rows"]}
    assert rows["exact"]["store_name"] == "Exact"
    assert rows["exact"]["candidates"][0]["site_code"] == "PH"

    payload = {"confirmed": True, "store_ids": [exact.id, ambiguous.id, unmatched.id], "idempotency_key": "mapping-batch-001"}
    applied = client.post(url, payload, format="json")
    assert applied.status_code == 200
    assert applied.data["data"]["applied"] == 1
    assert applied.data["data"]["conflicts"] == 2
    exact.refresh_from_db(); ambiguous.refresh_from_db(); unmatched.refresh_from_db()
    assert exact.platform_site_id == exact_site.id
    assert ambiguous.platform_site_id is None and unmatched.platform_site_id is None

    replay = client.post(url, payload, format="json")
    assert replay.status_code == 200
    assert replay.data["data"]["idempotent"] is True
    assert replay.data["data"]["applied"] == 1


def test_mapping_apply_requires_explicit_confirmation():
    tenant = Tenant.objects.create(name="Confirm", code="mapping-confirm")
    user = CustomUser.objects.create_user(username="confirm-user", password="not-real", tenant=tenant, user_type="internal")
    grant(user, "masterdata.manage")
    client = APIClient(); client.force_authenticate(user)
    response = client.post(
        "/api/internal/master-data/platform-sites/migration-preview/",
        {"confirmed": False, "store_ids": [1], "idempotency_key": "mapping-batch-002"}, format="json",
    )
    assert response.status_code == 400
