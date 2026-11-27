from datetime import datetime, timezone
from unittest.mock import patch

from django.db.models import Q

from apps.sales_management.order_presentation import attach_event_milestones


def test_event_lookup_pairs_platform_and_shop_with_page_orders():
    timestamp = datetime(2026, 11, 26, tzinfo=timezone.utc)
    first = {'store': {'id': 1}, 'platform': 'shopee', 'external_order_id': 'first'}
    second = {'store': {'id': 2}, 'platform': 'tiktok', 'external_order_id': 'second'}
    with patch('apps.integrations.models.MarketplaceStoreAuthorization.objects.filter') as stores, \
         patch('apps.integrations.models.WebhookEvent.objects.filter') as events:
        stores.return_value.values_list.return_value = [
            (1, 'shopee', 'PH', 'shop-a'), (2, 'tiktok', 'PH', 'shop-b'),
        ]
        events.return_value.values.return_value.annotate.return_value = [{
            'platform': 'shopee', 'external_shop_id': 'shop-a', 'external_order_id': 'first',
            'completed_at_utc': timestamp, 'cancelled_at_utc': None, 'cancel_requested_at_utc': None,
        }]
        attach_event_milestones(9, [first, second])
    events.assert_called_once_with(
        Q(platform='shopee', external_shop_id='shop-a', external_order_id__in={'first'})
        | Q(platform='tiktok', external_shop_id='shop-b', external_order_id__in={'second'}),
        tenant_id=9, signature_status='valid',
    )
    assert first['completed_at_utc'] == timestamp.isoformat()
    assert first['time_sources']['completed_at_utc'] == 'verified_platform_push'
    assert 'completed_at_utc' not in second
