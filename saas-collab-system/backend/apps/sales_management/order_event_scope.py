"""Platform-specific identities and evidenced order-level milestones."""
from django.db.models import Q


def shop_identity(platform, region, shop_id):
    return f'lazada_{region.lower()}:{shop_id}' if platform == 'lazada' else shop_id


def milestone_filters():
    # Lazada messages describe individual trade/reverse lines, not whole orders.
    return {
        'completed_at': Q(platform='shopee', order_status='COMPLETED', completed_scenario='NORMAL')
                        | Q(platform='tiktok', event_type='tiktok.order_status', order_status='COMPLETED'),
        'cancel_requested_at': Q(platform='shopee', order_status='IN_CANCEL'),
        'cancelled_at': Q(platform='shopee', order_status='CANCELLED')
                        | Q(platform='tiktok', event_type='tiktok.order_status', order_status='CANCEL'),
    }
