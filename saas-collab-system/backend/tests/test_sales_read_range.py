from datetime import UTC, datetime

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from apps.sales_management.views import _scoped_orders
from tests.test_sales_management import create_order, create_scope, grant, user_for


def authenticated_request(user, params):
    raw = APIRequestFactory().get("/", params)
    force_authenticate(raw, user=user)
    return Request(raw)


@pytest.mark.django_db
def test_scoped_orders_group_identical_store_local_date_ranges():
    tenant, _, store_a, _ = create_scope("read-range-a")
    store_b = StoreMaster.objects.create(
        tenant=tenant, platform=store_a.platform, code="read-range-b", name="B",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    store_c = StoreMaster.objects.create(
        tenant=tenant, platform=store_a.platform, code="read-range-c", name="C",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    order_a = create_order(tenant, store_a, "read-range-a")
    order_b = create_order(tenant, store_b, "read-range-b")
    order_c = create_order(tenant, store_c, "read-range-c")
    order_c.created_at_utc = datetime(2026, 8, 16, 15, 59, tzinfo=UTC)
    order_c.save(update_fields=["created_at_utc"])
    viewer = user_for(tenant, "read-range-viewer")
    grant(viewer, "sales_management.view")

    orders = _scoped_orders(authenticated_request(viewer, {
        "store_ids": f"{store_a.id},{store_b.id},{store_c.id}",
        "date_from": "2026-08-17", "date_to": "2026-08-17",
    }), "sales_management.view")

    assert list(orders.values_list("id", flat=True)) == [order_b.id, order_a.id]


@pytest.mark.django_db
def test_scoped_orders_apply_distinct_local_ranges_for_mixed_timezones():
    tenant, _, manila, _ = create_scope("read-range-mixed")
    los_angeles = StoreMaster.objects.create(
        tenant=tenant, platform=manila.platform, code="read-range-la", name="LA",
        country_code="US", currency="USD", timezone="America/Los_Angeles",
    )
    manila_inside = create_order(tenant, manila, "mixed-manila-in")
    la_inside = create_order(tenant, los_angeles, "mixed-la-in")
    la_before = create_order(tenant, los_angeles, "mixed-la-before")
    la_after = create_order(tenant, los_angeles, "mixed-la-after")
    manila_inside.created_at_utc = datetime(2026, 8, 16, 16, 0, tzinfo=UTC)
    la_inside.created_at_utc = datetime(2026, 8, 17, 7, 0, tzinfo=UTC)
    la_before.created_at_utc = datetime(2026, 8, 17, 6, 59, tzinfo=UTC)
    la_after.created_at_utc = datetime(2026, 8, 18, 7, 0, tzinfo=UTC)
    for order in (manila_inside, la_inside, la_before, la_after):
        order.save(update_fields=["created_at_utc"])
    viewer = user_for(tenant, "read-range-mixed-viewer")
    grant(viewer, "sales_management.view")

    orders = _scoped_orders(authenticated_request(viewer, {
        "store_ids": f"{manila.id},{los_angeles.id}",
        "date_from": "2026-08-17", "date_to": "2026-08-17",
    }), "sales_management.view")

    assert set(orders.values_list("id", flat=True)) == {manila_inside.id, la_inside.id}


@pytest.mark.django_db
def test_scoped_orders_preserve_dst_half_open_day_boundaries():
    tenant, _, store, _ = create_scope("read-range-dst")
    store.timezone = "America/Los_Angeles"
    store.save(update_fields=["timezone"])
    before = create_order(tenant, store, "read-range-before")
    start = create_order(tenant, store, "read-range-start")
    end = create_order(tenant, store, "read-range-end")
    after = create_order(tenant, store, "read-range-after")
    for order, timestamp in (
        (before, datetime(2026, 3, 8, 7, 59, tzinfo=UTC)),
        (start, datetime(2026, 3, 8, 8, 0, tzinfo=UTC)),
        (end, datetime(2026, 3, 9, 6, 59, tzinfo=UTC)),
        (after, datetime(2026, 3, 9, 7, 0, tzinfo=UTC)),
    ):
        order.created_at_utc = timestamp
        order.save(update_fields=["created_at_utc"])
    viewer = user_for(tenant, "read-range-dst-viewer")
    grant(viewer, "sales_management.view")

    orders = _scoped_orders(authenticated_request(viewer, {
        "store_id": str(store.id), "date_from": "2026-03-08", "date_to": "2026-03-08",
    }), "sales_management.view")

    assert set(orders.values_list("id", flat=True)) == {start.id, end.id}


@pytest.mark.django_db
def test_scoped_orders_preserve_tenant_and_custom_store_scope():
    tenant, _, allowed, _ = create_scope("range-scope")
    denied = StoreMaster.objects.create(
        tenant=tenant, platform=allowed.platform, code="range-denied", name="Denied",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    other_tenant, _, other_store, _ = create_scope("range-other-tenant")
    allowed_order = create_order(tenant, allowed, "range-allowed")
    create_order(tenant, denied, "range-denied")
    create_order(other_tenant, other_store, "range-other")
    viewer = user_for(tenant, "range-scoped-viewer")
    grant(viewer, "sales_management.view", DataScope.ScopeType.CUSTOM, {"store_ids": [allowed.pk]})

    orders = _scoped_orders(authenticated_request(viewer, {
        "date_from": "2026-08-17", "date_to": "2026-08-17",
    }), "sales_management.view")

    assert list(orders.values_list("pk", flat=True)) == [allowed_order.pk]
