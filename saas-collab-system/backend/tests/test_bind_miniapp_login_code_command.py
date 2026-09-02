from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.accounts.miniapp_auth import digest_miniapp_subject
from apps.accounts.models import CustomUser, MiniAppIdentity
from apps.tenants.models import Tenant


@pytest.mark.django_db
@override_settings(MINIAPP_AUTH_MODE="sandbox")
def test_bind_miniapp_login_code_hashes_subject_without_echoing_it():
    tenant = Tenant.objects.create(name="Miniapp Bind Tenant", code="miniapp-bind-tenant")
    user = CustomUser.objects.create_user(
        username="miniapp-bind-target",
        password="unused-test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    stdout = StringIO()

    with patch("sys.stdin", StringIO("sandbox:one-time-subject\n")):
        call_command(
            "bind_miniapp_login_code",
            "--username",
            user.username,
            "--code-stdin",
            stdout=stdout,
        )

    identity = MiniAppIdentity.objects.get(user=user)
    assert identity.subject_digest == digest_miniapp_subject(
        MiniAppIdentity.Provider.WECHAT,
        "one-time-subject",
    )
    assert "one-time-subject" not in stdout.getvalue()
    assert identity.subject_digest not in stdout.getvalue()
