from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log

from .models import ConnectionCapability, MarketplaceStoreAuthorization, SyncJob


RESOURCE_CAPABILITY = {
    SyncJob.ResourceType.SALES_ORDER: ConnectionCapability.CapabilityCode.ORDER,
    SyncJob.ResourceType.REFUND_RETURN: ConnectionCapability.CapabilityCode.RETURN_REFUND,
    SyncJob.ResourceType.INVENTORY_SNAPSHOT: ConnectionCapability.CapabilityCode.INVENTORY,
    SyncJob.ResourceType.INBOUND: ConnectionCapability.CapabilityCode.WAREHOUSE,
    SyncJob.ResourceType.SHIPMENT: ConnectionCapability.CapabilityCode.FULFILLMENT,
    SyncJob.ResourceType.SETTLEMENT_BILL: ConnectionCapability.CapabilityCode.SETTLEMENT,
    SyncJob.ResourceType.WITHDRAWAL: ConnectionCapability.CapabilityCode.PAYMENT,
}


def _eligible_source_queryset(sync_job, capability_code, *, lock=False):
    authorization = sync_job.store_authorization
    queryset = ConnectionCapability.objects.filter(
        authorization__tenant_id=sync_job.tenant_id,
        authorization__store_id=authorization.store_id,
        authorization__status=MarketplaceStoreAuthorization.Status.ACTIVE,
        capability_code=capability_code,
        read_enabled=True,
        write_enabled=False,
        status=ConnectionCapability.Status.ACTIVE,
    ).select_related("authorization").order_by("source_priority", "authorization_id", "id")
    return queryset.select_for_update() if lock else queryset


def require_sync_read_capability(sync_job, execution_mode, *, lock=False):
    if execution_mode != "live_readonly" or sync_job.resource_type == SyncJob.ResourceType.MOCK_RECORD:
        return None
    if not sync_job.store_authorization_id:
        return None
    code = RESOURCE_CAPABILITY.get(sync_job.resource_type)
    if not code:
        raise ValidationError(f"CAPABILITY_NOT_ENABLED: {sync_job.resource_type}")
    authorization = sync_job.store_authorization
    if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
        raise ValidationError(f"CAPABILITY_NOT_ENABLED: {code}")
    candidates = _eligible_source_queryset(sync_job, code, lock=lock)
    capability = candidates.first()
    if capability is None:
        raise ValidationError(f"CAPABILITY_NOT_ENABLED: {code}")
    if capability.authorization_id != authorization.id:
        raise ValidationError(f"CAPABILITY_SOURCE_NOT_SELECTED: {code}")
    return capability


def sync_source_health(sync_job):
    if not sync_job.store_authorization_id or sync_job.resource_type == SyncJob.ResourceType.MOCK_RECORD:
        return {"state": "not_required", "capability_code": "", "source_priority": None}
    code = RESOURCE_CAPABILITY.get(sync_job.resource_type)
    if not code:
        return {"state": "unsupported", "capability_code": "", "source_priority": None}
    authorization = sync_job.store_authorization
    if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
        return {"state": "authorization", "capability_code": code, "source_priority": None}
    selected = _eligible_source_queryset(sync_job, code).first()
    if selected is None:
        return {"state": "capability_missing", "capability_code": code, "source_priority": None}
    if selected.authorization_id != authorization.id:
        return {
            "state": "source_not_selected", "capability_code": code,
            "source_priority": selected.source_priority,
            "selected_authorization_id": selected.authorization_id,
        }
    return {
        "state": "ready", "capability_code": code,
        "source_priority": selected.source_priority,
        "selected_authorization_id": selected.authorization_id,
    }


def record_sync_source_decision(sync_job, sync_run, capability):
    if capability is None:
        return None
    candidates = list(
        _eligible_source_queryset(sync_job, capability.capability_code).values(
            "id", "authorization_id", "source_priority"
        )
    )
    decision = {
        "sync_job_id": sync_job.id,
        "sync_run_id": sync_run.id,
        "store_id": capability.authorization.store_id,
        "authorization_id": capability.authorization_id,
        "capability_id": capability.id,
        "capability_code": capability.capability_code,
        "source_priority": capability.source_priority,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selection_rule": "lowest_source_priority_then_authorization_id",
        "write_enabled": False,
    }
    return write_operation_log(
        tenant=sync_job.tenant,
        module="integrations",
        action="sync_source_selected",
        object_type="sync_run",
        object_id=sync_run.run_id,
        after_data=decision,
    )
