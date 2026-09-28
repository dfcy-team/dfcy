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
from rest_framework.exceptions import ValidationError

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
            "product_contract_approved"
            if self.resource_type == "platform_product"
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

    def _request(self, path, query):
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
            "GET",
            _query_url(host, path, signed),
            connect_timeout=self.config.connect_timeout_seconds,
            read_timeout=self.config.read_timeout_seconds,
        )
        payload = self._response_json(response)
        if payload.get("error"):
            raise ValidationError("Shopee rejected the readonly request.")
        return payload

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
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 15)
        page_no = int(provider_cursor or 0)
        response = self._request(
            return_list_path,
            {
                "create_time_from": time_from,
                "create_time_to": time_to,
                "page_no": page_no,
                "page_size": scope["page_size"],
            },
        )
        envelope = _as_dict(response.get("response"))
        raw_responses = [{"endpoint": return_list_path, "payload": response}]
        summaries = _as_list(envelope.get("return")) or _as_list(envelope.get("return_list"))
        valid_returns = [
            (item, item.get("return_sn") or item.get("return_id"))
            for item in summaries
            if isinstance(item, dict) and (item.get("return_sn") or item.get("return_id"))
        ]

        def fetch_return_detail(item_and_id):
            _item, return_id = item_and_id
            return self._request(return_detail_path, {"return_sn": return_id})

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(valid_returns)))) as executor:
            detail_responses = list(executor.map(fetch_return_detail, valid_returns))
        details = []
        for (item, _return_id), detail in zip(valid_returns, detail_responses):
            raw_responses.append({"endpoint": return_detail_path, "payload": detail})
            detail_record = _as_dict(detail.get("response"))
            details.append({**item, **detail_record})
        has_more = bool(envelope.get("more") or envelope.get("has_more"))
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
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 15)
        page_no = max(1, int(provider_cursor or 1))
        response = self._request(
            list_path,
            {
                "release_time_from": time_from,
                "release_time_to": time_to,
                "page_size": min(100, int(scope["page_size"])),
                "page_no": page_no,
            },
        )
        envelope = _as_dict(response.get("response"))
        summaries = _as_list(envelope.get("order_income_list")) or _as_list(envelope.get("escrow_list"))
        valid = [
            (item, _text(item.get("order_sn"), item.get("order_id")))
            for item in summaries
            if isinstance(item, dict) and _text(item.get("order_sn"), item.get("order_id"))
        ]

        def fetch_detail(item_and_id):
            _item, order_id = item_and_id
            return self._request(detail_path, {"order_sn": order_id})

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(valid)))) as executor:
            detail_responses = list(executor.map(fetch_detail, valid))
        raw_responses = [{"endpoint": list_path, "payload": response}]
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
        for (summary, order_id), detail in zip(valid, detail_responses):
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
        provider_next_cursor = str(page_no + 1) if envelope.get("more") or envelope.get("has_more") else ""
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
        app_secret = self.custody.retrieve_secret(_required(secret_reference, "tiktok.app_secret_reference"))
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
        summaries = _as_list(data.get("orders"))
        order_ids = [str(item.get("id")) for item in summaries if isinstance(item, dict) and item.get("id")]
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
            details.extend(_as_list(_as_dict(detail.get("data")).get("orders")))
        return {
            "records": details or summaries,
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
        time_from, time_to, provider_cursor, windowed = _time_window(cursor, scope, 31)
        query = {
            "shop_cipher": self.authorization.shop_cipher,
            "statement_time_ge": time_from,
            "statement_time_lt": time_to + 1,
            "page_size": min(100, int(scope["page_size"])),
            **({"page_token": provider_cursor} if provider_cursor else {}),
        }
        response = self._request(statement_path, query=query)
        data = _as_dict(response.get("data"))
        statements = _as_list(data.get("statements"))
        valid = [
            (statement, _text(statement.get("id"), statement.get("statement_id")))
            for statement in statements
            if isinstance(statement, dict) and _text(statement.get("id"), statement.get("statement_id"))
        ]

        def fetch_statement_transactions(statement_and_id):
            statement, statement_id = statement_and_id
            path = transaction_path.format(
                statement_id=urllib.parse.quote(statement_id, safe="")
            )
            page_token = ""
            responses = []
            transactions = []
            while True:
                detail = self._request(
                    path,
                    query={
                        "shop_cipher": self.authorization.shop_cipher,
                        "page_size": min(100, int(scope["page_size"])),
                        **({"page_token": page_token} if page_token else {}),
                    },
                )
                responses.append((path, detail))
                detail_data = _as_dict(detail.get("data"))
                transactions.extend(_as_list(detail_data.get("transactions")))
                page_token = _text(detail_data.get("next_page_token"))
                if not page_token:
                    break
            return statement, statement_id, responses, transactions

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(valid)))) as executor:
            details = list(executor.map(fetch_statement_transactions, valid))
        raw_responses = [{"endpoint": statement_path, "payload": response}]
        records = []
        for statement, statement_id, detail_responses, transactions in details:
            raw_responses.extend(
                {"endpoint": path, "payload": detail}
                for path, detail in detail_responses
            )
            for item in transactions:
                if not isinstance(item, dict):
                    continue
                transaction_id = _text(item.get("id"), item.get("transaction_id"))
                source_suffix = transaction_id or hashlib.sha256(
                    json.dumps(item, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
                ).hexdigest()
                records.append({
                    "source_key": f"{statement_id}:{source_suffix}",
                    "transaction_id": transaction_id,
                    "order_id": _text(item.get("order_id")),
                    "order_item_id": _text(item.get("order_item_id"), item.get("sku_order_id")),
                    "seller_sku": _text(item.get("seller_sku")),
                    "platform_variant_id": _text(item.get("sku_id")),
                    "fee_name": _text(item.get("type"), item.get("transaction_type"), "settlement_amount"),
                    "amount": item.get("settlement_amount", item.get("amount", item.get("transaction_amount"))),
                    "currency": _text(item.get("currency"), statement.get("currency")),
                    "occurred_at": item.get("create_time") or item.get("transaction_time")
                    or statement.get("statement_time") or statement.get("settlement_time"),
                })
        next_cursor = _next_time_window_cursor(
            scope, time_from, time_to, data.get("next_page_token"), windowed
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
                raise ValidationError(f"TikTok product detail response has no SKU list for product {product_id}.")
            for sku in skus:
                if not isinstance(sku, dict) or not _text(sku.get("id")):
                    raise ValidationError(f"TikTok product detail response has an invalid SKU for product {product_id}.")
                records.append(
                    {
                        "platform_product_id": product_id,
                        "platform_variant_id": _text(sku.get("id")),
                        "platform_sku": _text(sku.get("seller_sku")),
                        "source_old_sku_code": _text(sku.get("source_old_sku_code")),
                        "title": _text(product.get("title"), summary.get("title")),
                        "variant": _tiktok_variant_label(sku.get("sales_attributes")),
                        "sales_status": _text(product.get("status"), summary.get("status")),
                        "platform_created_at": product.get("create_time"),
                        "platform_updated_at": product.get("update_time"),
                        "category_l1": _text(product.get("category_id")),
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


def default_sync_scope(config, override=None, resource_type=None):
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
    lookback_days = max(1, min(int(scope.get("lookback_days") or 1), 30))
    start, end = now - timedelta(days=lookback_days), now
    uses_time_range = resource_type in {"sales_order", "refund_return", "settlement_bill"} or (
        resource_type == "platform_product" and not bool(scope.get("product_full_sync", True))
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
    return {
        "time_from": int(start.timestamp()),
        "time_to": int(end.timestamp()),
        "page_size": page_size,
        # Full product snapshots are the safe default.  A product job may
        # explicitly opt into the documented update-time window without
        # changing the order/refund query policy.
        "product_full_sync": bool(scope.get("product_full_sync", True)),
        "time_basis": time_basis,
        "statuses": statuses,
    }
