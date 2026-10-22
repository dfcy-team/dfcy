from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.masterdata.models import CountrySiteMaster, WarehouseMaster
from apps.supply_chain.dashboard_inventory import inventory_data
from tests.test_supply_chain_v2_foundation import internal_user, world


@pytest.fixture
def inventory_facts(world):
    tenant, actor = world["tenant"], internal_user(world, username="inventory-cockpit",
        codes=("supply.v2.view", "supply.v2.manage", "sales_management.view"))
    wh_us = WarehouseMaster.objects.create(tenant=tenant, code="warehouse-us", name="US WMS",
        country_code="US", warehouse_type="third_party")
    ca = world["country_ca"]
    WarehouseMaster.objects.create(tenant=tenant, code="warehouse-ca", name="Canada WMS",
        country_code="CA", warehouse_type="third_party")
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="jifeng_wms",
        account_alias="cockpit-wms", created_by=actor)
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type="inventory_snapshot")
    sku = world["sku"]
    now = timezone.now()

    def snapshot(warehouse, source_sku, *, hours=1, quantity=7, provided=True, status="success", internal_sku=sku):
        run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id=f"run-{source_sku}-{hours}-{status}",
            idempotency_key=f"key-{source_sku}-{hours}-{status}", status=status)
        return InventorySnapshot.objects.create(tenant=tenant, site_code=warehouse.country_code,
            warehouse=warehouse, internal_sku=internal_sku, source_run=run, source_sku=source_sku,
            available_qty=quantity, provided_quantity_fields=["available_qty"] if provided else [],
            snapshot_at_utc=now-timedelta(hours=hours), payload_hash="a"*64)

    wh_ca = WarehouseMaster.objects.get(tenant=tenant, code="warehouse-ca")
    old = snapshot(wh_us, "SKU-A", hours=3, quantity=900)
    current = snapshot(wh_us, "SKU-A", hours=1, quantity=7)
    snapshot(wh_ca, "SKU-B", hours=1, quantity=11)
    countries = CountrySiteMaster.objects.filter(tenant=tenant)
    scoped = (countries, None, None, None, None, None)
    return locals()


@pytest.mark.django_db
def test_latest_success_totals_exclude_history_and_country_filter(inventory_facts):
    f = inventory_facts
    data = inventory_data(f["actor"], f["scoped"])
    assert data["status"] == "available"
    assert data["totals"]["available_quantity"] == 18
    us = next(row for row in data["countries"] if row["country_code"] == "US")
    assert us["available_quantity"] == 7
    assert us["snapshots"] == 1

    only_us = inventory_data(f["actor"], f["scoped"], country_id=f["world"]["country"].pk)
    assert [row["country_code"] for row in only_us["countries"]] == ["US"]
    assert only_us["totals"]["available_quantity"] == 7


@pytest.mark.django_db
def test_long_sync_history_keeps_every_run_in_latest_selection(inventory_facts):
    f = inventory_facts
    SyncRun.objects.bulk_create([SyncRun(tenant=f['tenant'], sync_job=f['job'],
        run_id=f'long-history-{i}', idempotency_key=f'long-history-{i}', status='success') for i in range(2001)])
    newest_run=SyncRun.objects.create(tenant=f['tenant'], sync_job=f['job'],
        run_id='long-history-newest',idempotency_key='long-history-newest',status='failed')
    InventorySnapshot.objects.create(tenant=f['tenant'],site_code='US',warehouse=f['wh_us'],
        internal_sku=f['world']['sku'],source_run=newest_run,source_sku='SKU-A',available_qty=0,
        provided_quantity_fields=['available_qty'],snapshot_at_utc=timezone.now(),payload_hash='c'*64)
    data=inventory_data(f['actor'],f['scoped'],country_id=f['world']['country'].pk)
    assert data['countries'][0]['failed']==1
    assert data['totals']['available_quantity'] is None


@pytest.mark.django_db
def test_failed_missing_stale_and_virtual_latest_are_never_reliable_zero(inventory_facts):
    f = inventory_facts
    current = f["current"]
    newer = InventorySnapshot.objects.create(tenant=f["tenant"], site_code="US", warehouse=f["wh_us"],
        internal_sku=f["world"]["sku"], source_run=SyncRun.objects.create(tenant=f["tenant"], sync_job=f["job"],
            run_id="failed-latest", idempotency_key="failed-latest", status="failed"),
        source_sku="SKU-A", available_qty=0, provided_quantity_fields=["available_qty"],
        snapshot_at_utc=timezone.now(), payload_hash="b"*64)
    data = inventory_data(f["actor"], f["scoped"], country_id=f["world"]["country"].pk)
    us = data["countries"][0]
    assert us["available_quantity"] is None
    assert us["failed"] == 1 and us["unknown"] == 0

    newer.source_run.status = "success"
    newer.source_run.save(update_fields=["status"])
    newer.provided_quantity_fields = []
    newer.save(update_fields=["provided_quantity_fields"])
    missing = inventory_data(f["actor"], f["scoped"], country_id=f["world"]["country"].pk)["countries"][0]
    assert missing["available_quantity"] is None and missing["unknown"] == 1

    reported_failure = SyncRun.objects.create(tenant=f["tenant"], sync_job=f["job"], run_id="reported-failure",
        idempotency_key="reported-failure", status="success", failed_count=1)
    InventorySnapshot.objects.create(tenant=f["tenant"], site_code="US", warehouse=f["wh_us"],
        internal_sku=f["world"]["sku"], source_run=reported_failure, source_sku="SKU-REPORTED-FAIL",
        available_qty=20, provided_quantity_fields=["available_qty"], snapshot_at_utc=timezone.now(),
        payload_hash="d"*64)
    failed_count = inventory_data(f["actor"], f["scoped"], country_id=f["world"]["country"].pk)["countries"][0]
    assert failed_count["available_quantity"] is None and failed_count["failed"] == 1

    stale_run = SyncRun.objects.create(tenant=f["tenant"], sync_job=f["job"], run_id="stale-latest",
        idempotency_key="stale-latest", status="success")
    InventorySnapshot.objects.create(tenant=f["tenant"], site_code="US", warehouse=f["wh_us"],
        internal_sku=f["world"]["sku"], source_run=stale_run, source_sku="SKU-STALE",
        available_qty=99, provided_quantity_fields=["available_qty"],
        snapshot_at_utc=timezone.now()-timedelta(hours=25), payload_hash="c"*64)
    stale = inventory_data(f["actor"], f["scoped"], country_id=f["world"]["country"].pk)["countries"][0]
    assert stale["available_quantity"] is None and stale["stale"] == 1

    f["world"]["sku"].inventory_type = "virtual"
    f["world"]["sku"].save(update_fields=["inventory_type"])
    # Virtual-only inventory is excluded and is never represented as zero stock.
    virtual = inventory_data(f["actor"], f["scoped"], country_id=f["world"]["country"].pk)["countries"][0]
    assert virtual["snapshots"] == 0 and virtual["available_quantity"] is None


@pytest.mark.django_db
def test_supply_view_does_not_grant_inventory_access(inventory_facts):
    f = inventory_facts
    viewer = internal_user(f["world"], username="supply-only", codes=("supply.v2.view",))
    data = inventory_data(viewer, f["scoped"])
    assert data["status"] == "unavailable"
    assert data["totals"]["available_quantity"] is None
    assert data["countries"] == []


@pytest.mark.django_db
def test_multiple_warehouses_sum_and_conflicts_block_both_countries(inventory_facts):
    f=inventory_facts
    second=WarehouseMaster.objects.create(tenant=f['tenant'],code='second-us',name='Other US',country_code='US')
    f['snapshot'](second,'SECOND-US',quantity=13)
    result=inventory_data(f['actor'],f['scoped'])
    assert next(r for r in result['countries'] if r['country_code']=='US')['available_quantity']==20
    conflict=f['snapshot'](second,'CONFLICT',quantity=99)
    # Deliberate historical inconsistency fixture; production writes remain validated.
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('UPDATE inventory_snapshot SET site_code=%s WHERE id=%s',['CA',conflict.pk])
    result=inventory_data(f['actor'],f['scoped'])
    assert all(row['available_quantity'] is None for row in result['countries'])
    assert all(row['country_conflicts']>0 for row in result['countries'])


@pytest.mark.django_db
def test_inventory_section_uses_real_api_and_respects_stock_permission(inventory_facts):
    from tests.test_supply_chain_v2_logistics import client, BASE
    f=inventory_facts
    response=client(f['actor']).get(BASE+'dashboard/?section=inventory&country_id='+str(f['world']['country'].pk))
    assert response.status_code==200,response.data
    assert response.data['data']['totals']['available_quantity']==7
    assert response.data['data']['section']=='inventory'
    assert response.data['data']['generated_at']


@pytest.mark.django_db
def test_inventory_countries_are_discovered_without_supply_orders_and_respect_country_scope(inventory_facts):
    from apps.permissions.models import DataScope
    from tests.test_supply_chain_v2_foundation import internal_user
    from tests.test_supply_chain_v2_logistics import client, BASE
    f = inventory_facts
    scoped_actor = internal_user(f['world'], username='ca-inventory-only',
        scope=DataScope.ScopeType.CUSTOM, config={'regions': ['CA']},
        codes=('supply.v2.view', 'supply.v2.manage', 'sales_management.view'))
    api = client(scoped_actor)
    response = api.get(BASE + 'dashboard/?section=inventory')
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert [row['country_code'] for row in data['country_options']] == ['CA']
    assert [row['country_code'] for row in data['countries']] == ['CA']
    assert data['totals']['available_quantity'] == 11
    assert api.get(BASE + 'dashboard/?section=inventory&country_id=' + str(f['world']['country'].pk)).status_code == 404
