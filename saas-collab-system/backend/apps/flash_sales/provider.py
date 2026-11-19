"""Direct Shopee transport; never retries writes at the HTTP layer."""
import hashlib
import hmac
import time
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.custody import get_custody_backend
from apps.integrations.developer_transport import gateway_transport
from apps.integrations.net_guard import PlatformHttpClient
from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_RATE_LIMITED
from apps.integrations.production_settings import get_runtime_platform_config
from apps.integrations.security import sanitize_text
from .domain import normalize_items
from .models import AppPacer, TenantControl
from .services import authorized_store


READS = {"get_time_slot_id", "get_shop_flash_sale_list", "get_shop_flash_sale", "get_shop_flash_sale_items"}
WRITES = {"create_shop_flash_sale", "add_shop_flash_sale_items", "update_shop_flash_sale_items", "update_shop_flash_sale", "delete_shop_flash_sale"}


class Deferred(Exception):
    def __init__(self, message="平台暂不可用，等待后重试", retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class UnknownWrite(Deferred):
    pass


class Rejected(Exception):
    def __init__(self, code, message="平台明确拒绝本次操作"):
        super().__init__(message)
        self.code = code


class ShopeeAdapter:
    def __init__(self, store):
        self.store = store
        self.guard = None
        self.write_guard = None

    def _pace(self, partner):
        now = timezone.now()
        key = hashlib.sha256(f"shopee:{partner}".encode()).hexdigest()
        AppPacer.objects.get_or_create(key=key, defaults={"next_request_at": now})
        with transaction.atomic():
            pacer = AppPacer.objects.select_for_update().get(pk=key)
            delay = max(0, (pacer.next_request_at - now).total_seconds())
            if delay > 2:
                raise Deferred("应用共享限流等待", retry_after=int(delay) + 1)
            pacer.next_request_at = max(now, pacer.next_request_at) + timedelta(seconds=1)
            pacer.save(update_fields=["next_request_at"])
        if delay:
            time.sleep(delay)

    def call(self, endpoint, *, query=None, body=None):
        if self.guard:
            self.guard()
        write = body is not None
        if endpoint not in (WRITES if write else READS):
            raise ValidationError("闪购接口不在允许范围内。")
        if not getattr(settings, "FLASH_SALES_LIVE_ENABLED", False):
            raise ValidationError("正式闪购调用尚未启用；本次未调用平台。")
        if write and not TenantControl.objects.filter(tenant_id=self.store.tenant_id, scheduler_owner="saas").exists():
            raise ValidationError("尚未完成单边接管；本次未提交平台写入。")
        auth = authorized_store(self.store)
        config = auth.integration_config
        if not config.network_enabled or config.status not in {"active", "verified"}:
            raise ValidationError("店铺连接未启用。")
        if not auth.expires_at or auth.expires_at <= timezone.now() + timedelta(seconds=30):
            # The established credential-refresh queue owns renewal; no second token refresher.
            raise Deferred("等待既有凭据续期流程完成")
        runtime = get_runtime_platform_config("shopee")
        host = str(runtime.get("api_host") or "").rstrip("/")
        if host not in {"https://partner.shopeemobile.com", "https://openplatform.shopee.cn"}:
            raise ValidationError("Shopee 正式 API 主机不匹配。")
        partner = str(config.platform_config.get("partner_id") or runtime.get("app_id") or "")
        if not partner:
            raise ValidationError("开发者配置缺少 Partner ID。")
        self._pace(partner)
        custody = get_custody_backend()
        secret = custody.retrieve_secret(config.credential_id or config.platform_config.get("app_secret_reference"))
        token = custody.retrieve_access_token(auth.token_id)
        path = "/api/v2/shop_flash_sale/" + endpoint
        stamp = int(time.time())
        params = {"partner_id": partner, "timestamp": stamp, "shop_id": auth.platform_store_id, "access_token": token}
        params["sign"] = hmac.new(secret.encode(), f"{partner}{path}{stamp}{token}{auth.platform_store_id}".encode(), hashlib.sha256).hexdigest()
        if set(query or {}) & set(params):
            raise ValidationError("业务字段不能覆盖鉴权字段。")
        params.update(query or {})
        if self.guard:
            self.guard()
        if write and self.write_guard:
            self.write_guard()
        try:
            response = PlatformHttpClient(transport=gateway_transport, max_retries=0).request("POST" if write else "GET", host + path + "?" + urlencode(params),
                json_body=body, retry=False, connect_timeout=3, read_timeout=20, diagnostic_platform="shopee")
            payload = response.json()
        except OAuthFlowError as exc:
            if exc.controlled_code == OAUTH_RATE_LIMITED:
                raise Deferred("平台要求限流等待", retry_after=getattr(exc, "retry_after", 300)) from None
            if getattr(exc, "category", "") == "authentication_rejected":
                raise Rejected("authentication_rejected", "平台拒绝授权，请维护店铺授权") from None
            raise (UnknownWrite if write else Deferred)("平台调用尚未确认，等待核对") from None
        except Exception:
            raise (UnknownWrite if write else Deferred)("平台写入结果未知，先回读核对" if write else "平台读取暂未完成") from None
        if not isinstance(payload, dict):
            raise (UnknownWrite if write else Deferred)("平台响应不完整")
        if payload.get("error"):
            code = str(payload["error"])[:80]
            if response.status_code == 429 or "rate" in code.lower() or "limit" in code.lower():
                raise Deferred("平台要求限流等待", retry_after=300)
            raise Rejected(code)
        if "response" not in payload:
            raise (UnknownWrite if write else Deferred)("平台响应缺少结果")
        return payload["response"]

    def activities(self):
        rows = {}
        for kind in (1, 2, 3):
            offset = 0
            while True:
                data = self.call("get_shop_flash_sale_list", query={"type": kind, "offset": offset, "limit": 100})
                page = data.get("flash_sale_list")
                total = data.get("total_count")
                if not isinstance(page, list) or type(total) is not int or offset + len(page) > total:
                    raise Deferred("活动分页结果不完整，保留原缓存")
                for row in page:
                    rows[str(row["flash_sale_id"])] = row
                offset += len(page)
                if offset == total:
                    break
                if not page or offset > 100000:
                    raise Deferred("活动分页未完成，保留原缓存")
        return list(rows.values())

    def items(self, activity_id):
        rows, models, offset = [], [], 0
        while True:
            data = self.call("get_shop_flash_sale_items", query={"flash_sale_id": int(activity_id), "offset": offset, "limit": 100})
            page, total = data.get("item_info"), data.get("total_count")
            if not isinstance(page, list) or type(total) is not int or offset + len(page) > total:
                raise Deferred("活动商品分页结果不完整")
            rows.extend(page)
            models.extend(data.get("models") or [])
            offset += len(page)
            if offset == total:
                return normalize_items(rows, models)
            if not page or offset > 100000:
                raise Deferred("活动商品分页未完成")

    def slots(self):
        now = int(time.time())
        return self.call("get_time_slot_id", query={"start_time": now + 600, "end_time": now + 3 * 86400})

    def detail(self, activity_id):
        try:
            return self.call("get_shop_flash_sale", query={"flash_sale_id": int(activity_id)})
        except Rejected as exc:
            if exc.code == "shop_flash_sale_not_exist":
                return None
            raise


def rejections(response):
    rows = []
    for value in response.get("failed_items", []) if isinstance(response, dict) else []:
        codes = {str(condition.get("unqualified_code")) for condition in value.get("unqualified_conditions", [])}
        message = sanitize_text(str(value.get("err_msg") or value.get("failed_reason") or value.get("message") or "平台拒绝参加"))[:240]
        if "10014" in codes:
            message = "活动价高于平台记录的近 7 天最低价"
        rows.append({"item_id": str(value["item_id"]), "model_id": str(value.get("model_id", 0)),
                     "reason": message, "stock_rejected": "stock" in message.lower() or "库存" in message})
    return rows
