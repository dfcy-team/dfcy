import os
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.accounts.models import CustomUser
from apps.finance.models import ReconciliationException, ReconciliationMatch
from apps.permissions.models import Role
from apps.permissions.services import check_user_permission
from apps.products.models import ProductSKU
from apps.purchasing.models import PurchaseOrder
from apps.suppliers.models import SupplierTask
from apps.tenants.models import Tenant


SEED_ENV = {
    "LOCAL_SANDBOX_ENVIRONMENT": "local-sandbox",
    "LOCAL_SANDBOX_DEMO_PASSWORD": "local-test-password-12345",
    "SANDBOX_ALLOW_REAL_PLATFORM": "false",
    "SANDBOX_ALLOW_HIGH_RISK_AUTOMATION": "false",
}


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_seed_requires_explicit_local_confirmation():
    with patch.dict(os.environ, SEED_ENV, clear=False):
        with pytest.raises(CommandError, match="--confirm-local"):
            call_command("seed_local_sandbox", module="core", test_mode=True)


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_seed_rejects_real_platform_or_high_risk_switches():
    for key in ("SANDBOX_ALLOW_REAL_PLATFORM", "SANDBOX_ALLOW_HIGH_RISK_AUTOMATION"):
        env = {**SEED_ENV, key: "true"}
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(CommandError, match="disabled"):
                call_command(
                    "seed_local_sandbox",
                    module="core",
                    confirm_local=True,
                    test_mode=True,
                )


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_integration_seed_is_idempotent_and_keeps_finance_permission_separate():
    with patch.dict(os.environ, SEED_ENV, clear=False):
        call_command(
            "seed_local_sandbox",
            module="integration",
            confirm_local=True,
            test_mode=True,
        )
        call_command(
            "seed_local_sandbox",
            module="integration",
            confirm_local=True,
            test_mode=True,
        )

    assert Tenant.objects.filter(code__in=("local-sandbox-a", "local-sandbox-b")).count() == 2
    assert ProductSKU.objects.filter(sku_code__startswith="LOCAL-SKU-").count() == 2
    assert PurchaseOrder.objects.filter(po_no__startswith="LOCAL-PO-").count() == 2
    assert SupplierTask.objects.filter(task_no__startswith="LOCAL-TASK-").count() == 2
    assert ReconciliationMatch.objects.filter(tenant__code="local-sandbox-a").count() == 1
    assert ReconciliationException.objects.filter(tenant__code="local-sandbox-a").count() == 1

    operator = CustomUser.objects.get(username="local_internal_operator")
    finance = CustomUser.objects.get(username="local_finance_reviewer")
    assert operator.is_superuser is False
    assert finance.is_superuser is False
    assert check_user_permission(operator, "analytics.view") is True
    assert check_user_permission(operator, "finance.view") is False
    assert check_user_permission(finance, "finance.view") is True
    assert check_user_permission(finance, "finance.reconcile") is True
    assert Role.objects.get(code="creator_mock_viewer").permissions.count() == 0
