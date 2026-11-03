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
from apps.products.models import ProductCategory, ProductSKU, ProductSPU
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


def _snapshot(f, source, *, sku=_DEFAULT_SKU, qty=9, transit=0, hours_ago=1, provided=None, run=None, warehouse=None):
    return InventorySnapshot.objects.create(
        tenant=f.tenant, site_code="PH", warehouse=warehouse or f.warehouse,
        internal_sku=f.sku if sku is _DEFAULT_SKU else sku,
        source_run=run or f.run, source_sku=source, available_qty=qty, in_transit_qty=transit,
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
def test_transit_is_exposed_only_when_source_provided_it():
    f = _fixture("stock-transit")
    _snapshot(f, "source-a", qty=4, transit=6, provided=["available_qty", "in_transit_qty"])
    inventory = _attach(f, [_row(f)])['sku_ranking'][0]['inventory']
    assert inventory["available_qty"] == 4
    assert inventory["in_transit_qty"] == 6


@pytest.mark.django_db
def test_transit_only_snapshot_keeps_available_unknown():
    f = _fixture("stock-transit-only")
    _snapshot(f, "source-a", qty=99, transit=6, provided=["in_transit_qty"])
    inventory = _attach(f, [_row(f)])['sku_ranking'][0]['inventory']
    assert inventory["available_qty"] is None
    assert inventory["in_transit_qty"] == 6


@pytest.mark.django_db
def test_multiple_warehouses_keep_independent_partial_quantity_coverage():
    f = _fixture("stock-multi-field")
    second = WarehouseMaster.objects.create(tenant=f.tenant, code="wh-transit-only", name="Transit only",
                                            country_code="PH", warehouse_type="owned")
    _snapshot(f, "source-a", qty=4, transit=0, provided=["available_qty"])
    _snapshot(f, "source-a", qty=0, transit=8, provided=["in_transit_qty"], warehouse=second)
    inventory = _attach(f, [_row(f)])['sku_ranking'][0]['inventory']
    assert inventory["available_qty"] == 4
    assert inventory["partial"] is True
    assert inventory["in_transit_qty"] == 8
    assert inventory["transit_partial"] is True
    assert inventory["warehouses"][0]["available_qty"] == 4
    assert inventory["warehouses"][1]["in_transit_qty"] == 8


@pytest.mark.django_db
def test_category_inventory_deduplicates_category_skus_and_preserves_transit():
    f = _fixture("stock-category")
    category = ProductCategory.objects.create(tenant=f.tenant, level=1, code="1", name="Mapped")
    f.sku.spu.category_node = category
    f.sku.spu.save(update_fields=["category_node"])
    second = ProductSKU.objects.create(tenant=f.tenant, spu=f.sku.spu, sku_code="SKU-CAT-2", inventory_type="physical")
    _snapshot(f, "source-a", qty=4, transit=3, provided=["available_qty", "in_transit_qty"])
    _snapshot(f, "source-b", sku=second, qty=7, transit=2, provided=["available_qty", "in_transit_qty"])
    row = {"key": f"category:{category.id}", "inventory_category_id": category.id,
           "inventory_spu_ids": [f.sku.spu_id, f.sku.spu_id], "inventory_countries": ["PH"]}
    group = {"product_rankings": {"category": {"sales_amount": [row], "units_sold": [row]}}}
    attach_board_inventory(SimpleNamespace(user=f.user, _permission_resolution_cache=None), [group])
    assert row["inventory"]["available_qty"] == 11
    assert row["inventory"]["in_transit_qty"] == 5
    assert row["inventory"]["partial"] is False


@pytest.mark.django_db
def test_category_inventory_spans_sales_countries_with_partial_known_sum():
    f = _fixture("stock-category-countries")
    category = ProductCategory.objects.create(tenant=f.tenant, level=1, code="1", name="Mapped")
    f.sku.spu.category_node = category
    f.sku.spu.save(update_fields=["category_node"])
    _snapshot(f, "source-a", qty=4, transit=3, provided=["available_qty", "in_transit_qty"])
    row = {"key": f"category:{category.id}", "inventory_category_id": category.id,
           "inventory_spu_ids": [f.sku.spu_id], "inventory_countries": ["PH", "TH"]}
    group = {"product_rankings": {"category": {"sales_amount": [row], "units_sold": [row]}}}
    attach_board_inventory(SimpleNamespace(user=f.user, _permission_resolution_cache=None), [group])
    assert row["inventory"]["available_qty"] == 4
    assert row["inventory"]["partial"] is True
    assert row["inventory"]["transit_partial"] is True


@pytest.mark.django_db
def test_spu_inventory_sums_all_child_skus_once_per_country_and_reports_country_breakdown():
    f = _fixture("stock-spu-aggregate")
    second = ProductSKU.objects.create(tenant=f.tenant, spu=f.sku.spu, sku_code="SKU-SECOND", inventory_type="physical")
    _snapshot(f, "source-a", qty=4, sku=f.sku)
    _snapshot(f, "source-b", qty=7, sku=second)
    spu_row = {"mapped_spu_id": f.sku.spu_id, "inventory_countries": ["PH"], "sales_amount": "10", "units_sold": 1}
    group = {"product_rankings": {"product_spu": {"sales_amount": [spu_row], "units_sold": [spu_row]}}}
    attach_board_inventory(SimpleNamespace(user=f.user, _permission_resolution_cache=None), [group])
    inventory = spu_row["inventory"]
    assert inventory["available_qty"] == 11
    assert inventory["country_breakdown"] == [{"country": "PH", "available_qty": 11}]
    assert inventory["partial"] is False
    assert len(inventory["warehouses"]) == 1
    assert inventory["warehouses"][0]["country"] == "PH"


@pytest.mark.django_db
def test_spu_currency_rows_keep_country_scope_and_unknown_total_is_none():
    f = _fixture("stock-spu-row-country")
    _snapshot(f, "source-a", qty=4)
    ph_row = {"mapped_spu_id": f.sku.spu_id, "inventory_countries": ["PH"]}
    th_row = {"mapped_spu_id": f.sku.spu_id, "inventory_countries": ["TH"]}
    empty_spu = ProductSPU.objects.create(tenant=f.tenant, spu_code="SPU-EMPTY", product_name="No stock")
    empty_row = {"mapped_spu_id": empty_spu.id, "inventory_countries": ["TH"]}
    groups = [
        {"currency": "PHP", "product_rankings": {"product_spu": {"sales_amount": [ph_row], "units_sold": []}}},
        {"currency": "THB", "product_rankings": {"product_spu": {"sales_amount": [th_row, empty_row], "units_sold": []}}},
    ]
    attach_board_inventory(SimpleNamespace(user=f.user, _permission_resolution_cache=None), groups)
    assert ph_row["inventory"]["available_qty"] == 4
    assert ph_row["inventory"]["country_breakdown"] == [{"country": "PH", "available_qty": 4}]
    assert th_row["inventory"]["available_qty"] is None
    assert th_row["inventory"]["partial"] is True
    assert empty_row["inventory"]["available_qty"] is None
    assert empty_row["inventory"]["partial"] is True


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

@pytest.mark.django_db
def test_category_inventory_keeps_each_currency_spu_scope():
    f = _fixture('category-currency-scope')
    category = ProductCategory.objects.create(tenant=f.tenant, level=1, code='1', name='Category')
    f.sku.spu.category_node = category
    f.sku.spu.save(update_fields=['category_node'])
    other_spu = ProductSPU.objects.create(tenant=f.tenant, spu_code='OTHER', product_name='Other', category_node=category)
    other_sku = ProductSKU.objects.create(tenant=f.tenant, spu=other_spu, sku_code='OTHER-SKU', inventory_type='physical')
    _snapshot(f, 'first', qty=4)
    _snapshot(f, 'second', qty=7, sku=other_sku)
    rows = [dict(inventory_category_id=category.id, inventory_spu_ids=[spu], inventory_countries=['PH']) for spu in [f.sku.spu_id, other_spu.id]]
    groups = [dict(currency=currency, product_rankings={'category': {'sales_amount': [row]}}) for currency, row in zip(['USD', 'EUR'], rows)]
    attach_board_inventory(SimpleNamespace(user=f.user, _permission_resolution_cache=None), groups)
    assert [row['inventory']['available_qty'] for row in rows] == [4, 7]

