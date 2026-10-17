import pytest
from django.db import connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext

from apps.commerce.models import RefundReturn, SalesOrder
from apps.integrations.models import SyncJob
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope
from apps.sales_management.filter_catalog import sales_filter_catalog
from tests.test_sales_management import client_for, create_order, create_run, create_scope, grant, user_for


def _raw_order_update(order, **fields):
    # QuerySet.update bypasses this project's validated manager and models old
    # rows created by bulk imports before write-time validation was enforced.
    QuerySet.update(SalesOrder.objects.filter(pk=order.pk), **fields)


@pytest.mark.django_db
def test_catalog_uses_scoped_sales_facts_and_keeps_fact_platform_pairs():
    tenant, platform, store, _ = create_scope("catalog-sales")
    order = create_order(tenant, store, "catalog")
    second_platform = PlatformMaster.objects.create(
        tenant=tenant, code="catalog-fact-platform", name="Fact platform", platform_type="lazada"
    )
    same_type_platform = PlatformMaster.objects.create(
        tenant=tenant, code="catalog-fact-platform-2", name="Fact platform two", platform_type="lazada"
    )
    # Simulate a legacy/bulk-loaded fact that bypassed model validation.
    _raw_order_update(order, platform_id=second_platform.pk)
    duplicate_order = create_order(tenant, store, "catalog-duplicate")
    _raw_order_update(duplicate_order, platform_id=same_type_platform.pk)
    blank_order = create_order(tenant, store, "catalog-blank")
    _raw_order_update(blank_order, platform_id=second_platform.pk, currency="", normalized_status="")
    hidden_tenant, _, hidden_store, _ = create_scope("catalog-hidden")
    create_order(hidden_tenant, hidden_store, "hidden")

    orders = SalesOrder.objects.filter(tenant_id=tenant.pk, store_id=store.pk)
    result = sales_filter_catalog(
        orders,
        RefundReturn.objects.none(),
        SyncJob.objects.filter(tenant_id=tenant.pk),
    )

    assert result["platforms"] == ["lazada"]
    assert result["stores"] == [{
        "id": store.pk,
        "code": store.code,
        "name": store.name,
        "region": store.country_code,
        "platform": "lazada",
    }]
    assert result["currencies"] == ["", order.currency]
    assert result["order_statuses"] == ["", order.normalized_status]
    assert result["refund_statuses"] == []
    assert result["sites"] == result["warehouses"] == []


@pytest.mark.django_db
def test_catalog_keeps_order_currencies_and_refund_only_currency_out_of_catalog():
    tenant, platform, store, _ = create_scope("catalog-currencies")
    order = create_order(tenant, store, "catalog-php")
    second_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="catalog-th-store", name="TH", country_code="TH",
        currency="THB", timezone="Asia/Bangkok",
    )
    create_order(tenant, second_store, "catalog-thb")
    refund_run = create_run(tenant, "refund_return", "catalog-currency-refund")
    RefundReturn.objects.create(
        tenant=tenant, platform=platform, store=store, source_run=refund_run,
        external_return_id="RETURN-CATALOG-CURRENCY", case_type="refund_only", raw_status="COMPLETED",
        normalized_status="completed", requested_at_utc=order.created_at_utc,
        updated_at_utc=order.updated_at_utc, currency="USD", refund_amount="1", payload_hash="c" * 64,
    )
    result = sales_filter_catalog(
        SalesOrder.objects.filter(tenant_id=tenant.pk),
        RefundReturn.objects.filter(tenant_id=tenant.pk),
        SyncJob.objects.filter(tenant_id=tenant.pk),
    )

    assert result["currencies"] == ["PHP", "THB"]
    assert "USD" not in result["currencies"]
    assert result["refund_statuses"] == ["completed"]


@pytest.mark.django_db
def test_catalog_does_not_query_inventory_or_expand_caller_scope():
    tenant, _, store, _ = create_scope("catalog-query")
    other_tenant, _, other_store, _ = create_scope("catalog-query-hidden")
    create_order(tenant, store, "query-visible")
    create_order(other_tenant, other_store, "query-hidden")
    scoped_orders = SalesOrder.objects.filter(tenant_id=tenant.pk, store_id=store.pk)

    with CaptureQueriesContext(connection) as captured:
        result = sales_filter_catalog(
            scoped_orders,
            RefundReturn.objects.none(),
            SyncJob.objects.filter(tenant_id=tenant.pk),
        )

    assert len(result["stores"]) == 1
    assert result["stores"][0]["id"] == store.pk
    assert all("inventory_snapshot" not in query["sql"].lower() for query in captured.captured_queries)


@pytest.mark.django_db
def test_sales_catalog_endpoint_honors_custom_store_scope_and_legacy_endpoint_remains_available():
    tenant, _, visible_store, _ = create_scope("catalog-api-visible")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant, platform=visible_store.platform, code="catalog-api-hidden", name="Hidden",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    create_order(tenant, visible_store, "catalog-api-visible")
    create_order(tenant, hidden_store, "catalog-api-hidden")
    viewer = user_for(tenant, "catalog-api-viewer")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [visible_store.pk]})
    client = client_for(viewer)

    with CaptureQueriesContext(connection) as captured:
        response = client.get("/api/internal/commerce/filters/?catalog=sales")
    legacy_response = client.get("/api/internal/commerce/filters/")

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]["stores"]] == [visible_store.pk]
    assert all("inventory_snapshot" not in query["sql"].lower() for query in captured.captured_queries)
    assert legacy_response.status_code == 200
    assert "warehouses" in legacy_response.json()["data"]


@pytest.mark.django_db
def test_sales_scope_projection_keeps_tenant_and_store_without_ordered_self_subquery():
    from apps.sales_management.scopes import filter_sales_queryset

    tenant, _, visible_store, _ = create_scope("catalog-direct")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant, platform=visible_store.platform, code="catalog-direct-hidden", name="Hidden",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    create_order(tenant, visible_store, "direct-visible")
    create_order(tenant, hidden_store, "direct-hidden")
    foreign, _, foreign_store, _ = create_scope("catalog-direct-foreign")
    create_order(foreign, foreign_store, "direct-foreign")
    viewer = user_for(tenant, "catalog-direct-viewer")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM,
          {"store_ids": [visible_store.pk, foreign_store.pk]})
    scoped = filter_sales_queryset(viewer, "sales_management.view", SalesOrder.objects.filter(tenant=tenant))
    projection = scoped.order_by().values_list("tenant_id", "platform_id", "store_id").distinct()
    assert list(projection) == [(tenant.pk, visible_store.platform_id, visible_store.pk)]
    assert "SELECT U0." not in str(projection.query)
    assert not projection.query.order_by


@pytest.mark.django_db
def test_low_cardinality_candidates_never_return_hidden_or_out_of_range_values(monkeypatch):
    from apps.sales_management.filter_catalog import _tenant_distinct_values

    tenant, _, store, _ = create_scope("catalog-values")
    visible = create_order(tenant, store, "values-visible")
    _raw_order_update(visible, currency="", normalized_status="")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant, platform=store.platform, code="values-hidden", name="Hidden",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    hidden = create_order(tenant, hidden_store, "values-hidden")
    _raw_order_update(hidden, currency="USD", normalized_status="hidden-status")
    scoped = SalesOrder.objects.filter(tenant=tenant, store=store, pk=visible.pk)
    for field in ("currency", "normalized_status"):
        expected = _tenant_distinct_values(scoped, field)
        assert _tenant_distinct_values(scoped, field, fact_tenants={tenant.pk}) == expected == [""]
        assert _tenant_distinct_values(scoped.none(), field, fact_tenants={tenant.pk}) == []
    monkeypatch.setattr("apps.sales_management.filter_catalog.MAX_VALUE_CANDIDATES", 0)
    assert _tenant_distinct_values(scoped, "currency", fact_tenants={tenant.pk}) == [""]


@pytest.mark.django_db
def test_sales_scope_role_branches_do_not_cross_combine_or_duplicate_rows():
    from apps.permissions.models import Permission, Role, UserRole
    from apps.sales_management.scopes import filter_sales_queryset

    tenant, _, store, _ = create_scope("catalog-role-or")
    second = StoreMaster.objects.create(
        tenant=tenant, platform=store.platform, code="role-or-second", name="Second",
        country_code="MY", currency="MYR", timezone="Asia/Kuala_Lumpur",
    )
    a = create_order(tenant, store, "branch-a")
    b = create_order(tenant, second, "branch-b")
    crossed = create_order(tenant, store, "branch-crossed")
    _raw_order_update(crossed, region="MY")
    viewer = user_for(tenant, "catalog-role-or-viewer")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM,
          {"store_ids": [store.pk], "regions": ["PH"]})
    permission = Permission.objects.get(code="sales_management.view")
    for index, config in enumerate([
        {"store_ids": [second.pk], "regions": ["MY"]},
        {"store_ids": [store.pk], "regions": ["PH"]},
    ]):
        role = Role.objects.create(tenant=tenant, code=f"catalog-or-{index}", name=f"Catalog {index}")
        role.permissions.add(permission)
        UserRole.objects.create(tenant=tenant, user=viewer, role=role)
        DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM, config=config)
    scoped = filter_sales_queryset(viewer, "sales_management.view", SalesOrder.objects.filter(tenant=tenant))
    assert set(scoped.values_list("pk", flat=True)) == {a.pk, b.pk}
    assert scoped.count() == 2
