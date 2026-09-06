import io
import json
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    PlatformIntegrationConfig,
    WarehouseAuthorization,
    authorization_service_write,
)
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster, WarehouseMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _fixture():
    tenant = Tenant.objects.create(name="Preflight tenant", code="preflight-identity")
    user = CustomUser.objects.create_user(
        username="preflight-admin",
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_superuser=True,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="myjf",
        name="马来极风",
        platform_type="warehouse_third_party",
        status=StatusChoices.ACTIVE,
    )
    StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="store-my",
        name="Store MY",
        country_code="MY",
        currency="MYR",
        external_store_id="store-external-1",
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant,
        code="MY-WH-01",
        name="MY warehouse",
        country_code="MY",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
        service_platform=platform,
        status=StatusChoices.ACTIVE,
    )
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="jifeng_wms",
            account_alias="legacy-wms",
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            regions=["MY"],
            platform_config={
                "api_type": "inventory",
                "site_code": "MY",
                "warehouse_code": "LEGACY-WH-001",
            },
            credential_id="preflight-credential",
            token_id="preflight-token",
            credential_status=PlatformIntegrationConfig.CredentialStatus.CONFIGURED,
            created_by=user,
        )
        authorization = WarehouseAuthorization.objects.create(
            tenant=tenant,
            integration_config=config,
            warehouse=warehouse,
            provider="jifeng_wms",
            credential_id="preflight-credential",
            token_id="preflight-token",
            status=WarehouseAuthorization.Status.ACTIVE,
            created_by=user,
            updated_by=user,
        )
    return tenant, authorization


def _run_report(*args):
    output = io.StringIO()
    call_command("report_external_identity_preflight", *args, stdout=output)
    return json.loads(output.getvalue())


def test_preflight_reads_legacy_schema_without_selecting_new_columns():
    tenant, authorization = _fixture()

    from apps.integrations.management.commands import report_external_identity_preflight as command_module

    original_columns = command_module._table_columns

    def legacy_columns(table_name):
        columns = original_columns(table_name)
        if table_name == StoreMaster._meta.db_table:
            columns.discard("external_store_identity_key")
        if table_name == WarehouseAuthorization._meta.db_table:
            columns.difference_update(
                {
                    "external_warehouse_code",
                    "external_warehouse_region",
                    "external_warehouse_identity_key",
                }
            )
        return columns

    before = authorization.external_warehouse_code
    with patch.object(command_module, "_table_columns", side_effect=legacy_columns):
        report = _run_report("--tenant-id", str(tenant.id))

    assert report["schema"] == {
        "store_external_identity": "legacy",
        "warehouse_external_identity": "legacy",
    }
    assert report["counts"] == {
        "store_duplicate_groups": 0,
        "warehouse_duplicate_groups": 0,
        "warehouse_missing_identity": 0,
    }
    assert report["mutated"] is False
    authorization.refresh_from_db()
    assert authorization.external_warehouse_code == before == ""


def test_preflight_selects_binding_identity_after_migration():
    tenant, authorization = _fixture()
    authorization.external_warehouse_code = "BOUND-WH-001"
    authorization.external_warehouse_region = "MY"
    authorization.save(update_fields=["external_warehouse_code", "external_warehouse_region"])

    report = _run_report("--tenant-id", str(tenant.id))

    assert report["schema"] == {
        "store_external_identity": "available",
        "warehouse_external_identity": "available",
    }
    assert report["counts"]["warehouse_missing_identity"] == 0
    assert report["mutated"] is False
