"""Authenticated, deduplicated Feishu events. Never executes business writes."""
import base64
import hashlib
import hmac
import json
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.tenants.models import Tenant
from .custody import get_custody_backend
from .models import FeishuConnection, FeishuOperation

EVENT_TYPES = {"im.message.receive_v1", "im.chat.access_event.bot_p2p_chat_entered_v1"}


@csrf_exempt
@require_POST
def event_callback(request, tenant_id):
    connection = FeishuConnection.objects.filter(tenant_id=tenant_id, enabled=True).first()
    if not connection or not connection.verification_token_ref:
        return JsonResponse({"code": "FEISHU_CALLBACK_UNCONFIGURED"}, status=404)
    try:
        raw = request.body
        if len(raw) > 262144:
            raise ValueError("size")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload")
        custody = get_custody_backend()
        token = custody.retrieve_secret(connection.verification_token_ref)
        encrypt_key = custody.retrieve_secret(connection.encrypt_key_ref) if connection.encrypt_key_ref else ""
        if payload.get("encrypt"):
            if not encrypt_key:
                raise ValueError("encrypt key")
            encrypted = base64.b64decode(payload["encrypt"], validate=True)
            decryptor = Cipher(algorithms.AES(hashlib.sha256(encrypt_key.encode()).digest()), modes.CBC(encrypted[:16])).decryptor()
            padded = decryptor.update(encrypted[16:]) + decryptor.finalize()
            unpad = PKCS7(128).unpadder()
            payload = json.loads(unpad.update(padded) + unpad.finalize())
        header = payload.get("header") or {}
        incoming = header.get("token") if payload.get("schema") == "2.0" else payload.get("token")
        if not token or not isinstance(incoming, str) or not hmac.compare_digest(token, incoming):
            raise ValueError("token")
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge")
            if not isinstance(challenge, str) or len(challenge) > 200:
                raise ValueError("challenge")
            return JsonResponse({"challenge": challenge})
        if encrypt_key:
            stamp, nonce = request.headers.get("X-Lark-Request-Timestamp", ""), request.headers.get("X-Lark-Request-Nonce", "")
            if abs(time.time() - int(stamp)) > 300 or not nonce or len(nonce) > 200:
                raise ValueError("expired")
            signature = hashlib.sha256((stamp + nonce + encrypt_key).encode() + raw).hexdigest()
            if not hmac.compare_digest(signature, request.headers.get("X-Lark-Signature", "")):
                raise ValueError("signature")
        if payload.get("schema") != "2.0" or header.get("app_id") != connection.app_id:
            raise ValueError("app")
        event_id, event_type = header.get("event_id"), header.get("event_type")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 120 or not isinstance(event_type, str):
            raise ValueError("event")
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=tenant_id)
            existing = FeishuOperation.objects.filter(tenant_id=tenant_id, operation_type="event", reference_type="feishu_event", reference_id=event_id).first()
            if existing:
                return JsonResponse({"code": 0, "duplicate": True})
            FeishuOperation.objects.create(tenant_id=tenant_id, operation_type="event", reference_type="feishu_event", reference_id=event_id,
                status="success" if event_type in EVENT_TYPES else "skipped",
                masked_detail={"event_type": event_type[:120], "payload_hash": hashlib.sha256(raw).hexdigest(), "business_write": False},
                error_code="" if event_type in EVENT_TYPES else "FEISHU_EVENT_UNSUPPORTED")
        return JsonResponse({"code": 0})
    except Exception:
        # Never include credentials, raw content or decrypted personal data.
        return JsonResponse({"code": "FEISHU_CALLBACK_REJECTED"}, status=403)
