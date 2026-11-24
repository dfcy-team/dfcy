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

from apps.integrations.credential_access import (
    CredentialAccessError, checked_custody_backend, require_token_validity, retrieve_marketplace_credentials,
)
from apps.integrations.developer_transport import gateway_transport
from apps.integrations.net_guard import PlatformHttpClient
from apps.integrations.oauth_errors import OAuthFlowError, OAUTH_RATE_LIMITED
from apps.integrations.production_settings import get_runtime_platform_config
from apps.integrations.security import sanitize_text
from .domain import digest, normalize_items
from .models import AppPacer, StoreTask, TenantControl
from .services import authorized_store


READS = {"get_time_slot_id", "get_shop_flash_sale_list", "get_shop_flash_sale", "get_shop_flash_sale_items"}
WRITES = {"create_shop_flash_sale", "add_shop_flash_sale_items", "update_shop_flash_sale_items", "update_shop_flash_sale", "delete_shop_flash_sale"}
SERVER_ERRORS = {"error_server", "common.error_server"}


class Deferred(Exception):
    def __init__(self, message="平台暂不可用，等待后重试", retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class CredentialWait(Deferred):
    """No platform request was sent; preserve the business retry budget."""
    def __init__(self, error):
        self.code = error.code
        super().__init__(str(error), retry_after=60 if self.code == "TOKEN_REFRESH_REQUIRED" else 300)


class UnknownWrite(Deferred):
    pass


class RateLimited(Deferred):
    """An explicit platform quota response, not a failed execution attempt."""
    pass


class SharedCooldown(Deferred):
    """No platform call was made; waiting for another task's request budget."""
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
        self.task_id = None

    def _pace(self, partner, *, shop=None, endpoint=None):
        now = timezone.now()
        scopes = {hashlib.sha256(f"shopee:cooldown:{partner}:app".encode()).hexdigest(): "应用额度冷却等待"}
        if shop is not None and endpoint is not None:
            scopes[hashlib.sha256(f"shopee:cooldown:{partner}:{shop}:{endpoint}".encode()).hexdigest()] = "该店铺此接口冷却等待"
        cooldown = AppPacer.objects.filter(pk__in=scopes, next_request_at__gt=now).order_by("-next_request_at").first()
        if cooldown:
            raise SharedCooldown(scopes[cooldown.pk], retry_after=int((cooldown.next_request_at - now).total_seconds()) + 1)
        # Retain the existing conservative application ceiling; a shop cooldown
        # slows only that shop/endpoint, not every caller sharing the partner.
        app_cooldown = hashlib.sha256(f"shopee:cooldown:{partner}:app".encode()).hexdigest()
        recent = set(AppPacer.objects.filter(pk__in=scopes,
            next_request_at__gt=now-timedelta(seconds=120)).values_list("pk", flat=True))
        app_interval = 8 if app_cooldown in recent else 4
        interval = 8 if recent else 4
        key = hashlib.sha256(f"shopee:pace:{partner}".encode()).hexdigest()
        shop_key = hashlib.sha256(f"shopee:pace:{partner}:{shop}:{endpoint}".encode()).hexdigest() if shop is not None and endpoint is not None else key
        for value in sorted({key, shop_key}):
            AppPacer.objects.get_or_create(key=value, defaults={"next_request_at": now})
        local_wait = 0
        with transaction.atomic():
            rows = {row.pk: row for row in AppPacer.objects.select_for_update().filter(pk__in={key, shop_key}).order_by("pk")}
            pacer, local = rows[key], rows[shop_key]
            delay = max(0, (pacer.next_request_at-now).total_seconds())
            local_delay = max(0, (local.next_request_at-now).total_seconds())
            if shop_key != key and local_delay > delay:
                if local_delay > 8:
                    raise SharedCooldown("该店铺此接口请求排队等待", retry_after=int(local_delay)+1)
                local_wait = local_delay
            else:
                if delay > 8:
                    raise SharedCooldown("应用请求排队等待", retry_after=int(delay)+1)
                scheduled = max(now, pacer.next_request_at)
                pacer.next_request_at = scheduled + timedelta(seconds=app_interval)
                pacer.save(update_fields=["next_request_at"])
                if shop_key != key:
                    local.next_request_at = scheduled + timedelta(seconds=interval)
                    local.save(update_fields=["next_request_at"])
        if local_wait:
            # Release database locks and leave app capacity available to other shops.
            # Keep the caller's current page instead of restarting its whole read.
            time.sleep(local_wait)
            if self.guard:
                self.guard()
            return self._pace(partner, shop=shop, endpoint=endpoint)
        if delay:
            time.sleep(delay)

    def _cooldown(self, partner, retry_after, *, shop=None, endpoint=None):
        now = timezone.now()
        scope = "app" if shop is None and endpoint is None else f"{shop}:{endpoint}"
        key = hashlib.sha256(f"shopee:cooldown:{partner}:{scope}".encode()).hexdigest()
        AppPacer.objects.get_or_create(key=key, defaults={"next_request_at": now})
        with transaction.atomic():
            pacer = AppPacer.objects.select_for_update().get(pk=key)
            pacer.next_request_at = max(pacer.next_request_at, now + timedelta(seconds=retry_after))
            pacer.save(update_fields=["next_request_at"])

    def call(self, endpoint, *, query=None, body=None):
        if self.guard:
            self.guard()
        write = body is not None
        if endpoint not in (WRITES if write else READS):
            raise ValidationError("闪购接口不在允许范围内。")
        if not getattr(settings, "FLASH_SALES_LIVE_ENABLED", False):
            raise ValidationError("正式闪购调用尚未启用；本次未调用平台。")
        if write:
            owner = TenantControl.objects.filter(tenant_id=self.store.tenant_id).values_list("scheduler_owner", flat=True).first()
            manual_run = owner == "manual" and StoreTask.objects.filter(
                pk=self.task_id, tenant_id=self.store.tenant_id, store=self.store, status="running",
                batch__tenant_id=self.store.tenant_id, batch__source="manual",
                batch__operation="run", batch__plan__isnull=True, batch__finished_at__isnull=True,
            ).exists()
            if owner not in {"saas", "sync_tasks"} and not manual_run:
                raise ValidationError("尚未完成单边接管或当前操作不在手动补建范围；本次未提交平台写入。")
        auth = authorized_store(self.store)
        config = auth.integration_config
        if not config.network_enabled or config.status not in {"active", "verified"}:
            raise ValidationError("店铺连接未启用。")
        try:
            require_token_validity(auth, minimum_validity_seconds=30)
            custody = checked_custody_backend()
        except CredentialAccessError as exc:
            raise CredentialWait(exc) from None
        runtime = get_runtime_platform_config("shopee")
        host = str(runtime.get("api_host") or "").rstrip("/")
        if host not in {"https://partner.shopeemobile.com", "https://openplatform.shopee.cn"}:
            raise ValidationError("Shopee 正式 API 主机不匹配。")
        partner = str(config.platform_config.get("partner_id") or runtime.get("app_id") or "")
        if not partner:
            raise ValidationError("开发者配置缺少 Partner ID。")
        self._pace(partner, shop=auth.platform_store_id, endpoint=endpoint)
        try:
            secret, token = retrieve_marketplace_credentials(
                config, auth, custody=custody, minimum_validity_seconds=30)
        except CredentialAccessError as exc:
            raise CredentialWait(exc) from None
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
                delay = getattr(exc, "retry_after", None) or 300
                self._cooldown(partner, delay, shop=auth.platform_store_id, endpoint=endpoint)
                raise RateLimited(f"平台返回 HTTP 429，等待后自动重试（{endpoint}）", retry_after=delay) from None
            if getattr(exc, "category", "") == "authentication_rejected":
                raise Rejected("authentication_rejected", "平台拒绝授权，请维护店铺授权") from None
            raise (UnknownWrite if write else Deferred)("平台调用尚未确认，等待核对") from None
        except Exception:
            raise (UnknownWrite if write else Deferred)("平台写入结果未知，先回读核对" if write else "平台读取暂未完成") from None
        if not isinstance(payload, dict):
            raise (UnknownWrite if write else Deferred)("平台响应不完整")
        if payload.get("error"):
            code = str(payload["error"])[:80]
            if code in SERVER_ERRORS:
                raise (UnknownWrite if write else Deferred)(f"平台服务器异常（{code}；{endpoint}），等待回读核对", retry_after=300)
            if code in {"error_rate_limit", "common.error_rate_limit"}:
                self._cooldown(partner, 300, shop=auth.platform_store_id, endpoint=endpoint)
                raise RateLimited(f"平台频率限制，等待后自动重试（{code}；{endpoint}）", retry_after=300)
            if code in {"error_limit", "common.error_limit"}:
                message = str(payload.get("message") or "").lower()
                app_quota = "daily" in message and ("app" in message or "partner" in message)
                scope = {} if app_quota else {"shop": auth.platform_store_id, "endpoint": endpoint}
                self._cooldown(partner, 300, **scope)
                raise RateLimited("应用每日调用额度受限，请核对额度" if app_quota else f"平台调用额度限制，范围待核对（{code}；{endpoint}）", retry_after=300)
            raise Rejected(code)
        if "response" not in payload:
            raise (UnknownWrite if write else Deferred)("平台响应缺少结果")
        return payload["response"]

    def _read_page(self, endpoint, query):
        # Only sync jobs attach this checkpoint. Write verification always reads fresh.
        checkpoint = getattr(self, "read_checkpoint", None)
        if checkpoint is None:
            return self.call(endpoint, query=query)
        scope = digest({"endpoint": endpoint, **{key: value for key, value in query.items() if key != "offset"}})
        state = checkpoint.setdefault(scope, {"pages": {}, "saved_at": time.time()})
        if time.time() - state["saved_at"] > 600:
            state.update(pages={}, saved_at=time.time())
        offset = str(query["offset"])
        if offset != "0" and offset in state["pages"]:
            return state["pages"][offset]
        data = self.call(endpoint, query=query)
        # Re-read the first page on every resumed pass; changed data invalidates its pages.
        if offset == "0" and state["pages"].get("0") != data:
            state.update(pages={}, saved_at=time.time())
        field = "flash_sale_list" if endpoint == "get_shop_flash_sale_list" else "item_info"
        page, total = data.get(field), data.get("total_count")
        if page is None and field == "flash_sale_list" and total == 0:
            page = []
        if isinstance(page, list) and type(total) is int and total >= 0 and query["offset"] + len(page) <= total:
            state["pages"][offset] = data
            self.save_read_checkpoint()
        else:
            self._clear_read_checkpoint()
        return data

    def _clear_read_checkpoint(self, scope=None):
        if getattr(self, "read_checkpoint", None):
            if scope is None:
                self.read_checkpoint.clear()
            else:
                self.read_checkpoint.pop(scope, None)
            self.save_read_checkpoint()

    def activities(self, *, window=None, kinds=(1, 2, 3)):
        seen, pages = set(), 0
        def collect(kind, window=None):
            nonlocal pages
            query = {"type": kind, "limit": 100}
            if window is not None:
                query.update(start_time=window[0], end_time=window[1])
            rows, expected = {}, None
            offset = 0
            while True:
                data = self._read_page("get_shop_flash_sale_list", {**query, "offset": offset})
                page = data.get("flash_sale_list")
                total = data.get("total_count")
                if page is None and total == 0:
                    page = []
                if (not isinstance(page, list) or type(total) is not int or total < 0
                        or offset + len(page) > total or (expected is not None and total != expected)):
                    self._clear_read_checkpoint()
                    raise Deferred("活动分页结果不完整，保留原缓存")
                expected = total
                for row in page:
                    rows[str(row["flash_sale_id"])] = row
                    seen.add(str(row["flash_sale_id"]))
                pages += 1
                if getattr(self, "progress", None):
                    self.progress(f"正在读取活动列表：本轮已核对 {len(seen)} 条活动，处理 {pages} 页")
                offset += len(page)
                if offset == total:
                    if len(rows) != total:
                        self._clear_read_checkpoint()
                        raise Deferred("活动分页存在重复或缺失，保留原缓存")
                    return rows
                if not page:
                    raise Deferred("活动分页未完成，保留原缓存")

                # Shopee caps offset at 1000. Split inclusive time windows instead
                # of dropping older activities; reconcile unique IDs at every split.
                if total > 1100 or offset > 1000:
                    if window is None:
                        # Official flash-sale timeslot timestamp ceiling. The total
                        # comparison below also rejects records outside this range.
                        rows = collect(kind, (0, 2145887999))
                    else:
                        start, end = window
                        if end - start <= 1:
                            raise Deferred("活动分页在最小时间区间仍超出平台范围，保留原缓存")
                        middle = (start + end) // 2
                        rows = collect(kind, (start, middle))
                        rows.update(collect(kind, (middle, end)))
                    if len(rows) != total:
                        self._clear_read_checkpoint()
                        raise Deferred("活动分页时间区间核对不一致，保留原缓存")
                    return rows

        rows = {}
        for kind in kinds:
            rows.update(collect(kind, window))
        self._clear_read_checkpoint()
        return list(rows.values())

    def candidate_activities(self, checkpoint, save):
        if "active" not in checkpoint:
            checkpoint["active"] = self.activities(kinds=(1, 2))
            save()
        if not checkpoint.get("active_done"):
            rows = sorted(checkpoint["active"], key=lambda row: row["start_time"], reverse=True)
            while checkpoint.get("active_index", 0) < len(rows):
                index = checkpoint.get("active_index", 0)
                if rows[index].get("item_count") != 0:
                    yield rows[index]
                checkpoint["active_index"] = index + 1
                save()
            checkpoint["active_done"] = True
            save()
        while checkpoint.get("offset", 0) < 1000:
            offset = checkpoint.get("offset", 0)
            if "page" not in checkpoint:
                data = self.call("get_shop_flash_sale_list", query={"type": 3, "offset": offset, "limit": 100})
                total = data.get("total_count")
                page = data.get("flash_sale_list")
                if page is None and total == 0:
                    page = []
                if type(total) is not int or total < 0 or not isinstance(page, list) or offset + len(page) > total or (not page and offset < total):
                    raise Deferred("来源活动分页不完整")
                if offset and total != checkpoint.get("total"):
                    checkpoint.update(offset=0)
                    save()
                    raise Deferred("来源活动列表已变化，重新读取近期历史")
                checkpoint.update(page=sorted(page, key=lambda row: row["start_time"], reverse=True), index=0, total=total)
                save()
            page = checkpoint["page"]
            while checkpoint["index"] < len(page):
                row = page[checkpoint["index"]]
                if row.get("item_count") != 0:
                    yield row
                checkpoint["index"] += 1
                save()
            checkpoint["offset"] = offset + len(page)
            del checkpoint["page"]
            save()
            if checkpoint["offset"] >= checkpoint["total"]:
                return
        raise ValidationError("最近 1000 场历史活动没有可用来源，请手动选择来源活动。")

    def items(self, activity_id):
        rows, models, offset = [], [], 0
        expected = None
        while True:
            data = self._read_page("get_shop_flash_sale_items", {"flash_sale_id": int(activity_id), "offset": offset, "limit": 100})
            page, total = data.get("item_info"), data.get("total_count")
            if (not isinstance(page, list) or type(total) is not int or offset + len(page) > total
                    or (expected is not None and total != expected)):
                self._clear_read_checkpoint()
                raise Deferred("活动商品分页结果不完整")
            expected = total
            rows.extend(page)
            models.extend(data.get("models") or [])
            offset += len(page)
            if offset == total:
                result = normalize_items(rows, models)
                self._clear_read_checkpoint(digest({"endpoint": "get_shop_flash_sale_items",
                    "flash_sale_id": int(activity_id), "limit": 100}))
                return result
            if not page or offset > 100000:
                raise Deferred("活动商品分页未完成")

    def slots(self):
        now = int(time.time())
        return self.call("get_time_slot_id", query={"start_time": now + 600, "end_time": now + 3 * 86400})

    def detail(self, activity_id):
        try:
            detail = self.call("get_shop_flash_sale", query={"flash_sale_id": int(activity_id)})
            if not isinstance(detail, dict) or any(key not in detail for key in ("timeslot_id", "start_time", "end_time", "status")):
                raise UnknownWrite("活动详情不完整，不能据此确认不存在或清理成功")
            return detail
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
