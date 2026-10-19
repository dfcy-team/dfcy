from datetime import UTC, datetime

import pytest
from django.db import connection
from django.db.backends.mysql.base import DatabaseWrapper
from django.db.models import F, Q

from apps.commerce.models import InventorySnapshot
from apps.sales_management import views
from apps.sales_management.inventory_queries import is_broad_inventory_source, prefer_inventory_cover


def mysql_sql(queryset):
    # Compile for the actual server family without opening a network connection.
    mysql = DatabaseWrapper({"ENGINE": "django.db.backends.mysql", "NAME": "plan_test", "OPTIONS": {}, "TIME_ZONE": None})
    mysql.mysql_server_data = {
        "version": "8.4.11", "sql_mode": "STRICT_TRANS_TABLES",
        "default_storage_engine": "InnoDB", "sql_auto_is_null": False,
        "lower_case_table_names": 0, "has_zoneinfo_database": True,
    }
    return queryset.query.get_compiler(connection=mysql).as_sql()


def source():
    return InventorySnapshot.objects.filter(tenant_id=17, source_run_id__in=[11, 12]).order_by()


def test_mysql_hint_only_targets_ranking_base_and_keeps_parameters(monkeypatch):
    actual, params = mysql_sql(views._inventory_latest(source()))
    assert actual.count("FORCE INDEX (`idx_inv_latest_cover`)") == 1
    assert "FROM `inventory_snapshot` U0 FORCE INDEX" in actual
    assert "FROM `inventory_snapshot` FORCE INDEX" not in actual
    monkeypatch.setattr(views, "prefer_inventory_cover", lambda queryset: queryset)
    expected, expected_params = mysql_sql(views._inventory_latest(source()))
    assert params == expected_params
    assert actual.replace(" FORCE INDEX (`idx_inv_latest_cover`)", "") == expected


@pytest.mark.parametrize("filters", [
    {"warehouse_id": 3}, {"source_sku__icontains": "sku"},
    {"internal_sku_id": 9}, {"internal_sku__spu_id": 8},
    {"site_code__in": ["PH"]},
    {"snapshot_at_utc__gte": datetime(2026, 10, 1, tzinfo=UTC)},
    {"source_run__sync_job__integration_config__platform": "jifeng_wms"},
])
def test_selective_or_joined_sources_keep_optimizer_choice(filters):
    sql, _ = mysql_sql(views._inventory_latest(source().filter(**filters)))
    assert "FORCE INDEX" not in sql


def test_daily_ranking_keeps_time_index_choice():
    sql, _ = mysql_sql(views._inventory_latest(
        source().filter(snapshot_at_utc__gte=datetime(2026, 10, 1, tzinfo=UTC)), daily=True
    ))
    assert "FORCE INDEX" not in sql


def test_broad_daily_ranking_uses_cover_without_changing_sql_or_parameters(monkeypatch):
    actual, params = mysql_sql(views._inventory_latest(source(), daily=True))
    assert actual.count("FORCE INDEX (`idx_inv_latest_cover`)") == 1
    monkeypatch.setattr(views, "prefer_inventory_cover", lambda queryset: queryset)
    expected, expected_params = mysql_sql(views._inventory_latest(source(), daily=True))
    assert params == expected_params
    assert actual.replace(" FORCE INDEX (`idx_inv_latest_cover`)", "") == expected


def test_warehouse_options_cover_only_broad_authorized_id_projection(monkeypatch):
    original = source().select_related("warehouse", "internal_sku")
    actual, params = mysql_sql(views._inventory_warehouse_options(original, 17))
    assert actual.count("FORCE INDEX (`idx_inv_latest_cover`)") == 1
    assert "SELECT U0.`warehouse_id`" in actual
    assert "JOIN `masterdata_warehousemaster`" not in actual
    assert "FORCE INDEX" not in mysql_sql(original)[0]
    monkeypatch.setattr(views, "prefer_inventory_cover", lambda queryset: queryset)
    expected, expected_params = mysql_sql(views._inventory_warehouse_options(original, 17))
    assert params == expected_params
    assert actual.replace(" FORCE INDEX (`idx_inv_latest_cover`)", "") == expected


@pytest.mark.parametrize("filters", [{"warehouse_id": 3}, {"internal_sku_id": 9}, {"site_code": "PH"}])
def test_warehouse_options_selective_scope_retains_optimizer_choice(filters):
    sql, _ = mysql_sql(views._inventory_warehouse_options(source().filter(**filters), 17))
    assert "FORCE INDEX" not in sql


def test_hint_clones_never_mutate_source_or_accumulate():
    original = source()
    hinted = prefer_inventory_cover(original)
    assert "FORCE INDEX" not in mysql_sql(original)[0]
    assert mysql_sql(hinted)[0].count("FORCE INDEX") == 1
    assert mysql_sql(prefer_inventory_cover(hinted))[0].count("FORCE INDEX") == 1
    assert mysql_sql(hinted.all()) == mysql_sql(hinted)


@pytest.mark.parametrize("predicate", [
    Q(), Q(tenant_id=17), Q(source_run_id__in=[11]),
    Q(tenant_id__gt=17, source_run_id__in=[11]),
    Q(tenant_id=17, source_run_id__isnull=False),
    Q(tenant_id=17) | Q(source_run_id__in=[11]),
    ~Q(tenant_id=17, source_run_id__in=[11]),
    Q(tenant_id=F("source_run_id"), source_run_id__in=[11]),
])
def test_only_measured_literal_source_shape_is_hintable(predicate):
    assert not is_broad_inventory_source(InventorySnapshot.objects.filter(predicate))


def test_sqlite_keeps_original_portable_ranking():
    sql, _ = views._inventory_latest(source()).query.get_compiler(connection=connection).as_sql()
    if connection.vendor != "mysql":
        assert "FORCE INDEX" not in sql


def country_source():
    return source().filter(warehouse_id__in=[3], snapshot_at_utc__lte=datetime(2026, 10, 19, tzinfo=UTC))


def test_country_hint_only_ranks_clone_and_keeps_parameters(monkeypatch):
    from apps.sales_management import inventory_queries as iq
    original = country_source()
    actual, params = mysql_sql(iq.latest_country_inventory(original))
    assert actual.count('FORCE INDEX (`idx_inv_latest_cover`)') == 1
    assert 'FROM `inventory_snapshot` U0 FORCE INDEX' in actual
    assert 'FORCE INDEX' not in mysql_sql(original)[0]
    monkeypatch.setattr(iq, 'prefer_country_inventory_cover', lambda source: source)
    expected, expected_params = mysql_sql(iq.latest_country_inventory(original))
    assert params == expected_params
    assert actual.replace(' FORCE INDEX (`idx_inv_latest_cover`)', '') == expected


@pytest.mark.parametrize('filters', [
    {'internal_sku_id': 9}, {'source_sku': 'SKU'}, {'available_qty__gt': 0},
    {'source_run__status': 'success'}, {'snapshot_at_utc__gte': datetime(2026, 10, 1, tzinfo=UTC)},
    {'warehouse_id__in': list(range(1, 1002))}, {'source_run_id__in': list(range(1, 2002))},
    {'snapshot_at_utc__lte': F('ingested_at')},
])
def test_country_selective_or_unbounded_sources_are_unhinted(filters):
    from apps.sales_management.inventory_queries import latest_country_inventory
    sql, _ = mysql_sql(latest_country_inventory(country_source().filter(**filters)))
    assert 'FORCE INDEX' not in sql


def test_country_hint_rejects_or_not_and_missing_boundaries():
    from apps.sales_management.inventory_queries import prefer_country_inventory_cover
    for qs in (source(), InventorySnapshot.objects.filter(Q(tenant_id=17) | Q(warehouse_id=3)),
               country_source().exclude(source_sku='secret')):
        assert 'FORCE INDEX' not in mysql_sql(prefer_country_inventory_cover(qs))[0]
