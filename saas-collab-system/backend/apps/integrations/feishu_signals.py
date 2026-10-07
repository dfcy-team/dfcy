from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.alerts.models import InventoryAlert
from apps.workflows.models import ApprovalRequest, BusinessException
from .models import FeishuOperation, SyncAlertIncident


def _after_commit(tenant_id, callback):
    def safe():
        try:
            callback()
        except Exception:
            FeishuOperation.objects.create(tenant_id=tenant_id, operation_type="notification", status="failed",
                error_code="FEISHU_ENQUEUE_FAILED", masked_detail={"error_message": "通知入队失败，请检查规则、接收人和连接配置。"})
    transaction.on_commit(safe)


@receiver(post_save, sender=ApprovalRequest, dispatch_uid="feishu.approval.outbox")
def approval_changed(sender, instance, raw=False, **kwargs):
    if raw:
        return
    from .feishu_delivery import notify_approval
    _after_commit(instance.tenant_id, lambda: notify_approval(instance.pk))


@receiver(post_save, sender=InventoryAlert, dispatch_uid="feishu.inventory.outbox")
@receiver(post_save, sender=BusinessException, dispatch_uid="feishu.business.outbox")
@receiver(post_save, sender=SyncAlertIncident, dispatch_uid="feishu.sync.outbox")
def warning_changed(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    from .feishu_delivery import emit_notification
    scene = {InventoryAlert: "inventory_alert", BusinessException: "business_alert", SyncAlertIncident: "sync_failed"}[sender]
    _after_commit(instance.tenant_id, lambda: emit_notification(instance.tenant_id, scene, sender._meta.model_name, instance.pk))
