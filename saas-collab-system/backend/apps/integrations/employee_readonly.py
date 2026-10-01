"""Independent, fail-closed employee delegation. No business JWT or refresh."""
import base64
import hashlib
import json
import logging
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode, urlsplit
from cryptography.fernet import Fernet, InvalidToken

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.credential_auth import credential_lease_active
from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.common.responses import success_response as _success_response
from apps.permissions.lifecycle import effective_permissions
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.services import check_user_permission, get_field_permission_map, get_permission_data_scopes
from apps.permissions.ui_p2_scopes import filter_master_data
from apps.permissions.ui_p5_scopes import filter_product_spus, filter_product_skus
from apps.products.models import ProductSPU
from .internal_readonly_api import READY, _authenticate, _consume_limit, _image_url
from .internal_sso import _PKCE_PATTERN, _STATE_PATTERN, _VERIFIER_PATTERN, SSOAuthorizeThrottle
from .models import EmployeeReadonlyGrant, InternalAPIClient

AUDIENCE = "employee-readonly-v1"
RESOURCES = {"products": "products.master.view", "product_details": "products.master.view", "stores": "masterdata.view", "warehouses": "masterdata.view"}
logger = logging.getLogger("employee_readonly.audit")
SOURCE_PATHS = {"products": "/api/internal/products/spus/", "product_details": "/api/internal/products/skus/", "stores": "/api/internal/master-data/stores/", "warehouses": "/api/internal/master-data/warehouses/"}


def success_response(data):
    response = _success_response(data)
    response["Cache-Control"] = "no-store"
    return response


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cursor_cipher():
    key = hashlib.sha256((AUDIENCE+settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def policy(client):
    return bool(getattr(settings, "EMPLOYEE_READONLY_ENABLED", False) and client and client.client_id in getattr(settings, "EMPLOYEE_READONLY_CLIENT_IDS", []))


def eligible(user, client):
    return bool(policy(client) and not user.is_superuser and user.tenant_id is not None and client.tenant_id is not None and user.is_active and user.user_type == CustomUser.UserType.INTERNAL and user.tenant_id == client.tenant_id and credential_lease_active(user))


def fingerprint(user, client):
    # Read fresh DB relations: M2M removal and scope/metadata edits have no timestamp guarantee.
    role_ids = list(UserRole.objects.filter(user=user, tenant_id=user.tenant_id, role__tenant_id=user.tenant_id).values_list("role_id", flat=True))
    payload = {
        "user": [user.pk, user.tenant_id, user.is_active, user.is_superuser, user.user_type, user.get_session_auth_hash()],
        "roles": list(Role.objects.filter(pk__in=role_ids).order_by("pk").values("id", "status")),
        "permissions": list(Permission.objects.filter(roles__id__in=role_ids).distinct().order_by("pk").values("id", "code", "permission_type", "metadata")),
        "scopes": list(DataScope.objects.filter(role_id__in=role_ids).order_by("pk").values("id", "tenant_id", "role_id", "scope_type", "config")),
        "client": [client.pk, client.tenant_id, client.status, client.approval_status, client.expires_at, client.config_version, client.resources, client.allowed_cidrs, client.sso_redirect_uris, client.secret_hash, client.rate_limit_per_minute, client.page_size_limit],
        "policy": [policy(client), getattr(settings, "EMPLOYEE_READONLY_FIELD_POLICIES", {})],
    }
    return digest(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")))


def respond(request, status, decision, client=None, user=None, resource=None, scope=None, filters=None):
    rid = str(uuid.uuid4())
    logger.info("employee_readonly_decision", extra={"request_id": rid, "decision": decision, "client_id": getattr(client, "pk", None), "subject": getattr(user, "pk", None), "tenant": getattr(client, "tenant_id", None), "resource": resource})
    if client:
        OperationLog.objects.create(tenant_id=client.tenant_id, user=user, module="employee_readonly", action="allow" if status == 200 else "deny", object_type="delegation", object_id=str(client.pk), after_data={"request_id": rid, "decision": decision, "status": status, "client": client.pk, "subject": getattr(user, "pk", None), "tenant": client.tenant_id, "resource": resource, "scope_fingerprint": scope, "filter_keys": sorted(filters or {})})
    response = Response({"detail": decision, "request_id": rid}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def fields_for(user, resource):
    if user.is_superuser:
        return []
    mapping = getattr(settings, "EMPLOYEE_READONLY_FIELD_POLICIES", {}).get(resource, {})
    if not isinstance(mapping, dict):
        return []
    # No guessed permission names: only catalog FIELD policies explicitly mapped by operators.
    catalog = {row["code"]: row["metadata"] or {} for row in effective_permissions().filter(code__in=[v for v in mapping.values() if isinstance(v, str)], permission_type=Permission.PermissionType.FIELD).values("code", "metadata")}
    valid = {code for field, code in mapping.items() if isinstance(code, str) and catalog.get(code, {}).get("resource") == "employee_readonly."+resource and catalog.get(code, {}).get("field") == field}
    grants = get_field_permission_map(user, valid, default=False)
    return [field for field in READY[resource][1] if mapping.get(field) in valid and grants.get(mapping[field], False)]


def allowed(user, client, resource):
    code = RESOURCES.get(resource)
    return bool(code and resource in client.resources and check_user_permission(user, code) and get_permission_data_scopes(user, code) and fields_for(user, resource))


def principal(request, *, limit=True):
    client = _authenticate(request)
    if not policy(client):
        return None, respond(request, 401, "Delegation unavailable.", client)
    header = request.META.get("HTTP_X_EMPLOYEE_DELEGATION", "")
    if not header.startswith("Bearer ") or len(header) > 180:
        return None, respond(request, 401, "Invalid delegation.", client)
    grant = EmployeeReadonlyGrant.objects.select_related("user").filter(token_hash=digest(header[7:]), client=client, audience=AUDIENCE, revoked_at__isnull=True, expires_at__gt=timezone.now()).first()
    if not grant or not eligible(grant.user, client) or not secrets.compare_digest(grant.authorization_fingerprint, fingerprint(grant.user, client)):
        return None, respond(request, 401, "Invalid delegation.", client)
    if limit and not _consume_limit(client):
        return None, respond(request, 429, "Rate limit exceeded.", client, grant.user)
    return (client, grant.user, grant), None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([SSOAuthorizeThrottle])
def authorize(request):
    data = request.data
    names = ("client_id", "redirect_uri", "state", "code_challenge", "audience")
    if not isinstance(data, dict) or set(data) != set(names) or any(not isinstance(data.get(k), str) for k in names):
        return respond(request, 400, "Invalid authorization request.")
    client = InternalAPIClient.objects.filter(client_id=data["client_id"], tenant_id=request.user.tenant_id, status="active", approval_status="approved").first()
    try:
        callback = urlsplit(data["redirect_uri"])
    except ValueError:
        return respond(request, 400, "Invalid callback.")
    if not client or not eligible(request.user, client) or (client.expires_at and client.expires_at <= timezone.now()) or data["redirect_uri"] not in client.sso_redirect_uris or callback.scheme != "https" or not callback.hostname or callback.username or callback.password or callback.fragment or callback.query:
        return respond(request, 403, "Delegation unavailable.", client, request.user)
    if data["audience"] != AUDIENCE or not _STATE_PATTERN.fullmatch(data["state"]) or not _PKCE_PATTERN.fullmatch(data["code_challenge"]):
        return respond(request, 400, "Invalid authorization request.", client, request.user)
    code = secrets.token_urlsafe(32)
    EmployeeReadonlyGrant.objects.create(client=client, user=request.user, code_hash=digest(code), state_hash=digest(data["state"]), code_challenge=data["code_challenge"], redirect_uri=data["redirect_uri"], audience=AUDIENCE, authorization_fingerprint=fingerprint(request.user, client), code_expires_at=timezone.now()+timedelta(seconds=90))
    respond(request, 200, "authorize", client, request.user)
    return success_response({"redirect_url": data["redirect_uri"]+"?"+urlencode({"code": code, "state": data["state"]})})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def exchange(request):
    client = _authenticate(request)
    if not policy(client):
        return respond(request, 401, "Client authentication failed.", client)
    if not _consume_limit(client):
        return respond(request, 429, "Rate limit exceeded.", client)
    data = request.data
    if not isinstance(data, dict) or set(data) != {"code", "state", "redirect_uri", "code_verifier", "audience"} or any(not isinstance(data.get(k), str) or len(data[k]) > 2048 for k in ("code", "state", "redirect_uri", "code_verifier", "audience")) or not _VERIFIER_PATTERN.fullmatch(data["code_verifier"]):
        return respond(request, 400, "Invalid exchange.", client)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    with transaction.atomic():
        grant = EmployeeReadonlyGrant.objects.select_for_update().select_related("user").filter(code_hash=digest(data["code"]), client=client).first()
        if not grant or grant.consumed_at or grant.revoked_at or grant.code_expires_at <= timezone.now() or data["audience"] != AUDIENCE or grant.audience != AUDIENCE or grant.redirect_uri != data["redirect_uri"] or data["redirect_uri"] not in client.sso_redirect_uris or not secrets.compare_digest(grant.state_hash, digest(data["state"])) or not secrets.compare_digest(grant.code_challenge, challenge) or not eligible(grant.user, client) or not secrets.compare_digest(grant.authorization_fingerprint, fingerprint(grant.user, client)):
            return respond(request, 401, "Invalid exchange.", client)
        token = secrets.token_urlsafe(48)
        grant.token_hash = digest(token)
        grant.consumed_at = timezone.now()
        grant.expires_at = timezone.now()+timedelta(seconds=300)
        grant.save(update_fields=["token_hash", "consumed_at", "expires_at"])
    respond(request, 200, "exchange", client, grant.user)
    return success_response({"access_token": token, "token_type": "Bearer", "expires_in": 300, "audience": AUDIENCE})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def revoke(request):
    actor, error = principal(request, limit=False)
    if error is not None:
        return error
    client, user, grant = actor
    # Logout of this delegation revokes every grant for the same employee/client.
    EmployeeReadonlyGrant.objects.filter(client=client, user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
    respond(request, 200, "revoke", client, user)
    return success_response({"revoked": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def revoke_all(request):
    if request.data:
        return respond(request, 400, "Request body must be empty.")
    active = EmployeeReadonlyGrant.objects.filter(user=request.user, revoked_at__isnull=True)
    for client in InternalAPIClient.objects.filter(pk__in=active.values("client_id")).distinct():
        respond(request, 200, "revoke_all", client, request.user)
    active.update(revoked_at=timezone.now())
    return success_response({"revoked": True})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def capabilities(request):
    actor, error = principal(request)
    if error is not None:
        return error
    client, user, _ = actor
    respond(request, 200, "capabilities", client, user)
    return success_response({"audience": AUDIENCE, "ready_resources": [{"code": r, "fields": fields_for(user, r), "filters": ["id"], "source_path": SOURCE_PATHS[r]} for r in RESOURCES if allowed(user, client, r)], "pending_resources": ["sales_orders", "purchase_orders", "inventory_snapshots", "financial_aggregates"]})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def collection(request, resource):
    actor, error = principal(request)
    if error is not None:
        return error
    client, user, grant = actor
    if resource not in RESOURCES:
        return respond(request, 404, "Resource unavailable.", client, user, resource)
    if not allowed(user, client, resource):
        return respond(request, 403, "Resource access denied.", client, user, resource)
    if set(request.query_params)-{"id", "limit", "cursor"}:
        return respond(request, 400, "Unsupported filter.", client, user, resource)
    try:
        limit = int(request.query_params.get("limit", min(100, client.page_size_limit)))
        filters = {"id": int(request.query_params["id"])} if "id" in request.query_params else {}
        if not 1 <= limit <= min(100, client.page_size_limit) or any(v < 1 for v in filters.values()):
            raise ValueError
        after = 0
        if request.query_params.get("cursor"):
            raw_cursor = request.query_params["cursor"].encode("ascii")
            if len(raw_cursor) > 4096 or base64.urlsafe_b64encode(base64.urlsafe_b64decode(raw_cursor)) != raw_cursor:
                raise ValueError
            cursor = json.loads(cursor_cipher().decrypt(raw_cursor, ttl=300))
            if cursor["binding"] != [grant.pk, resource, filters, grant.authorization_fingerprint]:
                raise ValueError
            after = int(cursor["after"])
    except (ValueError, TypeError, KeyError, InvalidToken, UnicodeError):
        return respond(request, 400, "Invalid pagination or filter.", client, user, resource)
    model, _ = READY[resource]
    query = model.objects.filter(tenant_id=user.tenant_id)
    permission = RESOURCES[resource]
    if resource == "products":
        query = filter_product_spus(user, query, permission)
    elif resource == "product_details":
        query = filter_product_skus(user, query.filter(spu_id__in=ProductSPU.objects.filter(tenant_id=user.tenant_id).values("pk")), permission)
    else:
        query = filter_master_data(user, query, permission, resource)
    query = query.filter(**filters).filter(id__gt=after).order_by("id")
    fields = fields_for(user, resource)
    rows = list(query.values(*set(fields+["id", "updated_at"]))[:limit+1])
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = cursor_cipher().encrypt(json.dumps({"binding": [grant.pk, resource, filters, grant.authorization_fingerprint], "after": page[-1]["id"]}).encode()).decode() if has_more else None
    updated = max((row["updated_at"] for row in page if row["updated_at"]), default=None)
    items = [{k: (_image_url(request, row[k]) if k == "image_url" else row[k]) for k in fields} for row in page]
    audit = respond(request, 200, "allow", client, user, resource, grant.authorization_fingerprint, filters)
    logger.info("employee_readonly_scope", extra={"request_id": audit.data["request_id"], "scope_fingerprint": grant.authorization_fingerprint, "filter_keys": sorted(filters), "returned_count": len(items)})
    response = success_response({"resource": resource, "items": items, "query_time": timezone.now(), "business_updated_at": updated if "updated_at" in fields else None, "filters": filters, "returned_count": len(items), "has_more": has_more, "next_cursor": next_cursor, "source_path": SOURCE_PATHS[resource], "request_id": audit.data["request_id"]})
    response["Cache-Control"] = "no-store"
    return response
