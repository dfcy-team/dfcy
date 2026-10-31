from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsMarketplaceStoreAuthorizer, IsMarketplaceStoreViewer
from apps.permissions.services import user_has_integration_permission
from .ads_subject import mapping_allowed
from .ads_sync import bound_evidence, lock_runtime_approval, validate_mapping
from .models import IntegrationAuditLog, TikTokAdsAdvertiserMapping


def capability_row(mapping, user):
    reason, state, can_enable = "", "unverified", False
    advertiser_name = ""
    try:
        session = bound_evidence(mapping)
        advertiser_name = next((c.get("name", "") for c in session.candidates
            if isinstance(c, dict) and c.get("advertiser_id") == mapping.advertiser_id
            and isinstance(c.get("name"), str)), "")[:200]
        state = "verified"
    except Exception:
        reason = "Ads mapping lacks current verified bound OAuth metadata."
    try:
        validate_mapping(mapping, require_enabled=False)
        can_enable = (user_has_integration_permission(user, "integrations.store.authorize")
                      and mapping_allowed(user, mapping, "integrations.store.authorize"))
    except Exception:
        reason = reason or "Ads read-only configuration is not ready."
    job = mapping.sync_jobs.filter(tenant_id=mapping.tenant_id, resource_type="advertising_report").first()
    latest = job.runs.filter(status="success").order_by("-finished_at").first() if job else None
    return {"mapping_id": mapping.pk, "advertiser_id": mapping.advertiser_id,
        "advertiser_name": advertiser_name,
        "store_id": mapping.store_id, "store_code": mapping.store.code, "store_name": mapping.store.name,
        "integration_config_id": mapping.integration_config_id, "config_name": mapping.integration_config.account_alias,
        "currency": mapping.currency, "timezone": mapping.timezone, "read_enabled": mapping.enabled,
        "write_enabled": False, "can_enable_read": can_enable, "verification_state": state,
        "blocked_reason": reason or ("Ads read capability is disabled." if not mapping.enabled else ""),
        "existing_job_id": job.pk if job else None, "last_success_at": latest.finished_at if latest else None,
        "job_enabled": job.is_enabled if job else False, "report_scope": "AUCTION_CAMPAIGN"}


def visible_mappings(user):
    return [m for m in TikTokAdsAdvertiserMapping.objects.filter(tenant_id=user.tenant_id).select_related(
        "store__platform", "integration_config", "tenant").order_by("store_id", "id")
        if mapping_allowed(user, m, "integrations.store.view")]


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreViewer])
def capabilities(request):
    if request.query_params:
        raise ValidationError("Ads capabilities do not accept scope overrides.")
    return success_response({"items": [capability_row(m, request.user) for m in visible_mappings(request.user)]})


@api_view(["PUT"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def capability(request, pk):
    if (not isinstance(request.data, dict) or set(request.data) != {"read_enabled"}
            or type(request.data["read_enabled"]) is not bool):
        raise ValidationError("Expected only read_enabled: boolean.")
    with transaction.atomic():
        mapping = get_object_or_404(TikTokAdsAdvertiserMapping.objects.select_for_update().select_related(
            "store__platform", "integration_config", "tenant"), pk=pk, tenant_id=request.user.tenant_id)
        if not mapping_allowed(request.user, mapping, "integrations.store.authorize"):
            raise PermissionDenied("Ads mapping is outside the authorized store scope.")
        enabled = request.data["read_enabled"]
        if enabled:
            lock_runtime_approval()
            validate_mapping(mapping, require_enabled=False, lock=True)
        # A safety stop must remain possible even after config readiness is lost.
        TikTokAdsAdvertiserMapping.objects.filter(pk=mapping.pk).update(enabled=enabled)
        from django.utils import timezone
        TikTokAdsAdvertiserMapping.objects.filter(pk=mapping.pk).update(updated_at=timezone.now())
        IntegrationAuditLog.objects.create(tenant_id=mapping.tenant_id, integration_config_id=mapping.integration_config_id,
            actor=request.user, action="ads_read_capability", result="success",
            masked_detail={"mapping_id": mapping.pk, "store_id": mapping.store_id, "read_enabled": enabled})
        mapping.refresh_from_db()
    return success_response(capability_row(mapping, request.user))
