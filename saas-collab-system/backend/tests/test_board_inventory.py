from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import CustomUser
from apps.commerce.models import InventorySnapshot
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.sales_management.board_inventory import attach_board_inventory
from apps.tenants.models import Tenant


def _fixture(suffix):
    tenant = Tenant.objects.create(name=suffix, code=suffix)
    user = CustomUser.objects.create_user(username=f"board-stock-{suffix}", tenant=tenant,
                                          user_type=CustomUser.UserType.INTERNAL)
    permission, _ = Permission.objects.get_or_create(
        code="sales_management.view", defaults={"name": "Sales", "module": "sales_management", "action": "view"},
    )
    role = Role.objects.create(tenant=tenant, name="Sales", code=f"sales-stock-{suffix}")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="jifeng_wms", account_alias=suffix,
                                                      created_by=user)
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type="inventory_snapshot")
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id=f"run-{suffix}",
                                 idempotency_key=f"key-{suffix}", status="success", failed_count=0)
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code=f"wh-{suffix}", name=f"Warehouse {suffix}",
                                               country_code="PH", warehouse_type="owned")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{suffix}", product_name="Test product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"SKU-{suffix}", inventory_type="physical")
    return SimpleNamespace(user=user, tenant=tenant, run=run, warehouse=warehouse, sku=sku)


_DEFAULT_SKU = object()


def _snapshot(f, source, *, sku=_DEFAULT_SKU, qty=9, hours_ago=1, provided=None, run=None, warehouse=None):
    return InventorySnapshot.objects.create(
        tenant=f.tenant, site_code="PH", warehouse=warehouse or f.warehouse,
        internal_sku=f.sku if sku is _DEFAULT_SKU else sku,
        source_run=run or f.run, source_sku=source, available_qty=qty,
        provided_quantity_fields=["available_qty"] if provided is None else provided,
        snapshot_at_utc=datetime.now(UTC) - timedelta(hours=hours_ago),
        payload_hash=sha256(f"{source}:{qty}:{hours_ago}".encode()).hexdigest(),
    )


def _row(f, suffix="1"):
    return {"sku": suffix, "name": suffix, "sales_amount": "10", "units_sold": 1,
            "internal_sku_id": f.sku.id, "inventory_site": "PH", "inventory_type": "physical"}


def _attach(f, rows):
    group = {"sku_ranking": rows, "sku_rankings": {"sales_amount": list(rows), "units_sold": list(rows)}}
    attach_board_inventory(SimpleNamespace(user=f.user, _permission_resolution_cache=None), [group])
    return group


@pytest.mark.django_db
def test_board_inventory_attaches_only_recent_valid_matched_shared_stock():
    f = _fixture("stock-valid")
    _snapshot(f, "source-a", qty=4)
    row = _row(f)
    inventory = _attach(f, [row])["sku_ranking"][0]["inventory"]
    assert inventory["available_qty"] == 4
    assert inventory["status"] == "low"
    assert inventory["basis"] == "同站点已匹配仓共享库存"
    assert inventory["warehouses"] == [{"id": f.warehouse.id, "name": f.warehouse.name,
                                         "available_qty": 4, "status": "low"}]
    assert inventory["coverage_days"] is None


@pytest.mark.django_db
def test_latest_unmapped_or_missing_quantity_never_revives_older_stock():
    f = _fixture("stock-latest")
    _snapshot(f, "source-a", qty=8, hours_ago=2)
    _snapshot(f, "source-a", qty=0, hours_ago=1, sku=None)
    _snapshot(f, "source-b", qty=7, hours_ago=2)
    _snapshot(f, "source-b", qty=0, hours_ago=1, provided=[])
    failed_run = SyncRun.objects.create(tenant=f.tenant, sync_job=f.run.sync_job,
                                        run_id="failed-run", idempotency_key="failed-key",
                                        status="failed", failed_count=1)
    _snapshot(f, "source-c", qty=6, hours_ago=2)
    _snapshot(f, "source-c", qty=0, hours_ago=1, run=failed_run)
    rows = [_row(f, "a"), _row(f, "b"), _row(f, "c")]
    result = _attach(f, rows)["sku_ranking"]
    assert all(item["inventory"]["available_qty"] is None for item in result)
    assert all(item["inventory"]["warehouses"] == [] for item in result)


@pytest.mark.django_db
def test_zero_and_multiple_source_aliases_are_reported_without_summing():
    f = _fixture("stock-ambiguous")
    _snapshot(f, "source-zero", qty=0)
    zero = _attach(f, [_row(f)])["sku_ranking"][0]["inventory"]
    assert zero["available_qty"] == 0
    assert zero["status"] == "zero"

    _snapshot(f, "source-alias", qty=12)
    ambiguous = _attach(f, [_row(f)])["sku_ranking"][0]["inventory"]
    assert ambiguous["available_qty"] is None
    assert ambiguous["status"] == "ambiguous"
    assert ambiguous["warehouses"][0]["available_qty"] is None


@pytest.mark.django_db
def test_inventory_custom_scope_and_other_tenant_facts_do_not_leak():
    f = _fixture("stock-scope")
    DataScope.objects.filter(role__user_roles__user=f.user).update(
        scope_type=DataScope.ScopeType.CUSTOM, config={"warehouse_ids": [f.warehouse.id]},
    )
    hidden = WarehouseMaster.objects.create(tenant=f.tenant, code="hidden", name="Secret warehouse",
                                            country_code="PH", warehouse_type="owned")
    _snapshot(f, "visible", qty=3)
    _snapshot(f, "hidden", qty=20, warehouse=hidden)
    other = _fixture("stock-other-tenant")
    # Same SKU IDs cannot cross tenants; foreign facts are explicitly prevented by tenant filters.
    result = _attach(f, [_row(f)])["sku_ranking"][0]["inventory"]
    assert result["available_qty"] == 3
    assert all(row["name"] != "Secret warehouse" for row in result["warehouses"])
    assert other.tenant.id != f.tenant.id


@pytest.mark.django_db
def test_data_scope_denial_keeps_board_row_and_hides_inventory_details():
    f = _fixture("stock-denied")
    _snapshot(f, "secret", qty=25)
    DataScope.objects.filter(role__user_roles__user=f.user).update(
        scope_type=DataScope.ScopeType.CUSTOM, config={"warehouse_ids": ["invalid"]},
    )
    inventory = _attach(f, [_row(f)])["sku_ranking"][0]["inventory"]
    assert inventory["available_qty"] is None
    assert inventory["status"] == "permission"
    assert inventory["warehouses"] == []


@pytest.mark.django_db
def test_query_count_does_not_grow_with_rank_rows():
    f = _fixture("stock-query-count")
    rows = []
    for i in range(12):
        sku = ProductSKU.objects.create(tenant=f.tenant, spu=f.sku.spu, sku_code=f"SKU-{i}",
                                        inventory_type="physical")
        rows.append({**_row(f, str(i)), "internal_sku_id": sku.id})
    with CaptureQueriesContext(connection) as queries:
        _attach(f, rows)
    assert len(queries) <= 8
