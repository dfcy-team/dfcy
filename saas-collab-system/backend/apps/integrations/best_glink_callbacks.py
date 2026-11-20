"""Signed BEST push inbox. Acknowledgement follows durable storage, not accounting."""
import hashlib
import hmac
import json
import re

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST
from rest_framework.exceptions import PermissionDenied, ValidationError

from .best_glink import check_identity, parse_data
from .best_glink_contract import CALLBACKS, validate_fields
from .custody import get_custody_backend
from .models import PlatformIntegrationConfig, WarehouseAuthorization, WebhookEvent
from .raw_services import archive_webhook_payload


def reply(success, status=200):
    return JsonResponse({"success": success, "code": "SUCCESS" if success else "REJECTED"}, status=status)


def safe_business(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if re.search(r"secret|password|token|cookie|authorization|partnerkey|^sign$", key, re.I):
                raise ValidationError("回调不能携带凭据。")
            if key != "partnerId":
                result[key] = safe_business(item)
        return result
    if isinstance(value, list):
        return [safe_business(item) for item in value]
    return value


@csrf_exempt
@require_POST
@sensitive_post_parameters("sign", "bizData")
@sensitive_variables()
def receive(request, config_id):
    if not getattr(settings, "BEST_GLINK_CALLBACKS_ENABLED", False):
        return reply(False, 404)
    if len(request.body) > 1024 * 1024:
        return reply(False, 413)
    config = PlatformIntegrationConfig.objects.filter(pk=config_id, platform="best_ecapi",
        contract_version="glink", status__in=("verified", "active"), credential_status="configured").first()
    if not config or not config.credential_id:
        return reply(False, 404)
    if request.content_type != "application/x-www-form-urlencoded":
        return reply(False, 415)
    if any(len(request.POST.getlist(key)) != 1 for key in ("partnerId", "serviceType", "bizData", "sign")):
        return reply(False, 400)
    partner, operation, raw, sign = (request.POST.get(key, "") for key in ("partnerId", "serviceType", "bizData", "sign"))
    if operation not in CALLBACKS or partner != config.platform_config.get("partner_id"):
        return reply(False, 403)
    try:
        key = get_custody_backend().retrieve_secret(config.credential_id)
    except Exception:
        return reply(False, 503)
    expected = hashlib.md5((raw + key).encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{32}", sign) or not hmac.compare_digest(expected, sign):
        return reply(False, 401)
    try:
        data = parse_data(raw)
        validate_fields(operation, data, callback=True)
        if data.get("partnerId") != partner:
            return reply(False, 403)
        customer_field = "ownerCode" if operation == "GLINK_WORK_ORDER_FEED_BACK" else "customerCode"
        if data.get(customer_field) != config.platform_config.get("customer_code"):
            return reply(False, 403)
        business = safe_business(data)
    except (ValidationError, ValueError, TypeError):
        return reply(False, 400)
    with transaction.atomic():
        locked = PlatformIntegrationConfig.objects.select_for_update().get(pk=config.pk)
        if (locked.config_version != config.config_version or locked.credential_id != config.credential_id
                or locked.status not in ("verified", "active") or locked.platform_config != config.platform_config
                or locked.credential_status != "configured" or locked.contract_version != "glink"
                or locked.platform != "best_ecapi"):
            return reply(False, 409)
        bindings = WarehouseAuthorization.objects.filter(tenant_id=config.tenant_id,
            integration_config=config, provider="best_ecapi", status="active", validation_status="verified",
            warehouse__status="active", warehouse__tenant_id=config.tenant_id).select_related("warehouse")
        if data.get("warehouseCode"):
            bindings = bindings.filter(external_warehouse_code=data["warehouseCode"])
        candidates = list(bindings[:2])
        if len(candidates) != 1:
            return reply(False, 403)
        binding = candidates[0]
        try:
            check_identity({**data, "customerCode": config.platform_config["customer_code"],
                "warehouseCode": binding.external_warehouse_code}, binding)
        except PermissionDenied:
            return reply(False, 403)
        # Stable content digest rejects replay while retaining separate configuration identities.
        digest = hashlib.sha256((str(config.pk) + "\n" + operation + "\n" + json.dumps(business, sort_keys=True, ensure_ascii=False, separators=(",", ":"))).encode("utf-8")).hexdigest()
        event, created = WebhookEvent.objects.get_or_create(tenant_id=config.tenant_id,
            platform="best_ecapi", event_id=digest, defaults={"event_type": f"best:{binding.pk}:{operation}",
                "signature_status": "valid", "processing_status": "received",
                "payload_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest()})
        if created:
            archive_webhook_payload(event, {"integration_config_id": config.pk,
                "warehouse_authorization_id": binding.pk, "warehouse_id": binding.warehouse_id,
                "serviceType": operation, "bizData": business})
    return reply(True)
