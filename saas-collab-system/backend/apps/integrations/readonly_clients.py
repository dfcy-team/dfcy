import copy
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, ValidationError

from apps.common.module_gate import is_module_enabled

from .capability import require_live_mode
from .custody import get_custody_backend
from .live_providers import _lazada_sign
from .net_guard import PlatformHttpClient
from .oauth_errors import OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError
from .production_settings import get_runtime_platform_config, get_runtime_setting


class ReadonlyConfigurationError(ValidationError):
    """A missing approved configuration cannot be repaired by retrying."""

    default_code = "SYNC_CONFIGURATION_MISSING"


def _draft_epoch_seconds(value):
    if type(value) is int:
        seconds = value
    elif isinstance(value, str) and 1 <= len(value) <= 12 and value.isascii() and value.isdecimal():
        seconds = int(value)
    else:
        raise ValidationError("TikTok draft product has invalid update_time.")
    if not 0 < seconds <= 253402300799:
        raise ValidationError("TikTok draft product has invalid update_time.")
    return seconds


def _required(value, name):
    text = str(value or "").strip()
    if not text or text.startswith("REPLACE_ME"):
        raise ValidationError(f"Approved live configuration is missing: {name}.")
    return text


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _status_values(value):
    """Normalize a job status filter without inventing provider semantics."""

    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip().upper() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    raise ValidationError("Product status filter must be text or a list of text values.")


def _text(*values):
    """Return the first present scalar without coercing missing values."""
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _shopee_variant_label(model, tier_variations):
    """Render Shopee model tier indexes using the documented tier shape."""
    indexes = model.get("tier_index") if isinstance(model.get("tier_index"), list) else []
    labels = []
    for index, tier in enumerate(tier_variations):
        if not isinstance(tier, dict) or index >= len(indexes):
            continue
        options = tier.get("option_list") if isinstance(tier.get("option_list"), list) else []
        option_index = indexes[index]
        try:
            option = options[int(option_index)]
        except (IndexError, TypeError, ValueError):
            continue
        if not isinstance(option, dict):
            continue
        name = _text(tier.get("name"))
        value = _text(option.get("option"))
        if name and value:
            labels.append(f"{name}={value}")
        elif value:
            labels.append(value)
    return " / ".join(labels)


def _tiktok_variant_label(attributes):
    """Render TikTok sales attributes without relying on optional IDs."""
    if not isinstance(attributes, list):
        return ""
    labels = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        name = _text(attribute.get("name"), attribute.get("id"))
        value = _text(attribute.get("value_name"), attribute.get("value_id"))
        if name and value:
            labels.append(f"{name}={value}")
        elif value:
            labels.append(value)
    return " / ".join(labels)


def _query_url(host, path, query):
    return f"{host.rstrip('/')}{path}?{urllib.parse.urlencode(query, doseq=True)}"


def _time_window(cursor, scope, maximum_days):
    overall_start = int(scope["time_from"])
    overall_end = int(scope["time_to"])
    maximum_seconds = int(maximum_days) * 86400
    windowed = overall_end - overall_start + 1 > maximum_seconds
    window_start = overall_start
    provider_cursor = str(cursor or "")
    if windowed and provider_cursor.startswith("tw:"):
        _, raw_start, encoded_cursor = provider_cursor.split(":", 2)
        window_start = int(raw_start)
        provider_cursor = urllib.parse.unquote(encoded_cursor)
    window_end = min(overall_end, window_start + maximum_seconds - 1)
    return window_start, window_end, provider_cursor, windowed


def _unwrap_shopee_detail_cursor(cursor, scope, resource, page_size):
    cursor = str(cursor or "")
    if not cursor.startswith("sd1:"):
        return cursor
    state = scope.get("_detail_state")
    if scope.get("_history_details") is not True or not isinstance(state, dict):
        raise ValidationError("Shopee history detail cursor requires its checkpoint state.")
    parts = cursor.split(":")
    if len(parts) != 4 or not parts[1].isascii() or not parts[1].isdecimal() or not parts[3].isascii() or not parts[3].isdecimal():
        raise ValidationError("Shopee history detail cursor is damaged.")
    _, raw_window_start, raw_provider_cursor, raw_index = parts
    if raw_provider_cursor and (not raw_provider_cursor.isascii() or not raw_provider_cursor.isdecimal()):
        raise ValidationError("Shopee history detail cursor is damaged.")
    window_start = int(raw_window_start)
    next_index = int(raw_index)
    fingerprint = ShopeeReadonlyClient._detail_scope_fingerprint(scope, resource, page_size)
    if (
        state.get("version") != ShopeeReadonlyClient.DETAIL_CHECKPOINT_VERSION
        or state.get("resource") != resource
        or state.get("scope") != fingerprint
        or state.get("page_cursor") != raw_provider_cursor
        or state.get("window_start") != window_start
        or state.get("next_index") != next_index
    ):
        raise ValidationError("Shopee history detail cursor does not match its checkpoint.")
    windowed = int(scope["time_to"]) - int(scope["time_from"]) + 1 > 15 * 86400
    if windowed:
        return f"tw:{window_start}:{urllib.parse.quote(raw_provider_cursor, safe='')}"
    if window_start != int(scope["time_from"]):
        raise ValidationError("Shopee history detail cursor does not match the current time window.")
    return raw_provider_cursor


def _next_time_window_cursor(scope, window_start, window_end, provider_cursor, windowed):
    provider_cursor = str(provider_cursor or "")
    if not windowed:
        return provider_cursor
    if provider_cursor:
        return f"tw:{window_start}:{urllib.parse.quote(provider_cursor, safe='')}"
    if window_end < int(scope["time_to"]):
        return f"tw:{window_end + 1}:"
    return ""


LAZADA_API_HOSTS = {
    "SG": "https://api.lazada.sg",
    "TH": "https://api.lazada.co.th",
    "MY": "https://api.lazada.com.my",
    "VN": "https://api.lazada.vn",
    "PH": "https://api.lazada.com.ph",
    "ID": "https://api.lazada.co.id",
}


def _lazada_api_host(region, configured_host):
    return LAZADA_API_HOSTS.get(str(region or "").upper(), configured_host).rstrip("/")


class ReadonlyClientBase:
    def __init__(self, config, authorization=None, http_client=None, custody=None, now=None):
        self.config = config
        self.authorization = authorization
        # The same platform client serves multiple read-only resources.  The
        # adapter sets this before preflight so product contracts cannot be
        # inferred from an older order/return approval.
        self.resource_type = None
        self.platform_config = dict(config.platform_config or {})
        self.http = http_client or PlatformHttpClient()
        self.custody = custody or get_custody_backend()
        self.now = now or timezone.now

    def _runtime_path(self, key, fallback):
        value = (get_runtime_platform_config(str(getattr(self.config, "platform", "") or "").lower()) or {}).get(key)
        return str(value or fallback)

    def preflight(self):
        if getattr(self.authorization, "last_error_code", "") in {
            "AUTO_REFRESH_VALIDATION_PENDING", "AUTO_REFRESH_VALIDATION_FAILED",
        }:
            raise ValidationError("新令牌尚未通过只读验证，请先重新验证新令牌；不要重复刷新。")
        if not is_module_enabled("api_integrations"):
            raise ValidationError("API data integration module is disabled.")
        require_live_mode(f"{self.config.platform} readonly synchronization")
        if not get_runtime_setting("network", "readonly_sync_enabled", default=False):
            raise ValidationError("系统尚未启用真实只读同步，请在生产环境配置中完成只读同步审批。")
        if self.config.environment not in {"pilot", "production"}:
            raise ValidationError("Readonly production synchronization requires pilot or production environment.")
        if self.config.status not in {"verified", "active"}:
            raise ValidationError("Integration config is not verified and active.")
        if self.config.platform == "jifeng_wms":
            from .readiness_service import BLOCKER_LABELS
            from .warehouse_readiness import warehouse_config_blockers

            labels = {**BLOCKER_LABELS, "network_not_approved": "网络访问未审批",
                "platform_contract_not_enabled": "接口合同未确认"}
            blockers = [labels[code] for code in warehouse_config_blockers(self.config)]
            if blockers:
                raise ValidationError({"detail": "极风接入配置尚未就绪：" + "、".join(blockers)
                    + "。请联系接入配置管理员完成审批后重试；本次未调用极风接口。"})
            return
        if not self.config.network_enabled or not self.config.sync_read_enabled:
            raise ValidationError("Integration config readonly network capability is disabled.")
        contract_key = (
            "affiliate_seller_creator_read_approved" if self.resource_type == "affiliate_creator_profile"
            else "product_contract_approved" if self.resource_type == "platform_product"
            else "contract_approved"
        )
        # Shopee and TikTok use the versioned production approvals.
        # Tenant credential metadata must not shadow or grant that approval.
        # Other providers retain their existing order/return contract policy.
        approval_config = (
            get_runtime_platform_config(str(getattr(self.config, "platform", "") or "").lower())
            if contract_key == "product_contract_approved" or self.config.platform in {"lazada", "shopee", "tiktok"}
            else self.platform_config
        )
        if not approval_config.get(contract_key):
            if contract_key == "affiliate_seller_creator_read_approved":
                raise ValidationError("TikTok Affiliate seller creator lookup is not approved.")
            if contract_key == "product_contract_approved":
                raise ValidationError("Platform product readonly contract is not approved.")
            raise ValidationError("Platform readonly contract is not approved.")
        if self.config.sync_write_enabled:
            raise ValidationError("Readonly synchronization refuses configs with write capability enabled.")

    def _response_json(self, response):
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValidationError("Platform returned an invalid JSON response.") from exc
        if not isinstance(payload, dict):
            raise ValidationError("Platform returned an invalid response envelope.")
        return payload


class LazadaReadonlyClient(ReadonlyClientBase):
    ORDER_LIST_PATH = "/rest/orders/get"
    ORDER_ITEMS_PATH = "/rest/order/items/get"
    RETURN_LIST_PATH = settings.LIVE_LAZADA_RETURN_LIST_PATH
    FINANCE_TRANSACTION_PATH = "/rest/finance/transaction/details/get"

    def _request(self, path, query):
        self.preflight()
        authorization = self.authorization
        if authorization is None or authorization.status != authorization.Status.ACTIVE:
            raise ValidationError("Lazada store authorization is not active.")
        if authorization.expires_at and authorization.expires_at <= self.now():
            raise ValidationError("LAZADA_TOKEN_REFRESH_REQUIRED")
        runtime = get_runtime_platform_config("lazada")
        host = _lazada_api_host(
            authorization.region,
            _required(runtime.get("api_host"), "lazada.api_host"),
        )
        app_key = _required(runtime.get("app_id"), "lazada.app_id")
        secret_reference = self.config.credential_id or self.platform_config.get("app_secret_reference")
        app_secret = self.custody.retrieve_secret(_required(secret_reference, "lazada.app_secret_reference"))
        access_token = self.custody.retrieve_access_token(authorization.token_id)
        params = {
            "app_key": app_key,
            "access_token": access_token,
            "sign_method": "sha256",
            "timestamp": int(self.now().timestamp() * 1000),
            **query,
        }
        params["sign"] = _lazada_sign(path, params, app_secret)
        response = self.http.request(
            "GET",
            _query_url(host, path, params),
            connect_timeout=self.config.connect_timeout_seconds,
            read_timeout=self.config.read_timeout_seconds,
            diagnostic_platform="lazada",
        )
        payload = self._response_json(response)
        if payload.get("error") or payload.get("code") not in {None, 0, "0"}:
            raise ValidationError("Lazada rejected the readonly request.")
        return payload

    @staticmethod
    def _time(value):
        return datetime.fromtimestamp(int(value), tz=UTC).isoformat(timespec="seconds")

    def _finance_date(self, value):
        timezone_name = getattr(getattr(self.authorization, "store", None), "timezone", "")
        try:
            zone = ZoneInfo(timezone_name or "Asia/Shanghai")
        except ZoneInfoNotFoundError:
            zone = UTC
        return datetime.fromtimestamp(int(value), tz=UTC).astimezone(zone).date().isoformat()

    def validate_token(self):
        """Use one order-list page to prove the refreshed token is readable."""
        path = self._runtime_path("order_list_path", self.ORDER_LIST_PATH)
        now = int(self.now().timestamp())
        payload = self._request(path, {
            "update_after": self._time(now - 3600),
            "update_before": self._time(now),
            "limit": 1,
            "offset": 0,
            "sort_direction": "ASC",
        })
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
            raise ValidationError("Lazada refreshed token readonly validation returned an invalid response.")
        return {"validated": True}

    @staticmethod
    def _page(data, key, offset, page_size):
        records = _as_list(data.get(key))
        total = data.get("countTotal", data.get("count_total", data.get("total")))
        try:
            has_more = int(offset) + len(records) < int(total)
        except (TypeError, ValueError):
            has_more = len(records) == int(page_size)
        return records, str(int(offset) + len(records)) if records and has_more else ""

    def fetch_orders(self, cursor, scope):
        list_path = self._runtime_path("order_list_path", self.ORDER_LIST_PATH)
        items_path = self._runtime_path("order_items_path", self.ORDER_ITEMS_PATH)
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 30)
        offset = int(provider_cursor or 0)
        time_prefix = "created" if scope.get("time_basis") == "created" else "update"
        response = self._request(
            list_path,
            {
                f"{time_prefix}_after": self._time(time_from),
                f"{time_prefix}_before": self._time(time_to),
                "limit": scope["page_size"],
                "offset": offset,
                "sort_direction": "ASC",
            },
        )
        data = _as_dict(response.get("data"))
        orders, provider_next_cursor = self._page(data, "orders", offset, scope["page_size"])
        next_cursor = _next_time_window_cursor(
            scope, time_from, time_to, provider_next_cursor, windowed
        )
        raw_responses = [{"endpoint": list_path, "payload": response}]
        records = []
        valid_orders = [order for order in orders if isinstance(order, dict) and order.get("order_id")]

        def fetch_items(order):
            for attempt in range(2):
                try:
                    return self._request(items_path, {"order_id": order["order_id"]})
                except OAuthFlowError as exc:
                    if exc.controlled_code != OAUTH_PROVIDER_UNAVAILABLE or attempt:
                        raise
                    time.sleep(1)

        with ThreadPoolExecutor(max_workers=min(8, max(1, len(valid_orders)))) as executor:
            details = list(executor.map(fetch_items, valid_orders))
        for order, detail in zip(valid_orders, details):
            raw_responses.append({"endpoint": items_path, "payload": detail})
            detail_data = detail.get("data")
            if isinstance(detail_data, dict):
                items = next(
                    (_as_list(detail_data.get(key)) for key in ("order_items", "items") if key in detail_data),
                    [],
                )
            else:
                items = _as_list(detail_data)
            records.append({**order, "order_items": items})
        return {"records": records, "next_cursor": next_cursor, "raw_responses": raw_responses}

    def fetch_returns(self, cursor, scope):
        path = self._runtime_path("return_list_path", self.RETURN_LIST_PATH)
        page_no = max(1, int(cursor or 1))
        page_size = min(100, max(1, int(scope["page_size"])))
        response = self._request(path, {"page_size": page_size, "page_no": page_no})
        result = _as_dict(response.get("result"))
        if result.get("success") is False:
            raise ValidationError("Lazada rejected the reverse-order request.")
        items = _as_list(result.get("items"))
        time_from = int(scope.get("time_from") or 0)
        time_to = int(scope.get("time_to") or 0)

        def in_scope(record):
            timestamps = []
            for line in _as_list(record.get("reverse_order_lines")):
                if not isinstance(line, dict):
                    continue
                for key in ("return_order_line_gmt_modified", "return_order_line_gmt_create"):
                    try:
                        timestamps.append(int(line.get(key)))
                    except (TypeError, ValueError):
                        pass
            return bool(timestamps) and any(
                (not time_from or value >= time_from) and (not time_to or value <= time_to)
                for value in timestamps
            )

        records = [item for item in items if isinstance(item, dict) and in_scope(item)]
        try:
            total = int(result.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        next_cursor = str(page_no + 1) if page_no * page_size < total else ""
        return {
            "records": records,
            "next_cursor": next_cursor,
            "raw_responses": [{"endpoint": path, "payload": response}],
        }

    def fetch_finance_transactions(self, cursor, scope):
        path = self._runtime_path("finance_transaction_path", self.FINANCE_TRANSACTION_PATH)
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 15)
        offset = int(provider_cursor or 0)
        response = self._request(
            path,
            {
                "start_time": self._finance_date(time_from),
                "end_time": self._finance_date(time_to),
                "limit": scope["page_size"],
                "offset": offset,
            },
        )
        data = response.get("data")
        if isinstance(data, list):
            envelope = {"transactions": data}
        else:
            envelope = _as_dict(data)
        key = next(
            (name for name in ("transactions", "transaction_details", "details") if isinstance(envelope.get(name), list)),
            "transactions",
        )
        records, provider_next_cursor = self._page(envelope, key, offset, scope["page_size"])
        next_cursor = _next_time_window_cursor(
            scope, time_from, time_to, provider_next_cursor, windowed
        )
        return {
            "records": records,
            "next_cursor": next_cursor,
            "raw_responses": [{"endpoint": path, "payload": response}],
        }


class ShopeeReadonlyClient(ReadonlyClientBase):
    READONLY_POST_PATHS = frozenset({
        "/api/v2/ads/get_gms_campaign_performance", "/api/v2/ads/get_gms_item_performance",
    })
    ORDER_LIST_PATH = settings.LIVE_SHOPEE_ORDER_LIST_PATH
    ORDER_DETAIL_PATH = settings.LIVE_SHOPEE_ORDER_DETAIL_PATH
    RETURN_LIST_PATH = settings.LIVE_SHOPEE_RETURN_LIST_PATH
    RETURN_DETAIL_PATH = settings.LIVE_SHOPEE_RETURN_DETAIL_PATH
    PRODUCT_LIST_PATH = settings.LIVE_SHOPEE_PRODUCT_LIST_PATH
    PRODUCT_BASE_INFO_PATH = settings.LIVE_SHOPEE_PRODUCT_BASE_INFO_PATH
    PRODUCT_MODEL_LIST_PATH = settings.LIVE_SHOPEE_PRODUCT_MODEL_LIST_PATH
    FINANCE_LIST_PATH = settings.LIVE_SHOPEE_FINANCE_LIST_PATH
    FINANCE_DETAIL_PATH = settings.LIVE_SHOPEE_FINANCE_DETAIL_PATH
    # The current production contract is intentionally conservative.  The
    # official Shopee product-list contract has not been accepted in the
    # runtime catalogue yet, so NORMAL is the only status we expose through
    # the job policy.  Other values fail closed instead of being advertised as
    # supported without a verified contract.
    SUPPORTED_PRODUCT_ITEM_STATUSES = frozenset({"NORMAL"})

    DETAIL_CHECKPOINT_VERSION = 1
    DETAIL_BATCH_SIZE = 4
    DETAIL_STATE_MAX_BYTES = 131072
    DETAIL_SUMMARY_FIELDS = {
        "returns": (
            "return_sn", "return_id", "order_sn", "order_id", "return_type", "solution",
            "status", "return_status", "refund_id", "negotiation_status", "arbitration_status",
            "return_reason", "create_time", "update_time", "complete_time", "refund_time",
            "currency", "refund_amount", "refund_total", "refund_subtotal", "refund_shipping_fee",
            "refund_tax", "is_partial_quantity_return", "is_refund_amount_adjusted",
            "item", "item_list", "return_item_list", "return_items",
        ),
        "finance_transactions": (
            "order_sn", "order_id", "currency", "escrow_release_time", "release_time",
        ),
    }

    @staticmethod
    def _detail_page_size(scope, resource):
        try:
            configured_size = int(scope["page_size"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError("Shopee history page size is invalid.")
        if configured_size < 1 or (resource == "returns" and configured_size > 100):
            raise ValidationError("Shopee history page size is invalid.")
        # Keep the pre-existing provider limit for finance requests.
        return min(100, configured_size) if resource == "finance_transactions" else configured_size

    @staticmethod
    def _detail_scope_fingerprint(scope, resource, page_size):
        fingerprint_data = {
            "resource": resource,
            "page_size": page_size,
            "time_from": str(scope.get("time_from", "")),
            "time_to": str(scope.get("time_to", "")),
        }
        canonical = json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _safe_detail_summary(cls, item, resource):
        allowed = cls.DETAIL_SUMMARY_FIELDS[resource]
        scalar = lambda value: value is None or type(value) in (str, int, float, bool) and (not isinstance(value, str) or len(value) <= 512)
        summary = {}
        if resource == "returns":
            item_fields = {
                "return_item_id", "line_id", "order_item_id", "item_id", "model_id", "model_sku",
                "item_sku", "item_name", "name", "amount", "quantity", "refund_amount", "amount_refunded",
            }
            for key in ("item", "item_list", "return_item_list", "return_items"):
                if isinstance(item.get(key), list):
                    summary[key] = [
                        {field: value[field] for field in item_fields if field in value and scalar(value[field])}
                        for value in item[key]
                        if isinstance(value, dict) and any(field in value and scalar(value[field]) for field in item_fields)
                    ]
            for key in ("refund_amount", "refund_total", "refund_subtotal", "refund_shipping_fee", "refund_tax"):
                if isinstance(item.get(key), dict):
                    summary[key] = {
                        field: item[key][field]
                        for field in ("amount", "value", "currency")
                        if field in item[key] and scalar(item[key][field])
                    }
        for key in allowed:
            value = item.get(key)
            if key not in summary and scalar(value):
                summary[key] = value
        summary_id = _text(summary.get("return_sn"), summary.get("return_id")) if resource == "returns" else _text(
            summary.get("order_sn"), summary.get("order_id")
        )
        summary["_detail_id"] = summary_id
        return summary

    @classmethod
    def _is_safe_detail_summary(cls, summary, resource):
        allowed = set(cls.DETAIL_SUMMARY_FIELDS[resource]) | {"_detail_id"}
        if not isinstance(summary, dict) or set(summary) - allowed:
            return False
        item_fields = {
            "return_item_id", "line_id", "order_item_id", "item_id", "model_id", "model_sku",
            "item_sku", "item_name", "name", "amount", "quantity", "refund_amount", "amount_refunded",
        }
        money_fields = {"amount", "value", "currency"}

        def scalar(value):
            return value is None or type(value) in (str, int, float, bool) and (not isinstance(value, str) or len(value) <= 512)

        for key, value in summary.items():
            if key == "_detail_id":
                if not isinstance(value, str) or not value or len(value) > 512:
                    return False
            elif resource == "returns" and key in {"item", "item_list", "return_item_list", "return_items"} and isinstance(value, list):
                if not isinstance(value, list) or any(
                    not isinstance(entry, dict)
                    or set(entry) - item_fields
                    or not all(scalar(item_value) for item_value in entry.values())
                    for entry in value
                ):
                    return False
            elif resource == "returns" and key in {"refund_amount", "refund_total", "refund_subtotal", "refund_shipping_fee", "refund_tax"} and isinstance(value, dict):
                if set(value) - money_fields or not all(scalar(item_value) for item_value in value.values()):
                    return False
            elif not scalar(value):
                return False
        return True

    def _detail_checkpoint(self, scope, resource, provider_cursor, page_size, summaries, window_start):
        if scope.get("_history_details") is not True:
            return None
        state = scope.get("_detail_state")
        fingerprint = self._detail_scope_fingerprint(scope, resource, page_size)
        if state in (None, {}):
            return {
                "version": self.DETAIL_CHECKPOINT_VERSION,
                "resource": resource,
                "scope": fingerprint,
                "page_cursor": str(provider_cursor or ""),
                "window_start": int(window_start),
                "summaries": [self._safe_detail_summary(item, resource) for item in summaries],
                "next_index": 0,
                "next_cursor": "",
                "has_more": False,
            }
        if not isinstance(state, dict):
            raise ValidationError("Shopee history detail checkpoint is invalid.")
        state = copy.deepcopy(state)
        expected_state_fields = {
            "version", "resource", "scope", "page_cursor", "window_start", "summaries",
            "next_index", "next_cursor", "has_more",
        }
        if (
            set(state) != expected_state_fields
            or state.get("version") != self.DETAIL_CHECKPOINT_VERSION
            or state.get("resource") != resource
            or state.get("scope") != fingerprint
            or state.get("page_cursor") != str(provider_cursor or "")
            or type(state.get("window_start")) is not int
            or state.get("window_start") != int(window_start)
        ):
            raise ValidationError("Shopee history detail checkpoint does not match the current page scope.")
        frozen = state.get("summaries")
        next_index = state.get("next_index")
        if (
            not isinstance(frozen, list)
            or len(frozen) > page_size
            or type(next_index) is not int
            or not 0 <= next_index <= len(frozen)
            or any(
                not self._is_safe_detail_summary(item, resource)
                for item in frozen
            )
            or len({item["_detail_id"] for item in frozen}) != len(frozen)
            or (state.get("page_cursor") and (not state["page_cursor"].isascii() or not state["page_cursor"].isdecimal()))
            or not isinstance(state.get("next_cursor"), str)
            or (state["next_cursor"] and (not state["next_cursor"].isascii() or not state["next_cursor"].isdecimal()))
            or type(state.get("has_more")) is not bool
        ):
            raise ValidationError("Shopee history detail checkpoint is damaged.")
        self._check_detail_checkpoint_size(state)
        return state

    def _check_detail_checkpoint_size(self, state):
        try:
            size = len(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            raise ValidationError("Shopee history detail checkpoint is damaged.")
        if size > self.DETAIL_STATE_MAX_BYTES:
            raise ValidationError("Shopee history detail checkpoint exceeds the supported size.")

    def _detail_cursor(self, time_from, provider_cursor, next_index):
        cursor = f"sd1:{int(time_from)}:{str(provider_cursor or '')}:{int(next_index)}"
        if len(cursor) >= 255:
            raise ValidationError("Shopee history detail cursor exceeds the supported length.")
        return cursor

    def _detail_slice(self, state):
        start = state["next_index"]
        end = min(len(state["summaries"]), start + self.DETAIL_BATCH_SIZE)
        return state["summaries"][start:end], end

    def _request(self, path, query, *, readonly_body=None):
        if readonly_body is not None and path not in self.READONLY_POST_PATHS:
            raise ValidationError("Shopee readonly POST endpoint is not allowed.")
        self.preflight()
        authorization = self.authorization
        if authorization is None or authorization.status != authorization.Status.ACTIVE:
            raise ValidationError("Shopee store authorization is not active.")
        if authorization.expires_at and authorization.expires_at <= self.now():
            raise ValidationError("SHOPEE_TOKEN_REFRESH_REQUIRED")
        host = _required(get_runtime_platform_config("shopee").get("api_host"), "shopee.api_host").rstrip("/")
        partner_id = _required(self.platform_config.get("partner_id"), "shopee.partner_id")
        secret_reference = self.config.credential_id or self.platform_config.get("app_secret_reference")
        partner_key = self.custody.retrieve_secret(_required(secret_reference, "shopee.app_secret_reference"))
        access_token = self.custody.retrieve_access_token(authorization.token_id)
        timestamp = int(self.now().timestamp())
        base = f"{partner_id}{path}{timestamp}{access_token}{authorization.platform_store_id}"
        signed = {
            "partner_id": partner_id,
            "timestamp": timestamp,
            "access_token": access_token,
            "shop_id": authorization.platform_store_id,
            "sign": hmac.new(partner_key.encode(), base.encode(), hashlib.sha256).hexdigest(),
            **query,
        }
        response = self.http.request(
            "POST" if readonly_body is not None else "GET",
            _query_url(host, path, signed),
            **({"json_body": readonly_body} if readonly_body is not None else {}),
            connect_timeout=self.config.connect_timeout_seconds,
            read_timeout=self.config.read_timeout_seconds,
        )
        payload = self._response_json(response)
        if payload.get("error"):
            raise ValidationError("Shopee rejected the readonly request.")
        return payload

    def _refund_request(self, path, query, *, stage, page_no, page_size):
        started_at = time.monotonic()
        try:
            return self._request(path, query)
        except OAuthFlowError as exc:
            elapsed_ms = max(0, int((time.monotonic() - started_at) * 1000))
            controlled_code = exc.controlled_code
            reason = {
                "timeout_uncertain": "Shopee refund request timed out",
                "tls_failure": "Shopee refund request failed during TLS setup",
                "network_uncertain": "Shopee refund request failed due to a network issue",
            }.get(getattr(exc, "category", None), "Shopee refund request failed")
            # Keep the original exception and its retry/category metadata while
            # replacing any provider-derived text with fixed safe diagnostics.
            message = (
                f"{controlled_code}: {reason}; stage={stage}; page_no={page_no}; "
                f"page_size={page_size}; elapsed_ms={elapsed_ms}"
            )
            original_detail_code = getattr(exc.detail, "code", exc.error_code)
            exc.detail = ErrorDetail(message, code=original_detail_code)
            exc.args = (message,)
            raise

    def fetch_orders(self, cursor, scope):
        order_list_path = self._runtime_path("order_list_path", self.ORDER_LIST_PATH)
        order_detail_path = self._runtime_path("order_detail_path", self.ORDER_DETAIL_PATH)
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 15)
        response = self._request(
            order_list_path,
            {
                "time_range_field": "create_time" if scope.get("time_basis") == "created" else "update_time",
                "time_from": time_from,
                "time_to": time_to,
                "page_size": scope["page_size"],
                **({"cursor": provider_cursor} if provider_cursor else {}),
                "response_optional_fields": "order_status",
            },
        )
        envelope = _as_dict(response.get("response"))
        raw_responses = [{"endpoint": order_list_path, "payload": response}]
        summaries = _as_list(envelope.get("order_list"))
        order_ids = [str(item.get("order_sn")) for item in summaries if isinstance(item, dict) and item.get("order_sn")]
        details = []
        order_batches = [order_ids[start : start + 50] for start in range(0, len(order_ids), 50)]

        def fetch_order_batch(order_batch):
            return self._request(
                order_detail_path,
                {
                    "order_sn_list": ",".join(order_batch),
                    "response_optional_fields": "item_list,payment_method,total_amount,shipping_carrier,package_list",
                },
            )

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(order_batches)))) as executor:
            detail_responses = list(executor.map(fetch_order_batch, order_batches))
        for detail in detail_responses:
            raw_responses.append({"endpoint": order_detail_path, "payload": detail})
            details.extend(_as_list(_as_dict(detail.get("response")).get("order_list")))
        return {
            "records": details or summaries,
            "next_cursor": _next_time_window_cursor(
                scope, time_from, time_to, envelope.get("next_cursor"), windowed
            ),
            "raw_responses": raw_responses,
        }

    def fetch_returns(self, cursor, scope):
        return_list_path = self._runtime_path("return_list_path", self.RETURN_LIST_PATH)
        return_detail_path = self._runtime_path("return_detail_path", self.RETURN_DETAIL_PATH)
        history_details = scope.get("_history_details") is True
        page_size = self._detail_page_size(scope, "returns") if history_details else scope["page_size"]
        cursor_input = _unwrap_shopee_detail_cursor(cursor, scope, "returns", page_size) if history_details else cursor
        time_from, time_to, provider_cursor, windowed = _time_window(cursor_input, scope, 15)
        page_no = int(provider_cursor or 0)
        checkpoint = self._detail_checkpoint(scope, "returns", provider_cursor, page_size, [], time_from) if history_details else None
        if checkpoint is not None and scope.get("_detail_state"):
            summaries = checkpoint["summaries"]
            raw_responses = []
            has_more = checkpoint["has_more"]
            next_provider_cursor = checkpoint["next_cursor"]
        else:
            response = self._refund_request(
                return_list_path,
                {
                    "create_time_from": time_from,
                    "create_time_to": time_to,
                    "page_no": page_no,
                    "page_size": page_size,
                },
                stage="list",
                page_no=page_no,
                page_size=page_size,
            )
            envelope = _as_dict(response.get("response"))
            raw_responses = [{"endpoint": return_list_path, "payload": response}]
            summaries = _as_list(envelope.get("return")) or _as_list(envelope.get("return_list"))
            if history_details and len(summaries) > page_size:
                raise ValidationError("Shopee return list exceeded the requested page size.")
            has_more = bool(envelope.get("more") or envelope.get("has_more"))
            next_provider_cursor = str(page_no + 1) if has_more else ""
            if checkpoint is not None:
                checkpoint["summaries"] = [
                    self._safe_detail_summary(item, "returns")
                    for item in summaries
                    if isinstance(item, dict) and (item.get("return_sn") or item.get("return_id"))
                ]
                checkpoint["next_cursor"] = next_provider_cursor
                checkpoint["has_more"] = has_more
        valid_returns = [
            (item, item.get("_detail_id") if history_details and checkpoint is not None else item.get("return_sn") or item.get("return_id"))
            for item in summaries
            if isinstance(item, dict) and (
                (item.get("_detail_id") if history_details and checkpoint is not None else item.get("return_sn") or item.get("return_id"))
            )
        ]

        def fetch_return_detail(item_and_id):
            _item, return_id = item_and_id
            return self._refund_request(
                return_detail_path,
                {"return_sn": return_id},
                stage="detail",
                page_no=page_no,
                page_size=page_size,
            )

        if history_details and checkpoint is not None:
            current_batch, next_index = self._detail_slice(checkpoint)
            batch = [(item, item["_detail_id"]) for item in current_batch]
        else:
            batch = valid_returns
            next_index = len(batch)
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(batch)))) as executor:
            detail_responses = list(executor.map(fetch_return_detail, batch))
        details = []
        for (item, _return_id), detail in zip(batch, detail_responses):
            raw_responses.append({"endpoint": return_detail_path, "payload": detail})
            detail_record = _as_dict(detail.get("response"))
            details.append({**item, **detail_record})
        if history_details and checkpoint is not None:
            checkpoint["next_index"] = next_index
            remaining = next_index < len(checkpoint["summaries"])
            if remaining:
                self._check_detail_checkpoint_size(checkpoint)
                next_cursor = self._detail_cursor(time_from, provider_cursor, next_index)
                detail_state = checkpoint
            else:
                next_cursor = _next_time_window_cursor(scope, time_from, time_to, next_provider_cursor, windowed)
                detail_state = {}
            if not checkpoint["summaries"]:
                next_cursor = _next_time_window_cursor(scope, time_from, time_to, next_provider_cursor, windowed)
                detail_state = {}
            return {
                "records": details or summaries,
                "next_cursor": next_cursor,
                "raw_responses": raw_responses,
                "detail_state": detail_state,
                "detail_progress": {
                    "completed_in_page": next_index,
                    "remaining_in_page": max(0, len(checkpoint["summaries"]) - next_index),
                    "requests_in_slice": len(batch),
                },
            }
        return {
            "records": details or summaries,
            "next_cursor": _next_time_window_cursor(
                scope, time_from, time_to, str(page_no + 1) if has_more else "", windowed
            ),
            "raw_responses": raw_responses,
        }

    def fetch_finance_transactions(self, cursor, scope):
        list_path = self._runtime_path("finance_list_path", self.FINANCE_LIST_PATH)
        detail_path = self._runtime_path("finance_detail_path", self.FINANCE_DETAIL_PATH)
        history_details = scope.get("_history_details") is True
        page_size = self._detail_page_size(scope, "finance_transactions") if history_details else min(100, int(scope["page_size"]))
        cursor_input = _unwrap_shopee_detail_cursor(cursor, scope, "finance_transactions", page_size) if history_details else cursor
        time_from, time_to, provider_cursor, windowed = _time_window(cursor_input, scope, 15)
        page_no = max(1, int(provider_cursor or 1))
        checkpoint = self._detail_checkpoint(scope, "finance_transactions", provider_cursor, page_size, [], time_from) if history_details else None
        if checkpoint is not None and scope.get("_detail_state"):
            summaries = checkpoint["summaries"]
            raw_responses = []
            has_more = checkpoint["has_more"]
            next_provider_cursor = checkpoint["next_cursor"]
        else:
            response = self._request(
                list_path,
                {
                    "release_time_from": time_from,
                    "release_time_to": time_to,
                    "page_size": page_size,
                    "page_no": page_no,
                },
            )
            envelope = _as_dict(response.get("response"))
            summaries = _as_list(envelope.get("order_income_list")) or _as_list(envelope.get("escrow_list"))
            if history_details and len(summaries) > page_size:
                raise ValidationError("Shopee finance list exceeded the requested page size.")
            has_more = bool(envelope.get("more") or envelope.get("has_more"))
            next_provider_cursor = str(page_no + 1) if has_more else ""
            raw_responses = [{"endpoint": list_path, "payload": response}]
            if checkpoint is not None:
                checkpoint["summaries"] = [
                    self._safe_detail_summary(item, "finance_transactions")
                    for item in summaries
                    if isinstance(item, dict) and _text(item.get("order_sn"), item.get("order_id"))
                ]
                checkpoint["next_cursor"] = next_provider_cursor
                checkpoint["has_more"] = has_more
        valid = [
            (item, item.get("_detail_id") if history_details and checkpoint is not None else _text(item.get("order_sn"), item.get("order_id")))
            for item in summaries
            if isinstance(item, dict) and (
                item.get("_detail_id") if history_details and checkpoint is not None else _text(item.get("order_sn"), item.get("order_id"))
            )
        ]

        def fetch_detail(item_and_id):
            _item, order_id = item_and_id
            return self._request(detail_path, {"order_sn": order_id})

        if history_details and checkpoint is not None:
            current_batch, next_index = self._detail_slice(checkpoint)
            batch = [(item, item["_detail_id"]) for item in current_batch]
        else:
            batch = valid
            next_index = len(batch)
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(batch)))) as executor:
            detail_responses = list(executor.map(fetch_detail, batch))
        records = []
        finance_fields = (
            "escrow_amount",
            "order_original_price",
            "commission_fee",
            "service_fee",
            "seller_transaction_fee",
            "seller_return_refund",
            "actual_shipping_fee",
        )
        for (summary, order_id), detail in zip(batch, detail_responses):
            raw_responses.append({"endpoint": detail_path, "payload": detail})
            detail_data = _as_dict(detail.get("response"))
            income = _as_dict(detail_data.get("order_income")) or detail_data
            currency = _text(income.get("currency"), detail_data.get("currency"), summary.get("currency"))
            occurred_at = (
                detail_data.get("escrow_release_time")
                or summary.get("escrow_release_time")
                or detail_data.get("release_time")
                or summary.get("release_time")
            )
            for field_name in finance_fields:
                if field_name not in income or income.get(field_name) in (None, ""):
                    continue
                raw_amount = income[field_name]
                if isinstance(raw_amount, dict):
                    currency = _text(raw_amount.get("currency"), currency)
                    raw_amount = raw_amount.get("amount", raw_amount.get("value"))
                records.append({
                    "source_key": f"{order_id}:{field_name}",
                    "transaction_id": f"{order_id}:{field_name}",
                    "order_id": order_id,
                    "order_item_id": "",
                    "seller_sku": "",
                    "platform_variant_id": "",
                    "fee_name": field_name,
                    "amount": raw_amount,
                    "currency": currency,
                    "occurred_at": occurred_at,
                })
        if history_details and checkpoint is not None:
            checkpoint["next_index"] = next_index
            remaining = next_index < len(checkpoint["summaries"])
            if remaining:
                self._check_detail_checkpoint_size(checkpoint)
                next_cursor = self._detail_cursor(time_from, provider_cursor, next_index)
                detail_state = checkpoint
            else:
                next_cursor = _next_time_window_cursor(scope, time_from, time_to, next_provider_cursor, windowed)
                detail_state = {}
            if not checkpoint["summaries"]:
                next_cursor = _next_time_window_cursor(scope, time_from, time_to, next_provider_cursor, windowed)
                detail_state = {}
            return {
                "records": records,
                "next_cursor": next_cursor,
                "raw_responses": raw_responses,
                "detail_state": detail_state,
                "detail_progress": {
                    "completed_in_page": next_index,
                    "remaining_in_page": max(0, len(checkpoint["summaries"]) - next_index),
                    "requests_in_slice": len(batch),
                },
            }
        provider_next_cursor = str(page_no + 1) if has_more else ""
        return {
            "records": records,
            "next_cursor": _next_time_window_cursor(
                scope, time_from, time_to, provider_next_cursor, windowed
            ),
            "raw_responses": raw_responses,
        }

    def fetch_products(self, cursor, scope):
        """Fetch complete item/model snapshots from the Shopee read APIs.

        ``get_item_list`` is an identity/index endpoint only.  It is never
        used as a source of product details when the follow-up base/model
        requests are incomplete.  This is intentional: list summaries do not
        carry the seller SKU and variant identity required by the canonical
        platform-product table.
        """
        list_path = self._runtime_path("product_list_path", self.PRODUCT_LIST_PATH)
        base_path = self._runtime_path("product_base_info_path", self.PRODUCT_BASE_INFO_PATH)
        model_path = self._runtime_path("product_model_list_path", self.PRODUCT_MODEL_LIST_PATH)
        offset = int(cursor or 0)
        query = {"offset": offset, "page_size": min(100, int(scope["page_size"]))}
        # Shopee's item-list contract requires an item_status filter.  The
        # job's generic query_statuses/statuses value is mapped here only to
        # the provider values accepted by this verified readonly slice.
        item_status = _status_values(scope.get("item_status", scope.get("statuses"))) or ["NORMAL"]
        unsupported_statuses = sorted(set(item_status) - self.SUPPORTED_PRODUCT_ITEM_STATUSES)
        if unsupported_statuses:
            raise ValidationError(
                "Shopee product status filter is not enabled for the verified readonly contract: "
                + ",".join(unsupported_statuses)
            )
        query["item_status"] = item_status
        # A first/full catalogue pass must not silently reduce the source to
        # the generic order lookback window.  Incremental product jobs may set
        # product_full_sync=false to use the documented update-time filter.
        if not scope.get("product_full_sync", True):
            query.update(
                update_time_from=scope["time_from"],
                update_time_to=scope["time_to"],
            )
        response = self._request(list_path, query)
        envelope = _as_dict(response.get("response"))
        summaries = envelope.get("item")
        if not isinstance(summaries, list):
            raise ValidationError("Shopee product list response is missing response.item.")
        if any(not isinstance(item, dict) or not item.get("item_id") for item in summaries):
            raise ValidationError("Shopee product list response contains an invalid item identity.")
        raw_responses = [{"endpoint": list_path, "payload": response}]
        item_ids = [item.get("item_id") for item in summaries if isinstance(item, dict) and item.get("item_id")]
        if not item_ids:
            return {
                "records": [],
                "next_cursor": str(envelope.get("next_offset") or "") if envelope.get("has_next_page") else "",
                "raw_responses": raw_responses,
            }

        item_batches = [item_ids[start : start + 50] for start in range(0, len(item_ids), 50)]

        def fetch_base_batch(item_batch):
            return self._request(base_path, {"item_id_list": item_batch})

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(item_batches)))) as executor:
            base_responses = list(executor.map(fetch_base_batch, item_batches))
        base_by_id = {}
        for base_response in base_responses:
            raw_responses.append({"endpoint": base_path, "payload": base_response})
            base_items = _as_dict(base_response.get("response")).get("item_list")
            if not isinstance(base_items, list):
                raise ValidationError("Shopee product base-info response is missing response.item_list.")
            if any(not isinstance(item, dict) or not item.get("item_id") for item in base_items):
                raise ValidationError("Shopee product base-info response contains an invalid item identity.")
            base_by_id.update({str(item["item_id"]): item for item in base_items})
        missing = [str(item_id) for item_id in item_ids if str(item_id) not in base_by_id]
        if missing:
            raise ValidationError("Shopee product base-info response omitted item IDs: " + ",".join(missing[:10]))

        model_item_ids = [
            str(summary["item_id"])
            for summary in summaries
            if base_by_id[str(summary["item_id"])].get("has_model")
        ]

        def fetch_models(item_id):
            return self._request(model_path, {"item_id": item_id})

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(model_item_ids)))) as executor:
            model_responses = list(executor.map(fetch_models, model_item_ids))
        model_by_id = dict(zip(model_item_ids, model_responses))

        records = []
        for summary in summaries:
            if not isinstance(summary, dict) or not summary.get("item_id"):
                continue
            item_id = str(summary["item_id"])
            base = base_by_id[item_id]
            item_status = _text(base.get("item_status"), summary.get("item_status"))
            common = {
                "platform_product_id": item_id,
                "title": _text(base.get("item_name")),
                "platform_created_at": base.get("create_time"),
                "platform_updated_at": base.get("update_time"),
                "sales_status": item_status,
                "category_l1": _text(base.get("category_id")),
            }
            if base.get("has_model"):
                model_response = model_by_id[item_id]
                raw_responses.append({"endpoint": model_path, "payload": model_response})
                model_envelope = _as_dict(model_response.get("response"))
                models = model_envelope.get("model")
                if not isinstance(models, list):
                    raise ValidationError(f"Shopee product model response is missing response.model for item {item_id}.")
                tier_variations = model_envelope.get("tier_variation")
                if not isinstance(tier_variations, list):
                    tier_variations = []
                for model in models:
                    if not isinstance(model, dict) or not model.get("model_id"):
                        raise ValidationError(f"Shopee product model response has an invalid model for item {item_id}.")
                    records.append(
                        {
                            **common,
                            "platform_variant_id": str(model["model_id"]),
                            "platform_sku": _text(model.get("model_sku")),
                            "source_old_sku_code": _text(model.get("source_old_sku_code")),
                            "variant": _shopee_variant_label(model, tier_variations),
                            "sales_status": _text(model.get("model_status"), item_status),
                        }
                    )
            else:
                # A no-model Shopee item is itself the only sellable variant;
                # using item_id as the variant identity preserves idempotency
                # without inventing a model_id that the API did not return.
                item_sku = _text(base.get("item_sku"))
                records.append(
                    {
                        **common,
                        "platform_variant_id": item_id,
                        "platform_sku": item_sku,
                        "source_old_sku_code": _text(base.get("source_old_sku_code")),
                        "variant": "",
                    }
                )
        next_cursor = str(envelope.get("next_offset") or "") if envelope.get("has_next_page") else ""
        return {"records": records, "next_cursor": next_cursor, "raw_responses": raw_responses}

    def fetch_products_by_ids(self, item_ids):
        """Hydrate an explicitly supplied Shopee ID set without catalogue listing."""
        if not isinstance(item_ids, (list, tuple)) or not 1 <= len(item_ids) <= 50:
            raise ValidationError("Shopee targeted product lookup requires 1 to 50 item IDs.")
        if any(not isinstance(item_id, str) or not item_id.isascii() or not item_id.isdecimal()
               or not 1 <= len(item_id) <= 20 or int(item_id) == 0 for item_id in item_ids):
            raise ValidationError("Shopee targeted product IDs must be nonempty numeric strings.")
        if len(set(item_ids)) != len(item_ids):
            raise ValidationError("Shopee targeted product IDs must be unique.")

        base_path = self._runtime_path("product_base_info_path", self.PRODUCT_BASE_INFO_PATH)
        model_path = self._runtime_path("product_model_list_path", self.PRODUCT_MODEL_LIST_PATH)
        response = self._request(base_path, {"item_id_list": list(item_ids)})
        raw_responses = [{"endpoint": base_path, "payload": response}]
        base_items = _as_dict(response.get("response")).get("item_list")
        if not isinstance(base_items, list):
            raise ValidationError("Shopee product base-info response is missing response.item_list.")
        requested = set(item_ids)
        base_by_id = {}
        for item in base_items:
            if not isinstance(item, dict) or not item.get("item_id"):
                raise ValidationError("Shopee product base-info response contains an invalid item identity.")
            item_id = str(item["item_id"])
            if item_id not in requested:
                raise ValidationError("Shopee product base-info response contains an unrequested item ID.")
            if item_id in base_by_id:
                raise ValidationError("Shopee product base-info response contains a duplicate item ID.")
            if type(item.get("has_model")) is not bool:
                raise ValidationError("Shopee targeted product response is missing a verified has_model flag.")
            base_by_id[item_id] = item
        unavailable = [item_id for item_id in item_ids if item_id not in base_by_id]
        model_ids = [item_id for item_id in item_ids if item_id in base_by_id and base_by_id[item_id].get("has_model")]

        def fetch_models(item_id):
            return self._request(model_path, {"item_id": item_id})

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(model_ids)))) as executor:
            model_responses = list(executor.map(fetch_models, model_ids))
        records = []
        for item_id in item_ids:
            base = base_by_id.get(item_id)
            if base is None:
                continue
            status = _text(base.get("item_status"))
            common = {
                "platform_product_id": item_id,
                "title": _text(base.get("item_name")),
                "platform_created_at": base.get("create_time"),
                "platform_updated_at": base.get("update_time"),
                "sales_status": status,
                "category_l1": _text(base.get("category_id")),
            }
            if not base.get("has_model"):
                records.append({**common, "platform_variant_id": item_id,
                    "platform_sku": _text(base.get("item_sku")),
                    "source_old_sku_code": _text(base.get("source_old_sku_code")), "variant": ""})
                continue
            model_response = model_responses[model_ids.index(item_id)]
            raw_responses.append({"endpoint": model_path, "payload": model_response})
            envelope = _as_dict(model_response.get("response"))
            models = envelope.get("model")
            if not isinstance(models, list):
                raise ValidationError(f"Shopee product model response is missing response.model for item {item_id}.")
            if not models:
                unavailable.append(item_id)
                continue
            seen_models = set()
            tiers = envelope.get("tier_variation")
            if not isinstance(tiers, list):
                tiers = []
            for model in models:
                if not isinstance(model, dict) or not model.get("model_id"):
                    raise ValidationError(f"Shopee product model response has an invalid model for item {item_id}.")
                model_id = str(model["model_id"])
                if (not model_id.isascii() or not model_id.isdecimal() or int(model_id) == 0
                        or len(model_id) > 20 or model_id in seen_models):
                    raise ValidationError("Shopee targeted product response contains an invalid or duplicate model ID.")
                seen_models.add(model_id)
                records.append({**common, "platform_variant_id": str(model["model_id"]),
                    "platform_sku": _text(model.get("model_sku")),
                    "source_old_sku_code": _text(model.get("source_old_sku_code")),
                    "variant": _shopee_variant_label(model, tiers),
                    "sales_status": _text(model.get("model_status"), status)})
        return {"records": records, "raw_responses": raw_responses,
                "unavailable_item_ids": unavailable, "next_cursor": ""}


class TikTokReadonlyClient(ReadonlyClientBase):
    ORDER_LIST_PATH = settings.LIVE_TIKTOK_ORDER_LIST_PATH
    ORDER_DETAIL_PATH = settings.LIVE_TIKTOK_ORDER_DETAIL_PATH
    RETURN_LIST_PATH = settings.LIVE_TIKTOK_RETURN_LIST_PATH
    PRODUCT_SEARCH_PATH = settings.LIVE_TIKTOK_PRODUCT_SEARCH_PATH
    PRODUCT_DETAIL_PATH = settings.LIVE_TIKTOK_PRODUCT_DETAIL_PATH
    FINANCE_STATEMENT_PATH = settings.LIVE_TIKTOK_FINANCE_STATEMENT_PATH
    FINANCE_TRANSACTION_PATH = settings.LIVE_TIKTOK_FINANCE_TRANSACTION_PATH
    # Partner Center documents that Get Product cannot retrieve these search
    # statuses.  Search Products still returns their source product identity,
    # status, update time, and (when present) real SKU IDs.  Those rows are
    # emitted as explicit status-only snapshots below; they never fall back to
    # a complete detail snapshot.
    DETAIL_UNAVAILABLE_STATUSES = frozenset({"FREEZE", "DELETED"})
    SUPPORTED_PRODUCT_STATUSES = frozenset(
        {
            "ALL",
            "DRAFT",
            "PENDING",
            "FAILED",
            "ACTIVATE",
            "SELLER_DEACTIVATED",
            "PLATFORM_DEACTIVATED",
            "FREEZE",
            "DELETED",
        }
    )

    def _api_host(self):
        host = str(get_runtime_platform_config("tiktok").get("api_host") or "").strip()
        if not host or host.startswith("REPLACE_ME"):
            raise ReadonlyConfigurationError(
                "TikTok 同步缺少已批准的 API 域名（tiktok.api_host），"
                "请在生产环境配置中检查；本次未调用平台接口，无需重新授权。"
            )
        return host

    def preflight(self):
        super().preflight()
        self._api_host()

    def _request(self, path, *, query=None, body=None, method="GET"):
        self.preflight()
        authorization = self.authorization
        if authorization is None or authorization.status != authorization.Status.ACTIVE:
            raise ValidationError("TikTok Shop store authorization is not active.")
        if authorization.expires_at and authorization.expires_at <= self.now():
            raise ValidationError("TOKEN_EXPIRED_REAUTH_REQUIRED")
        host = self._api_host()
        app_key = _required(self.platform_config.get("app_key"), "tiktok.app_key")
        secret_reference = self.config.credential_id or self.platform_config.get("app_secret_reference")
        app_secret = _required(
            self.custody.retrieve_secret(_required(secret_reference, "tiktok.app_secret_reference")),
            "tiktok.app_secret",
        )
        access_token = self.custody.retrieve_access_token(authorization.token_id)
        body = body or {}
        body_text = json.dumps(body, separators=(",", ":")) if method == "POST" else ""
        params = {"app_key": app_key, "timestamp": int(self.now().timestamp()), **(query or {})}
        sign_params = {key: value for key, value in params.items() if key not in {"sign", "access_token"}}
        joined = "".join(f"{key}{sign_params[key]}" for key in sorted(sign_params))
        signature_text = f"{app_secret}{path}{joined}{body_text}{app_secret}"
        params["sign"] = hmac.new(app_secret.encode(), signature_text.encode(), hashlib.sha256).hexdigest()
        response = self.http.request(
            method,
            _query_url(host, path, params),
            headers={"Content-Type": "application/json", "x-tts-access-token": access_token},
            json_body=body if method == "POST" else None,
            connect_timeout=self.config.connect_timeout_seconds,
            read_timeout=self.config.read_timeout_seconds,
        )
        payload = self._response_json(response)
        if int(payload.get("code") or 0) != 0 or "data" not in payload:
            raise ValidationError("TikTok Shop rejected the readonly request.")
        return payload

    def fetch_marketplace_creator(self, creator_user_id):
        self.resource_type = "affiliate_creator_profile"
        scope = str(get_runtime_platform_config("tiktok").get("affiliate_seller_creator_scope") or "").strip()
        if not scope or scope not in (self.authorization.scopes or []):
            raise ValidationError("TikTok Affiliate seller read scope has not been verified for this shop; reauthorization is required.")
        creator_id = str(creator_user_id or "").strip()
        if not creator_id.isascii() or not creator_id.isdecimal() or not 1 <= len(creator_id) <= 20 or int(creator_id) == 0:
            raise ValidationError("A trusted numeric TikTok creator_user_id is required.")
        payload = self._request(
            f"/affiliate_seller/202406/marketplace_creators/{creator_id}",
            query={"shop_cipher": self.authorization.shop_cipher, "data_groups": "BASIC_CREATOR_INFORMATION"},
        )
        creator = (payload.get("data") or {}).get("creator")
        if not isinstance(creator, dict):
            raise ValidationError("TikTok Creator API returned no creator profile.")
        return creator

    def fetch_orders(self, cursor, scope):
        order_list_path = self._runtime_path("order_list_path", self.ORDER_LIST_PATH)
        order_detail_path = self._runtime_path("order_detail_path", self.ORDER_DETAIL_PATH)
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 30)
        time_field = "create_time" if scope.get("time_basis") == "created" else "update_time"
        query = {
            "shop_cipher": self.authorization.shop_cipher,
            "page_size": scope["page_size"],
            "sort_field": time_field,
            "sort_order": "ASC",
            **({"page_token": provider_cursor} if provider_cursor else {}),
        }
        payload = self._request(
            order_list_path,
            query=query,
            body={f"{time_field}_ge": time_from, f"{time_field}_lt": time_to + 1},
            method="POST",
        )
        data = _as_dict(payload.get("data"))
        raw_responses = [{"endpoint": order_list_path, "payload": payload}]
        summaries = data.get("orders")
        if not isinstance(summaries, list):
            raise ValidationError("TikTok order search response is missing data.orders.")
        order_ids = []
        for item in summaries:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                raise ValidationError("TikTok order search returned an invalid order ID.")
            order_ids.append(str(item["id"]).strip())
        if len(order_ids) != len(set(order_ids)):
            raise ValidationError("TikTok order search returned duplicate order IDs.")
        details = []
        order_batches = [order_ids[start : start + 50] for start in range(0, len(order_ids), 50)]

        def fetch_order_batch(order_batch):
            return self._request(
                order_detail_path,
                query={"shop_cipher": self.authorization.shop_cipher, "ids": ",".join(order_batch)},
            )

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(order_batches)))) as executor:
            detail_responses = list(executor.map(fetch_order_batch, order_batches))
        for detail in detail_responses:
            raw_responses.append({"endpoint": order_detail_path, "payload": detail})
            batch_details = _as_dict(detail.get("data")).get("orders")
            if not isinstance(batch_details, list):
                raise ValidationError("TikTok order detail response is missing data.orders.")
            details.extend(batch_details)
        detail_ids = []
        for item in details:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                raise ValidationError("TikTok order detail returned an invalid order ID.")
            detail_ids.append(str(item["id"]).strip())
        if len(detail_ids) != len(set(detail_ids)) or set(detail_ids) != set(order_ids):
            raise ValidationError("TikTok order detail does not exactly match the search page.")
        return {
            "records": details,
            "next_cursor": _next_time_window_cursor(
                scope, time_from, time_to, data.get("next_page_token"), windowed
            ),
            "raw_responses": raw_responses,
        }

    def fetch_returns(self, cursor, scope):
        return_list_path = self._runtime_path("return_list_path", self.RETURN_LIST_PATH)
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 30)
        query = {
            "shop_cipher": self.authorization.shop_cipher,
            "page_size": min(50, scope["page_size"]),
            **({"page_token": provider_cursor} if provider_cursor else {}),
        }
        payload = self._request(
            return_list_path,
            query=query,
            body={"create_time_ge": time_from, "create_time_lt": time_to + 1},
            method="POST",
        )
        data = _as_dict(payload.get("data"))
        records = _as_list(data.get("return_orders")) or _as_list(data.get("returns"))
        return {
            "records": records,
            "next_cursor": _next_time_window_cursor(
                scope, time_from, time_to, data.get("next_page_token"), windowed
            ),
            "raw_responses": [{"endpoint": return_list_path, "payload": payload}],
        }

    def fetch_finance_transactions(self, cursor, scope):
        statement_path = self._runtime_path("finance_statement_path", self.FINANCE_STATEMENT_PATH)
        transaction_path = self._runtime_path("finance_transaction_path", self.FINANCE_TRANSACTION_PATH)
        from . import tiktok_finance_fields as fields

        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 31)
        # Finish a bounded statement window before advancing its durable cursor.
        # Old mid-provider cursors cannot prove that earlier pages were unique.
        if provider_cursor:
            raise ValidationError("TK_FINANCE_LEGACY_CURSOR_RESTART_REQUIRED")
        query = {
            "shop_cipher": self.authorization.shop_cipher,
            "statement_time_ge": time_from,
            "statement_time_lt": time_to + 1,
            "sort_field": "statement_time",
            "sort_order": "ASC",
            "page_size": min(100, int(scope["page_size"])),
            **({"page_token": provider_cursor} if provider_cursor else {}),
        }
        valid, statement_ids = [], set()
        statement_responses, statement_tokens = [], set()
        for _page in range(100):
            response = self._request(statement_path, query=query)
            statement_responses.append({"endpoint": statement_path, "payload": response})
            data = response.get("data")
            statements = fields.records(data, "statements", query["page_size"])
            for statement in statements:
                statement_id = _text(statement.get("id"), statement.get("statement_id"))
                if not statement_id or statement_id in statement_ids:
                    raise ValidationError("TK_FINANCE_STATEMENT_ID_INVALID_OR_DUPLICATE")
                statement_ids.add(statement_id)
                valid.append((statement, statement_id))
            if len(valid) > 100:
                raise ValidationError("TK_FINANCE_STATEMENT_WINDOW_LIMIT_EXCEEDED")
            token = fields.page_token(data)
            if not token:
                break
            if not statements or token in statement_tokens:
                raise ValidationError("TK_FINANCE_PAGINATION_NOT_ADVANCING")
            statement_tokens.add(token)
            query = {**query, "page_token": token}
        else:
            raise ValidationError("TK_FINANCE_PAGINATION_LIMIT_EXCEEDED")

        def fetch_statement_transactions(statement_and_id):
            statement, statement_id = statement_and_id
            statement = dict(statement)
            path = transaction_path.format(
                statement_id=urllib.parse.quote(statement_id, safe="")
            )
            page_token = ""
            seen_tokens, transaction_ids = set(), set()
            expected_count = None
            responses = []
            transactions = []
            for _page in range(100):
                detail = self._request(
                    path,
                    query={
                        "shop_cipher": self.authorization.shop_cipher,
                        "page_size": min(100, int(scope["page_size"])),
                        **({"page_token": page_token} if page_token else {}),
                    },
                )
                responses.append((path, detail))
                detail_data = detail.get("data")
                rows = fields.records(detail_data, "transactions", query["page_size"])
                if "total_count" in detail_data:
                    total = detail_data["total_count"]
                    if (type(total) is not int or total < 0 or total > 100 * query["page_size"]
                            or expected_count is not None and total != expected_count):
                        raise ValidationError("TK_FINANCE_TOTAL_COUNT_INVALID_OR_CHANGED")
                    expected_count = total
                if detail_data.get("currency"):
                    if statement.get("currency") and statement["currency"] != detail_data["currency"]:
                        raise ValidationError("TK_FINANCE_CURRENCY_MISMATCH")
                    statement["currency"] = detail_data["currency"]
                for item in rows:
                    transaction_id = _text(item.get("id"), item.get("transaction_id"))
                    if not transaction_id or transaction_id in transaction_ids:
                        raise ValidationError("TK_FINANCE_TRANSACTION_ID_INVALID_OR_DUPLICATE")
                    transaction_ids.add(transaction_id)
                transactions.extend(rows)
                if expected_count is not None and len(transactions) > expected_count:
                    raise ValidationError("TK_FINANCE_TOTAL_COUNT_MISMATCH")
                page_token = fields.page_token(detail_data)
                if not page_token:
                    if expected_count is not None and len(transactions) != expected_count:
                        raise ValidationError("TK_FINANCE_TOTAL_COUNT_MISMATCH")
                    break
                if not rows or page_token in seen_tokens:
                    raise ValidationError("TK_FINANCE_PAGINATION_NOT_ADVANCING")
                seen_tokens.add(page_token)
            else:
                raise ValidationError("TK_FINANCE_PAGINATION_LIMIT_EXCEEDED")
            return statement, statement_id, responses, transactions

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(valid)))) as executor:
            details = list(executor.map(fetch_statement_transactions, valid))
        raw_responses = statement_responses
        records = []
        for statement, statement_id, detail_responses, transactions in details:
            raw_responses.extend(
                {"endpoint": path, "payload": detail}
                for path, detail in detail_responses
            )
            for item in transactions:
                transaction_id = _text(item.get("id"), item.get("transaction_id"))
                currency = _text(item.get("currency"), statement.get("currency"))
                raw_amount = item.get("settlement_amount", item.get("amount", item.get("transaction_amount")))
                exact_amount = fields.amount(raw_amount, currency)
                records.append({
                    "source_key": f"{statement_id}:{transaction_id}",
                    "transaction_id": transaction_id,
                    "order_id": _text(item.get("order_id")),
                    "order_item_id": _text(item.get("order_item_id"), item.get("sku_order_id")),
                    "seller_sku": _text(item.get("seller_sku")),
                    "platform_variant_id": _text(item.get("sku_id")),
                    "fee_name": _text(item.get("type"), item.get("transaction_type"), "UNKNOWN"),
                    "amount": exact_amount,
                    "currency": currency,
                    "occurred_at": item.get("create_time") or item.get("transaction_time")
                    or statement.get("statement_time") or statement.get("settlement_time"),
                })
        next_cursor = _next_time_window_cursor(
            scope, time_from, time_to, "", windowed
        )
        return {"records": records, "next_cursor": next_cursor, "raw_responses": raw_responses}

    def fetch_products(self, cursor, scope):
        """Search product IDs, then hydrate every ID with Get Product.

        TikTok documents Search Products as returning only key properties and
        explicitly directs callers to Get Product for the complete product
        and SKU shape.  A malformed detail response therefore fails closed;
        list summaries are never persisted as canonical product snapshots.
        """
        search_path = self._runtime_path("product_search_path", self.PRODUCT_SEARCH_PATH)
        detail_path = self._runtime_path("product_detail_path", self.PRODUCT_DETAIL_PATH)
        query = {
            "shop_cipher": self.authorization.shop_cipher,
            "page_size": min(100, int(scope["page_size"])),
            **({"page_token": cursor} if cursor else {}),
        }
        statuses = _status_values(scope.get("statuses"))
        if len(statuses) > 1:
            raise ValidationError("TikTok product search accepts one status value per request.")
        product_status = statuses[0] if statuses else "ALL"
        if product_status not in self.SUPPORTED_PRODUCT_STATUSES:
            raise ValidationError(f"TikTok product status filter is not supported: {product_status}.")
        search_body = {"status": product_status}
        # TikTok Search Products defines its update window in the JSON body,
        # not in the query string.  Keep full sync on ALL by default so frozen
        # and deleted products can be reconciled as status-only snapshots.
        if not scope.get("product_full_sync", True):
            search_body.update(
                update_time_ge=scope["time_from"],
                update_time_le=scope["time_to"],
            )
        payload = self._request(
            search_path,
            query=query,
            body=search_body,
            method="POST",
        )
        data = _as_dict(payload.get("data"))
        summaries = data.get("products")
        if not isinstance(summaries, list):
            raise ValidationError("TikTok product search response is missing data.products.")
        raw_responses = [{"endpoint": search_path, "payload": payload}]
        detail_targets = []
        for summary in summaries:
            if not isinstance(summary, dict):
                raise ValidationError("TikTok product search response contains an invalid product summary.")
            product_id = _text(summary.get("id"), summary.get("product_id"))
            if not product_id:
                raise ValidationError("TikTok product search response contains a product without id.")
            summary_status = _text(summary.get("status"), summary.get("product_status")).upper()
            if summary_status not in self.DETAIL_UNAVAILABLE_STATUSES:
                detail_targets.append((product_id, detail_path.format(product_id=urllib.parse.quote(product_id, safe=""))))

        def fetch_product_detail(target):
            _product_id, path = target
            return self._request(path, query={"shop_cipher": self.authorization.shop_cipher})

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(detail_targets)))) as executor:
            detail_responses = list(executor.map(fetch_product_detail, detail_targets))
        details_by_id = {
            product_id: (path, detail)
            for (product_id, path), detail in zip(detail_targets, detail_responses)
        }
        records = []
        for summary in summaries:
            product_id = _text(summary.get("id"), summary.get("product_id"))
            summary_status = _text(summary.get("status"), summary.get("product_status")).upper()
            if summary_status in self.DETAIL_UNAVAILABLE_STATUSES:
                records.extend(self._status_only_records(summary, product_id, summary_status))
                # The Search Products page remains complete and can advance
                # its opaque cursor even when a detail endpoint cannot serve a
                # tombstone.  Ingestion updates only exact existing variants;
                # unknown/missing variants are audited skips.
                continue
            path, detail = details_by_id[product_id]
            raw_responses.append({"endpoint": path, "payload": detail})
            product = _as_dict(detail.get("data"))
            detail_id = _text(product.get("product_id"), product.get("id"))
            skus = product.get("skus")
            if not detail_id or detail_id != product_id or not isinstance(skus, list):
                raise ValidationError(f"TikTok product detail response is incomplete for product {product_id}.")
            if not skus:
                if (_text(product.get("status"), product.get("product_status")).upper() == "DRAFT"
                        and product.get("product_status") in (None, "", "DRAFT")):
                    if product.get("update_time") in (None, ""):
                        raise ValidationError(f"TikTok draft product {product_id} is missing update_time.")
                    _draft_epoch_seconds(product["update_time"])
                    # A draft may have no variants yet. Preserve an observation
                    # for auditing, never create a SKU or change known variants.
                    records.append({"platform_product_id": product_id, "platform_variant_id": "",
                        "sales_status": "DRAFT", "platform_updated_at": product["update_time"],
                        "draft_without_skus": True})
                    continue
                raise ValidationError(f"TikTok product detail response has no SKU list for product {product_id}.")
            from .tiktok_product_fields import categories

            category_fields = categories(product)
            for sku in skus:
                if not isinstance(sku, dict) or not _text(sku.get("id")):
                    raise ValidationError(f"TikTok product detail response has an invalid SKU for product {product_id}.")
                records.append(
                    {
                        "platform_product_id": product_id,
                        "platform_variant_id": _text(sku.get("id")),
                        "platform_sku": _text(sku.get("seller_sku")),
                        "source_old_sku_code": _text(sku.get("source_old_sku_code")),
                        **({"title": _text(product.get("title"), summary.get("title"))}
                           if product.get("title") is not None or summary.get("title") is not None else {}),
                        **({"variant": _tiktok_variant_label(sku["sales_attributes"])}
                           if isinstance(sku.get("sales_attributes"), list) else {}),
                        "sales_status": _text(product.get("status"), summary.get("status")),
                        "platform_created_at": product.get("create_time"),
                        "platform_updated_at": product.get("update_time"),
                        **category_fields,
                    }
                )
        return {
            "records": records,
            "next_cursor": str(data.get("next_page_token") or ""),
            "raw_responses": raw_responses,
        }

    @staticmethod
    def _status_only_records(summary, product_id, status):
        """Build partial records for TikTok FREEZE/DELETED search rows.

        Search Products is authoritative for the product ID/status/update
        timestamp, but Get Product explicitly does not serve these statuses.
        The search response may still contain real SKU identities.  Preserve
        those IDs when present; when it does not, emit one product-level row
        with an empty variant ID so the ingestion boundary can audit and skip
        it without fabricating a SKU/detail.
        """

        updated_at = summary.get("update_time", summary.get("updated_at"))
        if updated_at in (None, ""):
            raise ValidationError(
                f"TikTok status-only product {product_id} is missing update_time; product checkpoint is not advanced."
            )
        raw_skus = summary.get("skus")
        if raw_skus is None:
            raw_skus = []
        if not isinstance(raw_skus, list):
            raise ValidationError(f"TikTok status-only product {product_id} has an invalid SKU list.")
        base = {
            "platform_product_id": product_id,
            "platform_sku": "",
            "source_old_sku_code": "",
            "title": "",
            "variant": "",
            "sales_status": status,
            "platform_created_at": None,
            "platform_updated_at": updated_at,
            "category_l1": "",
            "status_only": True,
            "partial_snapshot": True,
            "snapshot_kind": "status_only",
        }
        if not raw_skus:
            return [{**base, "platform_variant_id": ""}]
        records = []
        for sku in raw_skus:
            if not isinstance(sku, dict) or not _text(sku.get("id")):
                raise ValidationError(f"TikTok status-only product {product_id} has an invalid SKU identity.")
            records.append(
                {
                    **base,
                    "platform_variant_id": _text(sku.get("id")),
                    "platform_sku": _text(sku.get("seller_sku")),
                }
            )
        return records


class JifengWmsReadonlyClient(ReadonlyClientBase):
    INVENTORY_PATH = settings.LIVE_JIFENG_WMS_INVENTORY_PATH
    WAREHOUSE_LIST_PATH = "/api/warehouse/getList"

    def _signed_post(self, path, body):
        self.preflight()
        authorization = self.authorization
        if authorization is None or authorization.status != authorization.Status.ACTIVE:
            raise ValidationError("Jifeng WMS warehouse authorization is not active.")
        site = str(
            getattr(authorization, "external_warehouse_region", "")
            or self.platform_config.get("site_code")
            or ""
        ).upper()
        if site not in {"PH", "TH", "MY"}:
            raise ValidationError("Jifeng WMS site must be PH, TH, or MY.")
        host = _required(self.platform_config.get("api_host"), f"jifeng_wms.{site}.api_host")
        client_id = _required(self.platform_config.get("client_id"), f"jifeng_wms.{site}.client_id")
        user_id = _required(getattr(authorization, "oauth_user_id", ""), "仓库 OAuth userId（请先完成首次授权）")
        if not getattr(authorization, "email", ""):
            raise ValidationError("仓库授权待补充：缺少 Email。")
        if not authorization.oauth_expires_at or authorization.oauth_expires_at <= self.now():
            raise ValidationError("仓库 AccessToken 已过期，请刷新授权后再校验。")
        client_secret = self.custody.retrieve_secret(_required(self.config.credential_id, "jifeng_wms.credential_id"))
        access_token = self.custody.retrieve_access_token(_required(authorization.token_id, "仓库 AccessToken"))
        timestamp = str(int(self.now().timestamp() * 1000))
        nonce = str(secrets.randbelow(10**12)).zfill(12)
        sign_values = {
            "accessToken": access_token,
            "clientId": client_id,
            "method": "post",
            "nonce": nonce,
            "timestamp": timestamp,
            "url": path,
            "userId": user_id,
        }
        sign_input = "&".join(f"{key}={sign_values[key]}" for key in sorted(sign_values))
        signature = hmac.new(client_secret.encode(), sign_input.encode(), hashlib.sha256).hexdigest()
        from .warehouse_credential_service import jifeng_api_url
        response = self.http.request(
            "POST",
            jifeng_api_url(host, path),
            headers={
                "Content-Type": "application/json",
                "Accept-Language": "zh_CN",
                "clientId": client_id,
                "accessToken": access_token,
                "timestamp": timestamp,
                "nonce": nonce,
                "userId": user_id,
                "sign": signature,
            },
            json_body=body,
            connect_timeout=self.config.connect_timeout_seconds,
            read_timeout=self.config.read_timeout_seconds,
        )
        return self._response_json(response)

    def fetch_warehouses(self):
        # The documented endpoint returns all accessible warehouses without
        # codeList. Do not forward contact details or raw provider responses.
        payload = self._signed_post(self.WAREHOUSE_LIST_PATH, {})
        if str(payload.get("code")) != "0":
            raise ValidationError("极风拒绝仓库列表查询，请核对仓库授权和网络白名单。")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ValidationError("极风仓库列表响应格式不完整，未关联仓库。")
        warehouses = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValidationError("极风仓库列表响应格式不完整，未关联仓库。")
            code = row.get("code")
            country = row.get("country")
            if (not isinstance(code, str) or not code.strip() or len(code) > 160
                    or any(ord(char) < 32 for char in code)
                    or not isinstance(country, str) or len(country.strip()) != 2
                    or not isinstance(row.get("isAuth"), bool) or code.strip() in seen):
                raise ValidationError("极风仓库编号、国家或授权标识缺失或重复，未自动关联。")
            seen.add(code.strip())
            warehouses.append({"code": code.strip(), "name": row["name"][:160] if isinstance(row.get("name"), str) else "",
                "country": country.strip().upper(), "is_authorized": row["isAuth"]})
        return warehouses

    def fetch_inventory(self, cursor, scope):
        # Inventory must remain binding-scoped; discovery alone is not an
        # inventory check and cannot fall back to a shared/local warehouse.
        warehouse_code = _required(
            getattr(self.authorization, "external_warehouse_code", ""),
            "jifeng_wms.external_warehouse_code",
        )
        page_no = int(cursor or 1)
        body = {"pageNo": page_no, "pageSize": min(300, max(1, int(scope["page_size"]))), "warehouse": warehouse_code}
        payload = self._signed_post(self.INVENTORY_PATH, body)
        code = str(payload.get("code"))
        if code != "0":
            if code in {"10041", "10042", "10050", "10051"}:
                raise ValidationError("极风仓库不存在或当前 OMS 账号无仓库权限。")
            if code in {"10000", "10001", "10043", "10052"}:
                raise ValidationError("极风查询参数缺失或错误，请核对外部仓库编码和分页参数。")
            if code in {"10002", "10008", "10009", "10015", "10016", "10026", "10040"}:
                raise ValidationError("极风认证失败，请核对公共凭据及仓库授权。")
            raise ValidationError("极风拒绝库存查询，请检查网络白名单或稍后重试。")
        data = payload.get("data")
        page = _as_dict(_as_dict(data).get("page"))
        source = page or _as_dict(data)
        records = []
        for name in ("list", "records", "items", "rows", "content"):
            if isinstance(source.get(name), list):
                records = source[name]
                break
        else:
            raise ValidationError("极风库存响应缺少记录列表，不能标记为校验通过。")
        total_page = int(page.get("totalPage") or page_no)
        snapshot_at = self.now().isoformat()
        return {
            "records": [{**item, "_snapshot_at_utc": snapshot_at} for item in records if isinstance(item, dict)],
            "next_cursor": str(page_no + 1) if page_no < total_page else "",
            "raw_responses": [{"endpoint": self.INVENTORY_PATH, "payload": payload}],
        }


def default_sync_scope(config, override=None, resource_type=None, authorization=None):
    if resource_type == "advertising_report":
        from .shopee_advertising import advertising_sync_scope
        scope = advertising_sync_scope(config, override, authorization)
        from .retention_policy import bounded_range
        scope["time_from"], scope["time_to"] = bounded_range(
            scope["time_from"], scope["time_to"], resource_type,
            getattr(authorization, "store", None),
        )
        return scope
    scope = dict((config.platform_config or {}).get("sync_scope") or {})
    if isinstance(override, dict):
        # SyncJob stores schedule and query policy in nested objects.  Flatten
        # only the query controls used by live clients, while retaining the
        # explicit product_full_sync flag at job scope.
        scope.update({key: value for key, value in override.items() if key not in {"schedule", "query"}})
        query = override.get("query")
        if isinstance(query, dict):
            scope.update(query)
    now = timezone.now()
    from .order_product_gaps import product_backfill_mode
    product_order_backfill = product_backfill_mode(config, resource_type, scope)
    lookback_days = max(1, min(int(scope.get("lookback_days") or 1), 30))
    start, end = now - timedelta(days=lookback_days), now
    uses_time_range = resource_type in {"sales_order", "refund_return", "settlement_bill"} or (
        resource_type == "platform_product" and not bool(scope.get("product_full_sync", True))
        and product_order_backfill != "order_missing_only"
    )
    if uses_time_range:
        from datetime import date, datetime, time
        from zoneinfo import ZoneInfo
        from django.utils.dateparse import parse_datetime
        zone = ZoneInfo("Asia/Shanghai")
        maximum = 30 if resource_type == "platform_product" else 31
        mode = scope.get("mode", scope.get("query_mode", "incremental"))
        if mode == "range":
            start_value = str(scope.get("start_at") or scope.get("range_start_at") or "")
            end_value = str(scope.get("end_at") or scope.get("range_end_at") or "")
            try:
                if len(start_value) == 10 and len(end_value) == 10:
                    start_day, end_day = date.fromisoformat(start_value), date.fromisoformat(end_value)
                    if start_day > end_day or end_day > now.astimezone(zone).date():
                        raise ValidationError("开始日期不能晚于结束日期，结束日期不能晚于今天。")
                    if (end_day - start_day).days + 1 > maximum:
                        raise ValidationError(f"含首尾日期最多 {maximum} 天，请分段采集。")
                    start = datetime.combine(start_day, time.min, zone)
                    end = min(datetime.combine(end_day, time(23, 59, 59), zone), now)
                else:
                    start = parse_datetime(start_value)
                    end = parse_datetime(end_value)
            except ValueError:
                start = end = None
            if not start or not end or timezone.is_naive(start) or timezone.is_naive(end):
                raise ValidationError("采集起止时间必须有效且包含时区。")
            if start >= end or end > now:
                raise ValidationError("采集开始时间必须早于结束时间，结束时间不能晚于当前时间。")
            if end - start > timedelta(days=maximum):
                raise ValidationError(f"单次采集范围最多 {maximum} 天，请分段采集。")
        elif mode == "incremental":
            raw_days = scope.get("lookback_days", 1)
            if isinstance(raw_days, bool) or str(raw_days) != str(int(raw_days)) or not 1 <= int(raw_days) <= maximum:
                raise ValidationError(f"回看天数必须为 1～{maximum} 的整数。")
            start_day = now.astimezone(zone).date() - timedelta(days=int(raw_days) - 1)
            start = datetime.combine(start_day, time.min, zone)
        else:
            raise ValidationError("不支持的采集范围模式。")
    platform = str(getattr(config, "platform", "") or "").lower()
    is_lazada_finance = platform == "lazada" and resource_type == "settlement_bill"
    is_jifeng_inventory = (
        platform == "jifeng_wms" and resource_type == "inventory_snapshot"
    )
    default_page_size = 500 if is_lazada_finance else 300 if is_jifeng_inventory else 100
    maximum_page_size = default_page_size
    page_size = max(1, min(int(scope.get("page_size") or default_page_size), maximum_page_size))
    time_basis = None
    if resource_type == "sales_order":
        time_basis = scope.get("time_basis") or ("created" if mode == "range" else "updated")
        if time_basis not in {"created", "updated"}:
            raise ValidationError("订单采集时间口径无效。")
    # SyncJob stores the provider-neutral policy as query.statuses.  Preserve
    # it in the runtime scope so each client can map it to its own verified
    # request shape (Shopee query.item_status; TikTok JSON body.status).
    raw_statuses = scope.get("statuses", scope.get("query_statuses"))
    statuses = _status_values(raw_statuses)
    result = {
        "time_from": int(start.timestamp()),
        "time_to": int(end.timestamp()),
        "page_size": page_size,
        # Full product snapshots are the safe default.  A product job may
        # explicitly opt into the documented update-time window without
        # changing the order/refund query policy.
        "product_full_sync": bool(scope.get("product_full_sync", True)),
        "product_order_backfill": product_order_backfill,
        "time_basis": time_basis,
        "statuses": statuses,
    }
    if uses_time_range:
        from .retention_policy import bounded_range
        result["time_from"], result["time_to"] = bounded_range(
            result["time_from"], result["time_to"], resource_type,
            getattr(authorization, "store", None),
        )
    return result
