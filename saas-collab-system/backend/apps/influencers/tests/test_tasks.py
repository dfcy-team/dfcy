from unittest.mock import Mock, patch

from django.conf import settings

from apps.influencers.tasks import dispatch_daily_affiliate_order_attribution_refreshes_task


def test_order_attribution_refresh_dispatch_runs_daily_without_arguments():
    schedule = settings.CELERY_BEAT_SCHEDULE[
        "dispatch-daily-affiliate-order-attribution-refreshes"
    ]

    assert schedule["task"] == "influencers.dispatch_daily_affiliate_order_attribution_refreshes"
    assert schedule["args"] == ()
    assert schedule["schedule"].minute == {0}
    assert schedule["schedule"].hour == {19}


@patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.delay")
@patch("apps.influencers.tasks.bd_performance_settings")
@patch("apps.influencers.tasks.AffiliateOrderSnapshot.objects")
def test_daily_order_attribution_dispatch_only_queues_tenants_with_order_facts(
    order_objects,
    performance_settings,
    refresh_delay,
):
    tenant_ids = Mock()
    tenant_ids.distinct.return_value = [3, 8]
    order_objects.order_by.return_value.values_list.return_value = tenant_ids
    performance_settings.side_effect = lambda tenant_id: {
        "daily_attribution_reconciliation_enabled": tenant_id == 3,
    }

    result = dispatch_daily_affiliate_order_attribution_refreshes_task()

    assert result == {
        "status": "queued",
        "tenant_count": 1,
        "tenant_ids": [3],
        "skipped_tenant_ids": [8],
    }
    refresh_delay.assert_called_once_with(tenant_id=3)


def test_overdue_sample_fulfillment_task_runs_daily_without_arguments():
    schedule = settings.CELERY_BEAT_SCHEDULE["mark-overdue-sample-fulfillments"]

    assert schedule["task"] == "influencers.mark_overdue_sample_fulfillments"
    assert schedule["args"] == ()
    assert schedule["schedule"].minute == {0}
    assert schedule["schedule"].hour == {18}
