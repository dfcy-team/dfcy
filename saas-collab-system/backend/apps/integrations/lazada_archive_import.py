"""Import existing Lazada credentials into custody, never exchange or refresh."""
import hashlib
import json
import zipfile

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .custody import get_custody_backend
from .live_providers import LazadaLiveOAuthProvider
from .models import IntegrationAuditLog, MarketplaceStoreAuthorization, PlatformIntegrationConfig, authorization_service_write
from .production_settings import get_runtime_platform_config
from .store_authorization_service import create_store_authorization, rotate_store_authorization_references, transition_store_authorization


NO_REFRESH = "local:no-refresh"


def read_archive(path):
    with zipfile.ZipFile(path) as archive:
        files = [n for n in archive.infolist() if n.filename.endswith("/config.json") and "/.venv/" not in n.filename]
        if len(files) != 1 or files[0].file_size > 131072:
            raise ValidationError("压缩包必须只有一份顶层配置，且不得超过128KB。")
        data = json.loads(archive.read(files[0]))
    source = data.get("lazada", {})
    if not isinstance(source.get("apps"), dict) or not isinstance(source.get("stores"), dict):
        raise ValidationError("缺少 Lazada 应用或店铺配置。")
    return source


def prepare_import(source, actor):
    if not actor.is_active or actor.user_type != "internal":
        raise PermissionDenied("须使用有效内部账户。")
    for permission in ("integrations.store.authorize", "integrations.credential.rotate"):
        if not check_user_permission(actor, permission):
            raise PermissionDenied("缺少授权导入权限。")
    if get_runtime_platform_config("lazada").get("auto_refresh_enabled"):
        raise ValidationError("请先关闭 Lazada 自动刷新，再导入。")
    plans = []
    for code, saved in source["stores"].items():
        store = StoreMaster.objects.filter(tenant_id=actor.tenant_id, code=code, platform__code__iexact="lazada").first()
        if not store or str(saved.get("country", "")).upper() != store.country_code.upper():
            raise ValidationError("店铺编码或国家不匹配，未导入。")
        if not integration_values_allowed(actor, "integrations.store.authorize", platform="lazada",
                environment="production", regions=[store.country_code], store_id=store.pk):
            raise PermissionDenied("店铺不在授权范围。")
        app = source["apps"].get(saved.get("app_profile"), {})
        if not all(isinstance(v, str) and v.strip() for v in (
            app.get("app_key"), app.get("app_secret"), saved.get("access_token"), saved.get("refresh_token")
        )):
            raise ValidationError("现有授权字段不完整，未尝试刷新。")
        expiry = parse_datetime(str(saved.get("access_token_expires_at", "")))
        if not expiry or timezone.is_naive(expiry):
            raise ValidationError("授权缺少含时区的原始到期时间，不能按当前时间重算。")
        identity = LazadaLiveOAuthProvider._store_record(saved, store.country_code)
        existing = MarketplaceStoreAuthorization.objects.select_related("integration_config").filter(
            tenant_id=actor.tenant_id, store=store, platform="lazada").exclude(status="revoked").first()
        if existing and existing.platform_store_id != identity["platform_store_id"]:
            raise ValidationError("归档卖家身份与现有授权不同，禁止自动覆盖。")
        plans.append((store, saved, app, expiry, identity, existing))
    return plans


def import_archive(path, *, actor, commit=False, custody=None):
    source = read_archive(path)
    plans = prepare_import(source, actor)
    if not commit:
        return [{"store":s.code, "expires_at":e.isoformat(), "action":"preview", "refresh_allowed":False}
                for s, _, _, e, _, _ in plans]
    custody = custody or get_custody_backend()
    results = []
    for store, saved, app, expiry, identity, existing in plans:
        with transaction.atomic():
            if existing:
                existing = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=existing.pk)
                if existing.expires_at and existing.expires_at > timezone.now():
                    existing.scopes = sorted(set(existing.scopes or []) | {NO_REFRESH})
                    existing.updated_by = actor
                    with authorization_service_write():
                        existing.save(update_fields=["scopes", "updated_by", "updated_at"])
                    IntegrationAuditLog.objects.create(tenant=store.tenant, integration_config=existing.integration_config,
                        store_authorization=existing, actor=actor, action="lazada_archive.preserve",
                        result="success", masked_detail={"store_id":store.pk, "refresh_allowed":False})
                    results.append({"store":store.code,"authorization_id":existing.pk,"action":"preserved","refresh_allowed":False})
                    continue
                config = existing.integration_config
                public_key = (config.platform_config or {}).get("app_key") or get_runtime_platform_config("lazada").get("app_id")
                if str(public_key) != app["app_key"]:
                    raise ValidationError("现有接入配置与归档应用不一致，未覆盖。")
            else:
                config = next((c for c in PlatformIntegrationConfig.objects.filter(
                    tenant_id=actor.tenant_id, platform="lazada", environment="production")
                    if (c.platform_config or {}).get("app_key") == app["app_key"]), None)
                if config is None:
                    config = PlatformIntegrationConfig.objects.create(tenant=store.tenant, platform="lazada",
                        account_alias="Lazada归档只读应用-"+store.code, environment="production", status="verified",
                        regions=[store.country_code], contract_version="open-platform-v1",
                        platform_config={"app_key":app["app_key"],"api_type":"marketplace"},
                        network_enabled=True, sync_read_enabled=True, sync_write_enabled=False, created_by=actor)
            if config.sync_write_enabled:
                raise ValidationError("导入拒绝开启平台写能力的接入配置。")
            operation = hashlib.sha256(("lazada-archive:"+str(store.tenant_id)+":"+store.code+":"+saved["access_token"]).encode()).hexdigest()
            stored = custody.store_secrets(credential_type="lazada", reference_version=1,
                app_secret=app["app_secret"], access_token=saved["access_token"], refresh_token=saved["refresh_token"],
                expires_at=expiry.isoformat(), idempotency_key=operation, operation_id=operation,
                metadata={"tenant_id":store.tenant_id,"store_id":store.pk,"platform":"lazada","refresh_allowed":False})
            try:
                if existing:
                    refreshed_at = existing.refreshed_at
                    record = rotate_store_authorization_references(existing,
                        credential_id=stored["credential_id"], token_id=stored["token_id"],
                        version=existing.credential_reference_version+1, actor=actor, expires_at=expiry,
                        credential_mask=stored.get("credential_mask"), allow_live_references=True,
                        revoker=custody.revoke, new_reference_revoker=custody.revoke, defer_previous_revocation=True)
                    record.refreshed_at = refreshed_at
                else:
                    record = create_store_authorization(tenant=store.tenant, integration_config=config, store=store,
                        platform="lazada", region=store.country_code, platform_store_id=identity["platform_store_id"],
                        merchant_subject_id=identity["merchant_subject_id"], shop_cipher="",
                        credential_id=stored["credential_id"], token_id=stored["token_id"],
                        credential_mask=stored.get("credential_mask"), allow_live_references=True,
                        expires_at=expiry, scopes=[], actor=actor)
                record.scopes = sorted(set(record.scopes or []) | {NO_REFRESH})
                with authorization_service_write():
                    record.save(update_fields=["scopes", "refreshed_at", "updated_at"])
                if record.status != "active":
                    record = transition_store_authorization(record, target_status="active", actor=actor)
                if expiry <= timezone.now():
                    record = transition_store_authorization(record, target_status="expired", actor=actor, expires_at=expiry)
                original_updated = parse_datetime(str(saved.get("token_updated_at", "")))
                record.refreshed_at = original_updated if original_updated and timezone.is_aware(original_updated) else existing.refreshed_at if existing else None
                with authorization_service_write():
                    record.save(update_fields=["refreshed_at", "updated_at"])
                IntegrationAuditLog.objects.create(tenant=store.tenant, integration_config=config,
                    store_authorization=record, actor=actor, action="lazada_archive.import", result="success",
                    masked_detail={"store_id":store.pk,"refresh_allowed":False,"source":"existing_archive"})
            except Exception:
                custody.revoke(stored["credential_id"], stored["token_id"])
                raise
            results.append({"store":store.code,"authorization_id":record.pk,"action":"imported",
                "expires_at":expiry.isoformat(),"refresh_allowed":False})
    return results
