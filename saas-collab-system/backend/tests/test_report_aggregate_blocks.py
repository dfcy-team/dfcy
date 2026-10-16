from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.permissions.models import DataScope
from apps.reports.aggregate_blocks import daily_blocks
from apps.reports.models import ReportAggregateBlock
from tests.test_sales_management import create_scope, grant, user_for


def _request(dataset="sales"):
    tenant, _, _, _ = create_scope(f"aggregate-block-{dataset}")
    user = user_for(tenant, f"aggregate-block-{dataset}-viewer")
    grant(user, "reports.view")
    if dataset == "sales_skus":
        for code in ("sales_management.skus.view", "sales_management.view", "analytics.view"):
            grant(user, code)
    else:
        grant(user, "sales_management.view")
    return SimpleNamespace(user=user)


def _config(dataset="sales", sku_mode=""):
    filters = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
    if sku_mode:
        filters["sku_mode"] = sku_mode
    return {"dataset": dataset, "dimensions": ["date"], "metrics": ["order_count"], "filters": filters}


def _result(marker="fresh"):
    return {
        "rows": [{"date": marker}],
        "dimension_labels": {},
        "cached": False,
        "truncated": False,
        "computed_at": datetime(2026, 1, 31, tzinfo=UTC),
        "refreshed_at": datetime(2026, 1, 31, tzinfo=UTC),
    }


@pytest.mark.django_db
def test_daily_block_persists_and_reuses_unexpired_result():
    request = _request()
    with patch("apps.reports.aggregate_blocks.query_dataset", return_value=_result()) as query:
        first = daily_blocks(request, _config())
        second = daily_blocks(request, _config())

    assert query.call_count == 1
    assert ReportAggregateBlock.objects.filter(requested_by=request.user).count() == 1
    assert first["rows"] == second["rows"] == [{"date": "fresh"}]
    assert first["cached"] is False
    assert second["cached"] is True


@pytest.mark.django_db
def test_expired_block_is_refreshed():
    request = _request()
    with patch("apps.reports.aggregate_blocks.query_dataset", side_effect=[_result("first"), _result("second")]) as query:
        first = daily_blocks(request, _config())
        ReportAggregateBlock.objects.filter(requested_by=request.user).update(expires_at=timezone.now() - timedelta(seconds=1))
        second = daily_blocks(request, _config())

    assert query.call_count == 2
    assert first["rows"] == [{"date": "first"}]
    assert second["rows"] == [{"date": "second"}]
    assert ReportAggregateBlock.objects.filter(requested_by=request.user, expires_at__gt=timezone.now()).count() == 1


@pytest.mark.django_db
def test_scope_fingerprint_change_uses_separate_persistent_block():
    request = _request()
    with patch("apps.reports.aggregate_blocks.query_dataset", side_effect=[_result("all"), _result("scoped")]) as query:
        daily_blocks(request, _config())
        scope = request.user.user_roles.filter(role__permissions__code="sales_management.view").first().role.data_scopes.first()
        scope.scope_type = DataScope.ScopeType.CUSTOM
        scope.config = {"store_ids": [12345]}
        scope.save(update_fields=["scope_type", "config"])
        result = daily_blocks(request, _config())

    assert query.call_count == 2
    assert result["rows"] == [{"date": "scoped"}]
    assert ReportAggregateBlock.objects.filter(requested_by=request.user).count() == 2


@pytest.mark.django_db
def test_permission_scope_change_during_compute_denies_and_does_not_cache():
    request = _request()

    def compute_and_change_scope(*args, **kwargs):
        scope = request.user.user_roles.filter(role__permissions__code="sales_management.view").first().role.data_scopes.first()
        scope.scope_type = DataScope.ScopeType.CUSTOM
        scope.config = {"store_ids": [12345]}
        scope.save(update_fields=["scope_type", "config"])
        return _result()

    with patch("apps.reports.aggregate_blocks.query_dataset", side_effect=compute_and_change_scope):
        with pytest.raises(PermissionDenied):
            daily_blocks(request, _config())

    assert ReportAggregateBlock.objects.filter(requested_by=request.user).count() == 0


@pytest.mark.django_db
def test_related_sku_mode_skips_persistent_block_cache():
    request = _request("sales_skus")
    with patch("apps.reports.aggregate_blocks.query_dataset", side_effect=[_result("first"), _result("second")]) as query:
        first = daily_blocks(request, _config("sales_skus", "related"))
        second = daily_blocks(request, _config("sales_skus", "related"))

    assert query.call_count == 2
    assert first["rows"] == [{"date": "first"}]
    assert second["rows"] == [{"date": "second"}]
    assert ReportAggregateBlock.objects.filter(requested_by=request.user).count() == 0
