import io
import importlib
import json
import secrets
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.masterdata.models import SupplierMaster
from apps.packing.models import PackingStandardVersion, _packing_domain_write_context
from apps.permissions.models import Permission
from apps.purchasing.uat_data import (
    ALL_CONSOLIDATION_PERMISSIONS,
    ALL_PACKING_PERMISSIONS,
    ALL_PURCHASE_PERMISSIONS,
    ALL_SHIPMENT_PERMISSIONS,
    DATA_VERSION,
    make_context,
)
from apps.purchasing.uat_credentials import (
    CredentialToolError,
    activate_credentials,
    revoke_credentials,
    status_credentials,
)
from apps.tenants.models import Tenant
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


pytestmark = pytest.mark.django_db(transaction=True)


PERMISSION_CODES = (
    *ALL_PURCHASE_PERMISSIONS,
    *ALL_PACKING_PERMISSIONS,
    *ALL_CONSOLIDATION_PERMISSIONS,
    *ALL_SHIPMENT_PERMISSIONS,
)


@pytest.fixture(autouse=True)
def uat_fixture(db):
    # The command receives the exact loaded test database name; use a second
    # call after setup because pytest-django creates that database lazily.
    for code in PERMISSION_CODES:
        Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "sc-uat", "action": code.rsplit(".", 1)[-1]},
        )
    with _packing_domain_write_context():
        PackingStandardVersion.objects.get_or_create(
            code="packing-v1",
            version=1,
            defaults={"title": "UAT standard", "rules": {"exact_completion_required": True}, "is_active": True},
        )
    from django.db import connection

    call_command(
        "seed_supply_flow_uat",
        "generate",
        environment="local",
        database_name=str(connection.settings_dict["NAME"]),
        data_version=DATA_VERSION,
        payload="fixture-v1",
        confirm_local=True,
        allow_inmemory_test=True,
        as_json=True,
        stdout=io.StringIO(),
    )


def _context():
    return make_context(DATA_VERSION, "fixture-v1")


def _capture_secret(_credentials):
    # Deliberately no print/log/file side effect.  Tests inspect the in-memory
    # value without ever writing the generated password to pytest output.
    _capture_secret.values = list(_credentials)


_capture_secret.values = []


def _test_password():
    """Return an unpredictable password for users created directly in tests."""
    return secrets.token_urlsafe(24)


def test_activate_defaults_to_dry_run_and_metadata_has_no_secret():
    result = activate_credentials(_context(), ["SC-UAT-A-procurement"])
    assert result["status"] == "DRY_RUN"
    assert "password" not in json.dumps(result).lower()
    assert CustomUser.objects.get(username="SC-UAT-A-procurement").uat_credential_status == "never"


def test_uat_lease_migration_is_independent_of_parallel_accounts_changes():
    migration = importlib.import_module("apps.accounts.migrations.0004_customuser_uat_credential_lease")
    assert migration.Migration.dependencies == [("accounts", "0002_miniappidentity")]
    assert {
        (operation.model_name, operation.name)
        for operation in migration.Migration.operations
    } == {
        ("customuser", "uat_credential_activated_at"),
        ("customuser", "uat_credential_expires_at"),
        ("customuser", "uat_credential_batch_digest"),
        ("customuser", "uat_credential_status"),
    }


def test_activation_is_random_one_time_and_repeated_activation_cannot_extend():
    result = activate_credentials(
        _context(),
        ["SC-UAT-A-procurement"],
        duration_hours=Decimal("2"),
        apply=True,
        secret_sink=_capture_secret,
    )
    assert result["status"] == "ACTIVATED"
    password = _capture_secret.values[0][1]
    assert password not in json.dumps(result)
    user = CustomUser.objects.get(username="SC-UAT-A-procurement")
    old_expiry, old_digest = user.uat_credential_expires_at, user.uat_credential_batch_digest
    assert user.check_password(password)
    with pytest.raises(CredentialToolError, match="revoke first"):
        activate_credentials(_context(), [user.username], apply=True, secret_sink=_capture_secret)
    user.refresh_from_db()
    assert user.uat_credential_expires_at == old_expiry
    assert user.uat_credential_batch_digest == old_digest


def test_secret_sink_failure_rolls_back_entire_batch_without_secret_output():
    users = ["SC-UAT-A-procurement", "SC-UAT-A-packer"]

    def failing_sink(_credentials):
        raise RuntimeError("sink unavailable")

    with pytest.raises(CredentialToolError, match="rolled back"):
        activate_credentials(_context(), users, apply=True, secret_sink=failing_sink)
    assert all(
        CustomUser.objects.get(username=username).uat_credential_status == "never"
        for username in users
    )
    assert all(
        not CustomUser.objects.get(username=username).has_usable_password()
        for username in users
    )


def test_privileged_inactive_superuser_rpa_and_non_uat_subjects_are_rejected_without_writes():
    user = CustomUser.objects.get(username="SC-UAT-A-procurement")
    user.is_staff = True
    user.save(update_fields=["is_staff", "is_superuser", "user_type", "is_active", "updated_at"])
    with pytest.raises(CredentialToolError, match="privileged"):
        status_credentials(_context(), [user.username])
    user.is_staff = False
    user.is_superuser = True
    user.save(update_fields=["is_staff", "is_superuser", "updated_at"])
    with pytest.raises(CredentialToolError, match="privileged"):
        status_credentials(_context(), [user.username])
    user.is_superuser = False
    user.user_type = CustomUser.UserType.RPA
    user.save(update_fields=["is_superuser", "user_type", "updated_at"])
    with pytest.raises(CredentialToolError, match="privileged"):
        status_credentials(_context(), [user.username])
    user.user_type = CustomUser.UserType.INTERNAL
    user.is_active = False
    user.save(update_fields=["user_type", "is_active", "updated_at"])
    with pytest.raises(CredentialToolError, match="privileged"):
        status_credentials(_context(), [user.username])
    user.is_active = True
    user.save(update_fields=["is_staff", "is_superuser", "user_type", "is_active", "updated_at"])
    with pytest.raises(CredentialToolError, match="allowlist"):
        status_credentials(_context(), ["not-a-uat-user"])


def test_supplier_web_login_refresh_claims_and_api2_channel_mutex():
    result = activate_credentials(
        _context(),
        ["SC-UAT-A-supplier-a"],
        apply=True,
        secret_sink=_capture_secret,
    )
    assert result["status"] == "ACTIVATED"
    password = _capture_secret.values[0][1]
    user = CustomUser.objects.get(username="SC-UAT-A-supplier-a")
    supplier_id = user.external_profile.supplier_id
    client = APIClient()

    login = client.post(
        "/api/external/auth/login/",
        {"username": user.username, "password": password},
        format="json",
    )
    assert login.status_code == 200
    access = login.json()["access"]
    refresh = login.json()["refresh"]
    access_token = AccessToken(access)
    refresh_token = RefreshToken(refresh)
    assert access_token["channel"] == refresh_token["channel"] == "supplier_web"
    assert int(access_token["tenant_id"]) == int(user.tenant_id)
    assert int(access_token["supplier_id"]) == int(supplier_id)

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    # The real API2 supplier route accepts the typed channel and binding.
    assert client.get("/api/external/supplier/consolidations/assignments/").status_code == 200
    # The same access token cannot broaden generic/internal or MiniApp paths.
    assert client.get("/api/internal/auth/me/").status_code == 401
    assert client.get("/api/miniapp/auth/me/").status_code == 401

    refreshed = APIClient().post(
        "/api/external/auth/refresh/", {"refresh": refresh}, format="json"
    )
    assert refreshed.status_code == 200
    assert AccessToken(refreshed.json()["access"])["channel"] == "supplier_web"


def test_supplier_web_refresh_rejects_stale_binding_and_expired_lease():
    activate_credentials(
        _context(),
        ["SC-UAT-A-supplier-a"],
        apply=True,
        secret_sink=_capture_secret,
    )
    user = CustomUser.objects.get(username="SC-UAT-A-supplier-a")
    password = _capture_secret.values[0][1]
    login = APIClient().post(
        "/api/external/auth/login/",
        {"username": user.username, "password": password},
        format="json",
    )
    assert login.status_code == 200
    access = login.json()["access"]
    refresh = login.json()["refresh"]
    supplier_b = SupplierMaster.objects.get(tenant=user.tenant, code="SC-UAT-SUP-B")

    # A signed token with a stale supplier claim cannot be replayed after a
    # binding change; the API re-reads the current profile and supplier.
    forged = RefreshToken(refresh)
    forged["supplier_id"] = supplier_b.id
    forged_response = APIClient().post(
        "/api/external/auth/refresh/", {"refresh": str(forged)}, format="json"
    )
    assert forged_response.status_code == 401

    user.uat_credential_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["uat_credential_expires_at", "updated_at"])
    assert APIClient().post(
        "/api/external/auth/login/",
        {"username": user.username, "password": password},
        format="json",
    ).status_code in {400, 401}
    assert APIClient().post(
        "/api/external/auth/refresh/", {"refresh": refresh}, format="json"
    ).status_code == 401
    expired_client = APIClient()
    expired_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert expired_client.get("/api/external/supplier/consolidations/assignments/").status_code == 401


def test_ordinary_external_supplier_with_empty_lease_fields_can_use_new_channel():
    tenant = Tenant.objects.create(name="Ordinary supplier web", code="ordinary-supplier-web")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="ordinary-supplier", name="Ordinary supplier")
    ordinary_password = _test_password()
    user = CustomUser.objects.create_user(
        username="ordinary-external",
        password=ordinary_password,
        tenant=tenant,
        user_type=CustomUser.UserType.EXTERNAL,
    )
    ExternalUserProfile.objects.create(user=user, tenant=tenant, supplier_id=supplier.id)
    response = APIClient().post(
        "/api/external/auth/login/",
        {"username": user.username, "password": ordinary_password},
        format="json",
    )
    assert response.status_code == 200
    assert AccessToken(response.json()["access"])["channel"] == "supplier_web"


def test_supplier_web_endpoint_rejects_internal_rpa_and_other_token_channels():
    tenant = Tenant.objects.create(name="Supplier channel matrix", code="supplier-channel-matrix")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="supplier-channel", name="Supplier channel")
    external_password = _test_password()
    external = CustomUser.objects.create_user(
        username="supplier-channel-external",
        password=external_password,
        tenant=tenant,
        user_type=CustomUser.UserType.EXTERNAL,
    )
    ExternalUserProfile.objects.create(user=external, tenant=tenant, supplier_id=supplier.id)
    internal_password = _test_password()
    internal = CustomUser.objects.create_user(
        username="supplier-channel-internal",
        password=internal_password,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    rpa_password = _test_password()
    rpa = CustomUser.objects.create_user(
        username="supplier-channel-rpa",
        password=rpa_password,
        tenant=tenant,
        user_type=CustomUser.UserType.RPA,
    )
    for username, password in (
        (internal.username, internal_password),
        (rpa.username, rpa_password),
    ):
        assert APIClient().post(
            "/api/external/auth/login/",
            {"username": username, "password": password},
            format="json",
        ).status_code in {400, 401}

    internal_token = RefreshToken.for_user(internal)
    internal_client = APIClient()
    internal_client.credentials(HTTP_AUTHORIZATION=f"Bearer {internal_token.access_token}")
    assert internal_client.get("/api/external/supplier/consolidations/assignments/").status_code == 403

    miniapp_token = RefreshToken.for_user(external)
    miniapp_token["channel"] = "miniapp"
    miniapp_client = APIClient()
    miniapp_client.credentials(HTTP_AUTHORIZATION=f"Bearer {miniapp_token.access_token}")
    assert miniapp_client.get("/api/external/supplier/consolidations/assignments/").status_code == 403


def test_revoke_is_exact_and_does_not_touch_non_uat_account():
    activate_credentials(_context(), ["SC-UAT-A-procurement"], apply=True, secret_sink=_capture_secret)
    other_tenant = Tenant.objects.create(code="ordinary-tenant", name="Ordinary tenant")
    ordinary_password = _test_password()
    ordinary = CustomUser.objects.create_user(
        username="ordinary-user",
        password=ordinary_password,
        tenant=other_tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    revoke_credentials(_context(), ["SC-UAT-A-procurement"], apply=True)
    uat_user = CustomUser.objects.get(username="SC-UAT-A-procurement")
    assert uat_user.uat_credential_status == "revoked"
    assert not uat_user.has_usable_password()
    ordinary.refresh_from_db()
    assert ordinary.check_password(ordinary_password)


def test_expired_lease_rejects_login_refresh_and_existing_access_token():
    activate_credentials(_context(), ["SC-UAT-A-procurement"], apply=True, secret_sink=_capture_secret)
    password = _capture_secret.values[0][1]
    client = APIClient()
    login = client.post(
        "/api/internal/auth/login/",
        {"username": "SC-UAT-A-procurement", "password": password},
        format="json",
    )
    assert login.status_code == 200
    access, refresh = login.json()["access"], login.json()["refresh"]
    user = CustomUser.objects.get(username="SC-UAT-A-procurement")
    user.uat_credential_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["uat_credential_expires_at", "updated_at"])
    assert client.post(
        "/api/internal/auth/login/",
        {"username": user.username, "password": password},
        format="json",
    ).status_code in {400, 401}
    assert client.post("/api/internal/auth/refresh/", {"refresh": refresh}, format="json").status_code == 401
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert client.get("/api/internal/auth/me/").status_code == 401


def test_duration_limit_and_command_json_never_contain_password(capsys):
    with pytest.raises(CredentialToolError, match="no more than 8"):
        activate_credentials(_context(), ["SC-UAT-A-procurement"], duration_hours=Decimal("8.01"))
    from django.db import connection

    call_command(
        "uat_credentials",
        "activate",
        "--username",
        "SC-UAT-A-procurement",
        "--environment",
        "local",
        "--database-name",
        str(connection.settings_dict["NAME"]),
        "--confirm-local",
        "--allow-inmemory-test",
        "--json",
    )
    output = capsys.readouterr().out
    assert "DRY_RUN" in output
    assert "password" not in output.lower()
