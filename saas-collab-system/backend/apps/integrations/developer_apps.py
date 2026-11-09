import secrets, re
from datetime import timedelta
from rest_framework import serializers
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS
from django.db import transaction
from apps.permissions.services import _check_role_grant_permission, is_api_access_admin
from apps.common.responses import success_response
from apps.permissions.api_permissions import IsInternalAPIClientApprover
from .models import DeveloperApplication, DeveloperEndpoint, DeveloperCallLog, PlatformIntegrationConfig

class IsDeveloperAppUser(BasePermission):
    def has_permission(self, request, view):
        code="integrations.developer_app.view" if request.method in SAFE_METHODS else "integrations.developer_app.manage"
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.tenant_id and user.user_type == "internal" and (is_api_access_admin(user) or _check_role_grant_permission(user, code)))

class ApplicationInput(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    endpoint_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False)
    expires_at = serializers.DateTimeField(required=False)
    def validate_expires_at(self, value):
        if value <= timezone.now() or value > timezone.now() + timedelta(days=90): raise ValidationError("有效期须在未来90天内。")
        return value

def _input(request, partial=False):
    serializer = ApplicationInput(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data

def authenticate_developer_token(token):
    """Resolve ``<app-id>.<secret>`` without scanning, then validate current grants."""
    try:
        app_id, secret = token.split(".", 1)
        if not app_id.isdigit() or len(app_id) > 18 or len(secret) > 128: return None
        app=DeveloperApplication.objects.get(pk=int(app_id),status="active",expires_at__gt=timezone.now())
    except (ValueError, TypeError, DeveloperApplication.DoesNotExist, AttributeError): return None
    owner = app.owner
    return app if owner.is_active and owner.user_type == "internal" and owner.tenant_id == app.tenant_id and app.approved_endpoint_ids and app.secret_hash and check_password(secret,app.secret_hash) else None

def _app(request, pk):
    queryset = DeveloperApplication.objects.filter(tenant=request.user.tenant)
    if not is_api_access_admin(request.user): queryset = queryset.filter(owner=request.user)
    return get_object_or_404(queryset, pk=pk)
def _endpoint_dict(e):
    return {"id":e.id,"code":e.code,"name":e.name,"connection_id":e.config_id,"account_id":e.account_id,"method":e.method,"path":e.relative_path,"scope_mode":e.scope_mode,"auth_mode":e.auth_mode}
def _detail(a):
    return {"id":a.id,"name":a.name,"description":a.description,"status":a.status,"approval_status":a.approval_status,"expires_at":a.expires_at,"requested_expires_at":a.requested_expires_at,"owner_id":a.owner_id,"owner_name":a.owner.username,"updated_by_id":a.updated_by_id,"requested_endpoint_ids":list(a.requested_endpoint_ids),"approved_endpoint_ids":list(a.approved_endpoint_ids),"docs_url":f"/api/internal/integrations/developer-apps/{a.id}/docs/"}
def _ids(values, tenant):
    if not isinstance(values,list) or not values: raise ValidationError({"endpoint_ids":"Provide a non-empty list."})
    eps=list(DeveloperEndpoint.objects.filter(id__in=values,approved=True,config__tenant=tenant))
    if len({e.id for e in eps}) != len(set(values)): raise ValidationError({"endpoint_ids":"Unknown or unavailable endpoint."})
    return sorted(set(values))

@api_view(["GET","POST"])
@permission_classes([IsDeveloperAppUser])
def collection(request):
    if request.method=="GET":
        apps=DeveloperApplication.objects.filter(tenant=request.user.tenant).select_related("owner")
        if not is_api_access_admin(request.user): apps=apps.filter(owner=request.user)
        configs=PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant)
        from .models import MarketplaceStoreAuthorization
        accounts=MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant)
        return success_response({"items":[_detail(a) for a in apps],"connections":[{"id":c.id,"platform":c.platform,"name":c.account_alias} for c in configs],"accounts":[{"id":ac.id,"connection_id":ac.integration_config_id,"name":ac.platform_store_id} for ac in accounts],"endpoints":[_endpoint_dict(e) for e in DeveloperEndpoint.objects.filter(config__tenant=request.user.tenant,approved=True)]})
    data = _input(request)
    ids = _ids(data["endpoint_ids"], request.user.tenant)
    a=DeveloperApplication.objects.create(tenant=request.user.tenant,owner=request.user,updated_by=request.user,name=data["name"],description=data.get("description", ""),requested_endpoint_ids=ids,requested_expires_at=data.get("expires_at", timezone.now()+timedelta(days=7)))
    DeveloperCallLog.objects.create(tenant=a.tenant,application=a,actor=request.user,action="submitted")
    return success_response({"id":a.id,"status":"pending","approval_status":"pending","endpoints":ids},status=201)

@api_view(["GET","PATCH"])
@permission_classes([IsDeveloperAppUser])
def detail(request,pk):
    if request.method=="GET": return success_response(_detail(_app(request,pk)))
    data = _input(request, partial=True)
    with transaction.atomic():
        a=get_object_or_404(DeveloperApplication.objects.select_for_update(),pk=pk,tenant=request.user.tenant,owner=request.user)
        if "endpoint_ids" in data: a.requested_endpoint_ids=_ids(data["endpoint_ids"],a.tenant)
        if "expires_at" in data: a.requested_expires_at=data["expires_at"]
        for key in ("name","description"):
            if key in data: setattr(a,key,data[key])
        a.approval_status="pending"; a.updated_by=request.user; a.save()
    DeveloperCallLog.objects.create(tenant=a.tenant,application=a,actor=request.user,action="changed")
    return success_response(_detail(a))

@api_view(["POST"])
@permission_classes([IsInternalAPIClientApprover])
def review(request,pk):
    with transaction.atomic():
        a=get_object_or_404(DeveloperApplication.objects.select_for_update(),pk=pk,tenant=request.user.tenant)
        decision=request.data.get("decision")
        if decision not in ("approve","reject"): raise ValidationError({"decision":"Must be approve or reject."})
        if a.owner_id==request.user.id or a.updated_by_id==request.user.id: raise ValidationError({"decision":"Cannot approve own application."})
        if a.approval_status!="pending": raise ValidationError({"decision":"Application is not pending."})
        a.approval_status="approved" if decision=="approve" else "rejected"
        if decision=="approve":
            _ids(a.requested_endpoint_ids, a.tenant)
            if not a.requested_expires_at or a.requested_expires_at <= timezone.now(): raise ValidationError("申请已过期。")
            a.status="active"
        elif not a.approved_endpoint_ids: a.status="disabled"
        if decision=="approve": a.approved_endpoint_ids=a.requested_endpoint_ids; a.expires_at=a.requested_expires_at
        a.updated_by=request.user; a.save()
        DeveloperCallLog.objects.create(tenant=a.tenant,application=a,actor=request.user,action=decision,detail={"reason":str(request.data.get("reason", ""))[:500]})
    return success_response({"id":a.id,"status":a.status,"approval_status":a.approval_status})

@api_view(["POST"])
@permission_classes([IsDeveloperAppUser])
def token(request,pk):
    with transaction.atomic():
        a=get_object_or_404(DeveloperApplication.objects.select_for_update(),pk=pk,tenant=request.user.tenant,owner=request.user)
        if not a.approved_endpoint_ids or a.status!="active" or not a.expires_at or a.expires_at <= timezone.now(): raise ValidationError("Application must be approved.")
        secret=secrets.token_urlsafe(40); a.secret_hash=make_password(secret); a.save(update_fields=["secret_hash","updated_at"])
        DeveloperCallLog.objects.create(tenant=a.tenant,application=a,actor=request.user,action="token_issued")
    response = success_response({"token":f"{a.pk}.{secret}","token_display_once":True,"expires_at":a.expires_at})
    response["Cache-Control"] = "no-store"
    return response

@api_view(["POST"])
@permission_classes([IsDeveloperAppUser])
def revoke(request,pk):
    with transaction.atomic():
        queryset=DeveloperApplication.objects.select_for_update().filter(tenant=request.user.tenant)
        if not is_api_access_admin(request.user): queryset=queryset.filter(owner=request.user)
        a=get_object_or_404(queryset,pk=pk); a.secret_hash=""; a.status="disabled"; a.save(update_fields=["secret_hash","status","updated_at"])
        DeveloperCallLog.objects.create(tenant=a.tenant,application=a,actor=request.user,action="revoked")
    return success_response(_detail(a))

@api_view(["GET"])
@permission_classes([IsDeveloperAppUser])
def logs(request,pk):
    a=_app(request,pk); items=[]
    for row in a.logs.order_by("-id").values("action","detail","created_at")[:200]:
        items.append({"action":row["action"],"created_at":row["created_at"],**(row["detail"] or {})})
    return success_response({"items":items})

@api_view(["GET","POST"])
@permission_classes([IsDeveloperAppUser])
def catalog(request):
    if request.method=="GET":
        from .models import MarketplaceStoreAuthorization
        configs=PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant)
        accounts=MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant)
        return success_response({"connections":[{"id":c.id,"platform":c.platform,"name":c.account_alias} for c in configs],"accounts":[{"id":ac.id,"connection_id":ac.integration_config_id,"name":ac.platform_store_id} for ac in accounts],"endpoints":[_endpoint_dict(e) for e in DeveloperEndpoint.objects.filter(approved=True,config__tenant=request.user.tenant)]})
    if not is_api_access_admin(request.user): raise PermissionDenied("API administrator registration required.")
    data=request.data; config=get_object_or_404(PlatformIntegrationConfig,pk=data.get("connection_id"),tenant=request.user.tenant)
    method=str(data.get("method","POST")).upper(); path=str(data.get("path","")); auth=str(data.get("auth_mode","bearer")); base=str(data.get("base_url", "")).rstrip("/")
    from urllib.parse import urlsplit
    try:
        parsed=urlsplit(base)
    except ValueError:
        raise ValidationError({"base_url": "平台地址格式无效。"}) from None
    from .models import MarketplaceStoreAuthorization
    account=get_object_or_404(MarketplaceStoreAuthorization,pk=data.get("account_id"),tenant=request.user.tenant,integration_config=config) if data.get("account_id") else None
    platform_scope = path == "/"
    if platform_scope:
        expected_auth = {"shopee": "shopee_shop", "tiktok": "tiktok_shop", "lazada": "lazada"}.get(config.platform)
        if not account or not expected_auth or auth != expected_auth:
            raise ValidationError("平台级授权仅支持绑定匹配平台的已授权店铺签名适配器。")
        from .production_settings import get_runtime_platform_config
        runtime = get_runtime_platform_config(config.platform)
        expected_base = runtime.get("api_host", "")
        if config.platform == "lazada":
            from .readonly_clients import _lazada_api_host
            expected_base = _lazada_api_host(account.region, expected_base)
        if not expected_base or urlsplit(expected_base).hostname != parsed.hostname:
            raise ValidationError("平台级授权必须使用该平台账号配置的固定 API 主机。")
    if method not in ("GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS") or (not platform_scope and (not path.startswith("/") or ".." in path or re.search(r"https?://",path))) or auth not in ("bearer","api_key","tiktok_shop","shopee_shop","lazada") or parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or (platform_scope and account is None):
        raise ValidationError("Unsupported method, relative path, HTTPS origin, or auth mode.")
    from .developer_transport import build_gateway_url
    from .oauth_errors import OAuthFlowError
    try: build_gateway_url(base, path, {})
    except (OAuthFlowError, ValueError): raise ValidationError("目标域名尚未获准或路径无效。")
    code = str(data.get("code") or "")
    name = str(data.get("name") or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", code) or not name or len(name)>160: raise ValidationError("接口代码或名称无效。")
    if DeveloperEndpoint.objects.filter(config__tenant=request.user.tenant, code=code).exists(): raise ValidationError("接口代码在租户内已存在。")
    e=DeveloperEndpoint.objects.create(config=config,account=account,code=data.get("code"),name=data.get("name"),method=method,relative_path=path,scope_mode="platform" if platform_scope else "fixed",base_url=base,auth_mode=auth,approved=True,created_by=request.user)
    return success_response(_endpoint_dict(e),status=201)

@api_view(["GET"])
@permission_classes([IsDeveloperAppUser])
def docs(request,pk):
    a=_app(request,pk)
    from .developer_docs import documentation_response
    return documentation_response(a, request)
