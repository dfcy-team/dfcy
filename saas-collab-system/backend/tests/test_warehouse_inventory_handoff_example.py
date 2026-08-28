import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.commerce.models import InventorySnapshot
from apps.integrations.inventory_snapshot_contract import normalize_inventory_snapshot_record
from apps.integrations.models import PlatformIntegrationConfig
from apps.masterdata.models import WarehouseMaster
from tests.factories import create_internal_user, create_tenant


SAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "03_api"
    / "examples"
    / "warehouse_inventory_handoff.example.json"
)
FORBIDDEN_KEYS = {
    "app_secret",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "secret_key",
    "sign",
    "cookie",
}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).lower()
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def test_warehouse_inventory_example_matches_normalized_contract_and_has_no_credentials():
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "shopapi-handoff.v1"
    assert payload["synthetic"] is True
    assert payload["api_example"]["provider"] == "jifeng_wms"
    assert payload["api_example"]["mode"] == "read_only"
    assert FORBIDDEN_KEYS.isdisjoint(_walk_keys(payload))

    warehouses = {row["id"]: row for row in payload["warehouses"]}
    assert {row["country_code"] for row in warehouses.values()} == {"MY", "PH", "TH"}
    for snapshot in payload["inventory_snapshots"]:
        normalized = normalize_inventory_snapshot_record(
            {
                "contract_version": "inventory_snapshot.v1",
                **snapshot,
            }
        )
        assert normalized["site_code"] == warehouses[snapshot["warehouse_id"]]["country_code"]


@pytest.mark.django_db
def test_warehouse_inventory_example_importer_dry_run_rolls_back_all_rows():
    tenant = create_tenant(code="warehouse-handoff-test")
    actor = create_internal_user(tenant=tenant, username="warehouse-handoff-operator")
    stdout = StringIO()

    call_command(
        "import_saas_handoff_sample",
        str(SAMPLE_PATH),
        tenant_id=tenant.id,
        actor_id=actor.id,
        stdout=stdout,
    )

    assert '"warehouses": 4' in stdout.getvalue()
    assert '"inventory": 6' in stdout.getvalue()
    assert WarehouseMaster.objects.filter(tenant=tenant).count() == 0
    assert PlatformIntegrationConfig.objects.filter(tenant=tenant).count() == 0
    assert InventorySnapshot.objects.filter(tenant=tenant).count() == 0
