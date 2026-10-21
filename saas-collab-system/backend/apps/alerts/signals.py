from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import InventoryAlertRule
from .inventory_refresh import mark_after_commit


@receiver(post_save, sender=InventoryAlertRule, dispatch_uid='inventory.rule.refresh')
@receiver(post_delete, sender=InventoryAlertRule, dispatch_uid='inventory.rule.deleted.refresh')
def rule_changed(sender, instance, raw=False, **kwargs):
    if not raw:
        mark_after_commit(instance.tenant_id, reason='rules_changed')


def source_changed(sender, instance, raw=False, **kwargs):
    if raw:
        return
    tenant_id = getattr(instance, 'tenant_id', None)
    if tenant_id:
        mark_after_commit(tenant_id, reason='source_changed')


def connect_sources():
    from apps.integrations.models import SyncRun, HistorySyncSegment
    from apps.supply_chain.models import (PurchaseOrder, PurchaseLine, DispatchBatch, DispatchAllocation,
        InternalStockReceipt, InternalStockReceiptLine, OperatingAllocation, SupplierShipment, ShipmentLine,
        InboundOrder, InboundLine, WmsReceiptAllocation)
    from apps.sales_management.operating_models import OperatingOrder, OperatingOrderLine
    from apps.products.models import ProductSKU
    from apps.masterdata.models import StoreMaster, WarehouseMaster
    for model in (PurchaseOrder, PurchaseLine, DispatchBatch, DispatchAllocation, InternalStockReceipt,
                  InternalStockReceiptLine, OperatingAllocation, OperatingOrder, OperatingOrderLine,
                  SupplierShipment, ShipmentLine, InboundOrder, InboundLine, WmsReceiptAllocation,
                  ProductSKU, StoreMaster, WarehouseMaster):
        post_save.connect(source_changed, sender=model, dispatch_uid=f'inventory.source.{model._meta.label_lower}')
        post_delete.connect(source_changed, sender=model,
            dispatch_uid=f'inventory.source.deleted.{model._meta.label_lower}')
    # Run completion is after fact ingestion. History coverage becomes valid
    # only after the segment is finalized; periodic refresh also covers bulk updates.
    post_save.connect(sync_changed, sender=SyncRun, dispatch_uid='inventory.sync.refresh')
    post_save.connect(segment_changed, sender=HistorySyncSegment, dispatch_uid='inventory.coverage.refresh')


def sync_changed(sender, instance, raw=False, **kwargs):
    if not raw and instance.status in ('success', 'partial', 'failed'):
        from apps.integrations.models import SyncJob
        if SyncJob.objects.filter(pk=instance.sync_job_id, resource_type__in=(
                'inventory_snapshot', 'sales_order', 'refund_return', 'inbound')).exists():
            mark_after_commit(instance.tenant_id, reason='source_changed')


def segment_changed(sender, instance, raw=False, **kwargs):
    if not raw:
        mark_after_commit(instance.batch.tenant_id, reason='source_changed')
