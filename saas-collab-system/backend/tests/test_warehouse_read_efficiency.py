"""Page-bounded warehouse reads keep status and credential scope semantics."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import WarehouseAuthorization
from apps.masterdata.models import PlatformMaster, WarehouseMaster
from apps.masterdata.serializers import WarehouseMasterSerializer
from apps.permissions.models import DataScope
from apps.tenants.models import Tenant
from tests.test_sales_management import client_for, create_run, grant, user_for

pytestmark = pytest.mark.django_db


def fixture(code, count=20):
    tenant = Tenant.objects.create(code=code, name=code)
    user = user_for(tenant, code)
    grant(user, "masterdata.view")
    grant(user, "integrations.warehouse.view")
    platform = PlatformMaster.objects.create(tenant=tenant, code="myjf", name="马来极风", platform_type="warehouse_third_party")
    run = create_run(tenant, "inventory_snapshot", code, platform="jifeng_wms")
    now = timezone.now()
    warehouses = []
    for i in range(count):
        warehouse = WarehouseMaster.objects.create(tenant=tenant, code=f"wh-{i:03}", name=str(i), country_code="MY",
            service_platform=platform, warehouse_type="third_party")
        warehouses.append(warehouse)
        WarehouseAuthorization.objects.create(tenant=tenant, integration_config=run.sync_job.integration_config,
            warehouse=warehouse, provider="jifeng_wms", credential_id="synthetic", status="active",
            validation_status="verified", last_verified_at=now, email="synthetic@example.test", created_by=user, updated_by=user)
        if i % 2:
            InventorySnapshot.objects.bulk_create([InventorySnapshot(tenant=tenant, warehouse=warehouse, source_run=run,
                site_code="MY", source_sku=f"sku-{j}", snapshot_at_utc=now-timedelta(seconds=j), payload_hash="a"*64)
                for j in range(2)])
    return user, warehouses


def test_warehouse_page_query_budget_and_individual_representation_agree():
    user, warehouses = fixture("warehouse-read-budget")
    client = client_for(user)
    with CaptureQueriesContext(connection) as small:
        first = client.get("/api/internal/master-data/warehouses/?page_size=2")
    with CaptureQueriesContext(connection) as larger:
        second = client.get("/api/internal/master-data/warehouses/?page_size=20")
    assert first.status_code == second.status_code == 200
    assert len(larger) <= len(small) + 2
    assert len(larger) < 45
    expected = [WarehouseMasterSerializer(row, context={"request": SimpleNamespace(user=user)}).data
        for row in WarehouseMaster.objects.filter(pk__in=[row.pk for row in warehouses]).select_related("service_platform")]
    assert second.json()["data"]["results"] == expected
    assert first.json()["data"]["results"] == expected[:2]
    assert second.json()["data"]["count"] == 20
    assert client.get("/api/internal/master-data/warehouses/?page=11&page_size=2").status_code == 404
    next_page = client.get("/api/internal/master-data/warehouses/?page=2&page_size=2").json()["data"]
    assert next_page["results"] == expected[2:4]
    assert "page=1" in next_page["previous"] and "page=3" in next_page["next"]


def test_bulk_warehouse_metadata_keeps_scope_and_rechecks_next_request():
    user, warehouses = fixture("warehouse-read-scope", 2)
    foreign, _ = fixture("warehouse-read-foreign", 1)
    scope = DataScope.objects.get(role__user_roles__user=user, role__permissions__code="integrations.warehouse.view")
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = {"warehouse_ids": [warehouses[0].pk]}
    scope.save()
    client = client_for(user)
    rows = client.get("/api/internal/master-data/warehouses/").json()["data"]["results"]
    assert {row["id"] for row in rows} == {row.pk for row in warehouses}
    assert rows[0]["api_email"] == "synthetic@example.test"
    assert "api_email" not in rows[1]
    # Connectivity is public archive state in the existing contract; metadata
    # still requires integrations.warehouse.view and its data scope.
    assert all(row["api_connected"] for row in rows)
    scope.config = {"warehouse_ids": [warehouses[1].pk]}
    scope.save()
    rows = client.get("/api/internal/master-data/warehouses/").json()["data"]["results"]
    assert "api_email" not in rows[0] and rows[1]["api_email"] == "synthetic@example.test"
    assert client_for(foreign).get("/api/internal/master-data/warehouses/").json()["data"]["count"] == 1


def test_empty_warehouse_page_keeps_the_existing_envelope():
    tenant = Tenant.objects.create(code="empty-warehouse-read", name="Empty")
    user = user_for(tenant, "empty-warehouse-read")
    grant(user, "masterdata.view")
    response = client_for(user).get("/api/internal/master-data/warehouses/")
    assert response.status_code == 200
    assert response.json()["data"] == {"count":0, "next":None, "previous":None, "results":[]}
