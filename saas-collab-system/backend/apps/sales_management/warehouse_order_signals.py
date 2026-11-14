import logging
from types import SimpleNamespace
from .warehouse_order_policy import fingerprint

from django.conf import settings
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from apps.commerce.models import SalesOrder


@receiver(pre_save, sender=SalesOrder)
def remember_order_status(sender, instance, raw=False, update_fields=None, **kwargs):
    instance._warehouse_status_changed = False
    if raw or not getattr(settings, 'SALES_ORDER_WAREHOUSE_SYNC_ENABLED', False):
        return
    fields = {'raw_status', 'normalized_status', 'paid_at_utc', 'source_details', 'store_id'}
    if update_fields is not None and not fields.intersection(update_fields):
        return
    previous = sender.objects.filter(pk=instance.pk).values(*fields).first() if instance.pk else None
    if previous is None:
        instance._warehouse_status_changed = True
    else:
        current = {field: getattr(instance, field) if update_fields is None or field in update_fields else value for field, value in previous.items()}
        instance._warehouse_status_changed = fingerprint(SimpleNamespace(**previous)) != fingerprint(SimpleNamespace(**current))



@receiver(post_save, sender=SalesOrder)
def queue_order_warehouse_lookup(sender, instance, raw=False, **kwargs):
    if raw or not getattr(instance, '_warehouse_status_changed', False):
        return
    from .warehouse_orders import request_lookup
    try:
        # A savepoint keeps enrichment failures from breaking the order transaction.
        with transaction.atomic():
            request_lookup(instance.pk)
    except Exception:
        logging.getLogger(__name__).error(
            'Warehouse lookup registration failed for order %s; manual retry required.', instance.pk)
