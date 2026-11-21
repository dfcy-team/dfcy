"""The old cloud warning interface and V518 page filter share one selector."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.conf import settings

from apps.sales_management import inventory_batches as batches

NOW = datetime(2026, 11, 21, 1, tzinfo=timezone.utc)


def test_cloud_default_keeps_complete_batches_without_environment_override():
    # The deployment flag is observed absent in the real cloud; this test checks
    # the resulting candidate default and does not edit any environment file.
    assert settings.INVENTORY_COMPLETE_BATCH_READS_ENABLED is True


def test_cloud_id_interface_delegates_to_same_time_bound_selector():
    qs = Mock()
    qs.values_list.return_value = [17, 18]
    with patch.object(batches, "_latest_complete_inventory_runs", return_value=qs) as selector:
        assert batches.latest_complete_inventory_runs(3, "PH", as_of=NOW) == [17, 18]
    selector.assert_called_once_with(3, country_code="PH", as_of=NOW)
    qs.values_list.assert_called_once_with("pk", flat=True)


def test_published_filter_keeps_run_and_warehouse_paired():
    qs = Mock()
    qs.values_list.return_value = [(17, 31), (18, 32)]
    with patch.object(batches, "_latest_complete_inventory_runs", return_value=qs):
        scope = batches.published_inventory_filter(3, country_code="PH", as_of=NOW)
    pairs = []
    for child in scope.children:
        if hasattr(child, "children"):
            values = dict(child.children)
            if "source_run_id" in values:
                pairs.append(values)
    assert pairs == [{"source_run_id": 17, "warehouse_id": 31}, {"source_run_id": 18, "warehouse_id": 32}]


def test_selector_requires_tenant_ownership_finished_run_and_complete_cursor():
    qs = Mock()
    qs.filter.return_value = qs
    qs.annotate.return_value = qs
    qs.order_by.return_value = qs
    with patch.object(batches.SyncRun.objects, "filter", return_value=qs) as query:
        batches._latest_complete_inventory_runs(3, country_code="PH", as_of=NOW)
    filters = query.call_args.kwargs
    for key in ("tenant_id", "sync_job__tenant_id", "sync_job__integration_config__tenant_id", "sync_job__warehouse_authorization__tenant_id", "sync_job__warehouse_authorization__warehouse__tenant_id"):
        assert filters[key] == 3
    assert filters["finished_at__isnull"] is False
    for name in ("started_from_initial_cursor", "ended_without_cursor", "all_records_valid"):
        assert filters["masked_log__decision_source__" + name] is True
    qs.filter.assert_any_call(finished_at__lte=NOW)
    qs.filter.assert_any_call(sync_job__warehouse_authorization__warehouse__country_code__iexact="PH")
    qs.filter.assert_any_call(warehouse_rank=1)
