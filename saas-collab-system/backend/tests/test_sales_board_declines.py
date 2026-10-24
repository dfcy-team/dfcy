from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.permissions.models import DataScope, Role
from apps.sales_management.board_declines import _params
from tests.test_sales_realtime_board import DAY, _fixture, _grant, _order


URL = "/api/internal/commerce/board-declines/"


def test_params_rejects_dates_that_would_overflow_bounded_query_window():
    request = Request(APIRequestFactory().get(URL, {
        "date_from": "9999-12-31", "date_to": "9999-12-31", "currency": "PHP",
    }))
    with pytest.raises(ValidationError):
        _params(request)


def _set_day(order, day):
    order.created_at_utc = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    order.save(update_fields=["created_at_utc"])


@pytest.mark.django_db
def test_declines_requires_both_permissions_and_explicit_currency():
    user, tenant, platform, store, run, client = _fixture("board-declines-permission")
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "currency": "PHP"}).status_code == 403
    _grant(user, "sales_management.skus.view")
    assert client.get(URL, {"date_from": DAY, "date_to": DAY}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "currency": "PHP", "metric": "volume"}).status_code == 400
    today = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE))
    _order(tenant, platform, store, run, "today")
    today_order = SalesOrder.objects.get(external_order_id="today")
    _set_day(today_order, today)
    assert client.get(URL, {
        "date_from": today.isoformat(), "date_to": today.isoformat(), "currency": "PHP",
    }).status_code == 400


@pytest.mark.django_db
def test_sql_aggregates_full_product_set_before_top_ten_and_excludes_missing_baseline():
    user, tenant, platform, store, run, client = _fixture("board-declines-ranking")
    _grant(user, "sales_management.skus.view")
    day = datetime.fromisoformat(DAY).date()
    previous_day = day - timedelta(days=1)
    _order(tenant, platform, store, run, "stable-prev", amount="10000")
    stable_prev = SalesOrder.objects.get(external_order_id="stable-prev")
    _set_day(stable_prev, previous_day)
    _order(tenant, platform, store, run, "stable-current", amount="10000")
    stable_current = SalesOrder.objects.get(external_order_id="stable-current")
    _set_day(stable_current, day)
    SalesOrderItem.objects.filter(sales_order__in=[stable_prev, stable_current]).update(platform_product_id="stable")

    for index in range(11):
        product_id = f"decline-{index:02}"
        _order(tenant, platform, store, run, f"prev-{index}", amount=str(100 + index))
        previous = SalesOrder.objects.get(external_order_id=f"prev-{index}")
        _set_day(previous, previous_day)
        _order(tenant, platform, store, run, f"current-{index}", amount="1")
        current = SalesOrder.objects.get(external_order_id=f"current-{index}")
        _set_day(current, day)
        SalesOrderItem.objects.filter(sales_order__in=[previous, current]).update(platform_product_id=product_id)

    _order(tenant, platform, store, run, "no-baseline", amount="1")
    current_only = SalesOrder.objects.get(external_order_id="no-baseline")
    _set_day(current_only, day)
    SalesOrderItem.objects.filter(sales_order=current_only).update(platform_product_id="current-only")
    _order(tenant, platform, store, run, "previous-only", amount="100")
    previous_only = SalesOrder.objects.get(external_order_id="previous-only")
    _set_day(previous_only, previous_day)
    SalesOrderItem.objects.filter(sales_order=previous_only).update(platform_product_id="previous-only")
    _order(tenant, platform, store, run, "zero-prev", amount="0")
    zero_previous = SalesOrder.objects.get(external_order_id="zero-prev")
    _set_day(zero_previous, previous_day)
    _order(tenant, platform, store, run, "zero-current", amount="0")
    zero_current = SalesOrder.objects.get(external_order_id="zero-current")
    _set_day(zero_current, day)
    SalesOrderItem.objects.filter(sales_order__in=[zero_previous, zero_current]).update(platform_product_id="zero-base")
    _order(tenant, platform, store, run, "cancelled-prev", amount="100", status="cancelled")
    cancelled_previous = SalesOrder.objects.get(external_order_id="cancelled-prev")
    _set_day(cancelled_previous, previous_day)
    _order(tenant, platform, store, run, "cancelled-current", amount="1")
    cancelled_current = SalesOrder.objects.get(external_order_id="cancelled-current")
    _set_day(cancelled_current, day)
    SalesOrderItem.objects.filter(sales_order__in=[cancelled_previous, cancelled_current]).update(platform_product_id="cancelled-base")

    response = client.get(URL, {
        "date_from": DAY, "date_to": DAY, "currency": "PHP", "metric": "amount",
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["rows"]) == 10
    assert data["rows"][0]["product_id"] == "decline-10"
    assert data["rows"][0]["decline_amount"] == "109"
    assert "stable" not in [row["product_id"] for row in data["rows"]]
    assert "current-only" not in [row["product_id"] for row in data["rows"]]
    assert "previous-only" not in [row["product_id"] for row in data["rows"]]
    assert "zero-base" not in [row["product_id"] for row in data["rows"]]
    assert "cancelled-base" not in [row["product_id"] for row in data["rows"]]
    assert data["filters"]["previous_from"] == previous_day.isoformat()
    assert all(row["currency"] == "PHP" for row in data["rows"])


@pytest.mark.django_db
def test_percent_metric_uses_ratio_order_and_tenant_isolation():
    user, tenant, platform, store, run, client = _fixture("board-declines-percent")
    _grant(user, "sales_management.skus.view")
    day = datetime.fromisoformat(DAY).date()
    prev_day = day - timedelta(days=1)
    for suffix, previous_amount, current_amount in (("third", "3", "2"), ("hundredth", "100", "67")):
        _order(tenant, platform, store, run, f"{suffix}-prev", amount=previous_amount)
        previous = SalesOrder.objects.get(external_order_id=f"{suffix}-prev")
        _set_day(previous, prev_day)
        _order(tenant, platform, store, run, f"{suffix}-current", amount=current_amount)
        current = SalesOrder.objects.get(external_order_id=f"{suffix}-current")
        _set_day(current, day)
        SalesOrderItem.objects.filter(sales_order__in=[previous, current]).update(platform_product_id=suffix)

    _, other_tenant, other_platform, other_store, other_run, _ = _fixture("board-declines-foreign")
    _order(other_tenant, other_platform, other_store, other_run, "foreign-prev", amount="999999")
    foreign_previous = SalesOrder.objects.get(external_order_id="foreign-prev")
    _set_day(foreign_previous, prev_day)
    _order(other_tenant, other_platform, other_store, other_run, "foreign-current", amount="1")
    foreign_current = SalesOrder.objects.get(external_order_id="foreign-current")
    _set_day(foreign_current, day)
    SalesOrderItem.objects.filter(sales_order__in=[foreign_previous, foreign_current]).update(platform_product_id="tenant-sentinel")

    response = client.get(URL, {
        "date_from": DAY, "date_to": DAY, "currency": "PHP", "metric": "percent",
    })
    assert response.status_code == 200
    rows = response.json()["data"]["rows"]
    assert [row["product_id"] for row in rows] == ["third", "hundredth"]
    assert "tenant-sentinel" not in str(rows)


@pytest.mark.django_db
def test_custom_scope_intersection_is_applied_before_product_aggregation():
    user, tenant, platform, store, run, client = _fixture("board-declines-scope-intersection")
    sales_role = Role.objects.get(user_roles__user=user, permissions__code="sales_management.view")
    sales_role.data_scopes.update(scope_type=DataScope.ScopeType.CUSTOM, config={"store_ids": [str(store.id)]})
    other_store = type(store).objects.create(
        tenant=tenant, platform=platform, code="scope-other", name="Other store", country_code="PH",
        currency="PHP", timezone="Asia/Manila",
    )
    _grant(user, "sales_management.skus.view", {"store_ids": [str(other_store.id)]})
    day = datetime.fromisoformat(DAY).date()
    for suffix, target_store in (("own", store), ("other", other_store)):
        _order(tenant, platform, target_store, run, f"{suffix}-prev", amount="100")
        previous = SalesOrder.objects.get(external_order_id=f"{suffix}-prev")
        _set_day(previous, day - timedelta(days=1))
        _order(tenant, platform, target_store, run, f"{suffix}-current", amount="50")
        current = SalesOrder.objects.get(external_order_id=f"{suffix}-current")
        _set_day(current, day)
        SalesOrderItem.objects.filter(sales_order__in=[previous, current]).update(platform_product_id=suffix)
    response = client.get(URL, {"date_from": DAY, "date_to": DAY, "currency": "PHP"})
    assert response.status_code == 200
    assert response.json()["data"]["rows"] == []


@pytest.mark.django_db
def test_store_timezone_blocks_incomplete_local_day(monkeypatch):
    user, tenant, platform, store, run, client = _fixture("board-declines-local-time")
    _grant(user, "sales_management.skus.view")
    store.timezone = "America/Los_Angeles"
    store.save(update_fields=["timezone"])
    monkeypatch.setattr(
        "apps.sales_management.board_declines.timezone.now",
        lambda: datetime(2026, 10, 22, 17, tzinfo=UTC),
    )
    _order(tenant, platform, store, run, "la-current", amount="50")
    la_current = SalesOrder.objects.get(external_order_id="la-current")
    la_current.created_at_utc = datetime(2026, 10, 22, 17, tzinfo=UTC)
    la_current.save(update_fields=["created_at_utc"])
    blocked = client.get(URL, {
        "date_from": "2026-10-22", "date_to": "2026-10-22", "currency": "PHP",
    })
    assert blocked.status_code == 400
    assert client.get(URL, {
        "date_from": "2026-10-21", "date_to": "2026-10-21", "currency": "PHP",
    }).status_code == 200


@pytest.mark.django_db
def test_yesterday_diagnosis_requires_strictly_more_than_thirty_percent(monkeypatch):
    user, tenant, platform, store, run, client = _fixture("board-declines-diagnosis-boundary")
    _grant(user, "sales_management.skus.view")
    monkeypatch.setattr(
        "apps.sales_management.board_declines.timezone.now",
        lambda: datetime(2026, 10, 23, 17, tzinfo=UTC),
    )
    day, previous_day = date(2026, 10, 23), date(2026, 10, 22)
    for suffix, amount in (("exact", "70"), ("over", "69")):
        _order(tenant, platform, store, run, f"{suffix}-prev", amount="100")
        previous = SalesOrder.objects.get(external_order_id=f"{suffix}-prev")
        _set_day(previous, previous_day)
        _order(tenant, platform, store, run, f"{suffix}-current", amount=amount)
        current = SalesOrder.objects.get(external_order_id=f"{suffix}-current")
        _set_day(current, day)
        SalesOrderItem.objects.filter(sales_order__in=[previous, current]).update(platform_product_id=suffix)
    rows = client.get(URL, {
        "date_from": day.isoformat(), "date_to": day.isoformat(), "currency": "PHP",
    }).json()["data"]["rows"]
    by_product = {row["product_id"]: row for row in rows}
    assert by_product["exact"]["diagnosis"] is None
    assert by_product["over"]["diagnosis"]["status"] == "suspected_decline"
