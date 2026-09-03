import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .capability import require_live_mode
from .custody import get_custody_backend
from .net_guard import PlatformHttpClient
from .production_settings import get_runtime_platform_config, get_runtime_setting


def _required(value, name):
    text = str(value or "").strip()
    if not text or text.startswith("REPLACE_ME"):
        raise ValidationError(f"Approved live configuration is missing: {name}.")
    return text


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _query_url(host, path, query):
    return f"{host.rstrip('/')}{path}?{urllib.parse.urlencode(query, doseq=True)}"


class ReadonlyClientBase:
    def __init__(self, config, authorization=None, http_client=None, custody=None, now=None):
        self.config = config
        self.authorization = authorization
        self.platform_config = dict(config.platform_config or {})
        self.http = http_client or PlatformHttpClient()
        self.custody = custody or get_custody_backend()
        self.now = now or timezone.now

    def _runtime_path(self, key, fallback):
        value = (get_runtime_platform_config(str(getattr(self.config, "platform", "") or "").lower()) or {}).get(key)
        return str(value or fallback)

    def preflight(self):
        require_live_mode(f"{self.config.platform} readonly synchronization")
        if not get_runtime_setting("network", "readonly_sync_enabled", default=False):
            raise ValidationError("Production readonly synchronization feature flag is disabled.")
        if self.config.environment not in {"pilot", "production"}:
            raise ValidationError("Readonly production synchronization requires pilot or production environment.")
        if self.config.status not in {"verified", "active"}:
            raise ValidationError("Integration config is not verified and active.")
        if not self.config.network_enabled or not self.config.sync_read_enabled:
            raise ValidationError("Integration config readonly network capability is disabled.")
        if not self.platform_config.get("contract_approved"):
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


class ShopeeReadonlyClient(ReadonlyClientBase):
    ORDER_LIST_PATH = settings.LIVE_SHOPEE_ORDER_LIST_PATH
    ORDER_DETAIL_PATH = settings.LIVE_SHOPEE_ORDER_DETAIL_PATH
    RETURN_LIST_PATH = settings.LIVE_SHOPEE_RETURN_LIST_PATH
    RETURN_DETAIL_PATH = settings.LIVE_SHOPEE_RETURN_DETAIL_PATH

    def _request(self, path, query):
        self.preflight()
        authorization = self.authorization
        if authorization is None or authorization.status != authorization.Status.ACTIVE:
            raise ValidationError("Shopee store authorization is not active.")
        if authorization.expires_at and authorization.expires_at <= self.now():
            raise ValidationError("SHOPEE_TOKEN_REFRESH_REQUIRED")
        host = _required(self.platform_config.get("api_host"), "shopee.api_host")
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
        response = self._request(
            order_list_path,
            {
                "time_range_field": "update_time",
                "time_from": scope["time_from"],
                "time_to": scope["time_to"],
                "page_size": scope["page_size"],
                **({"cursor": cursor} if cursor else {}),
                "response_optional_fields": "order_status",
            },
        )
        envelope = _as_dict(response.get("response"))
        raw_responses = [{"endpoint": order_list_path, "payload": response}]
        summaries = _as_list(envelope.get("order_list"))
        order_ids = [str(item.get("order_sn")) for item in summaries if isinstance(item, dict) and item.get("order_sn")]
        details = []
        for start in range(0, len(order_ids), 50):
            detail = self._request(
                order_detail_path,
                {
                    "order_sn_list": ",".join(order_ids[start : start + 50]),
                    "response_optional_fields": "item_list,payment_method,total_amount,shipping_carrier,package_list",
                },
            )
            raw_responses.append({"endpoint": order_detail_path, "payload": detail})
            details.extend(_as_list(_as_dict(detail.get("response")).get("order_list")))
        return {
            "records": details or summaries,
            "next_cursor": str(envelope.get("next_cursor") or ""),
            "raw_responses": raw_responses,
        }

    def fetch_returns(self, cursor, scope):
        return_list_path = self._runtime_path("return_list_path", self.RETURN_LIST_PATH)
        return_detail_path = self._runtime_path("return_detail_path", self.RETURN_DETAIL_PATH)
        page_no = int(cursor or 1)
        response = self._request(
            return_list_path,
            {
                "create_time_from": scope["time_from"],
                "create_time_to": scope["time_to"],
                "page_no": page_no,
                "page_size": scope["page_size"],
            },
        )
        envelope = _as_dict(response.get("response"))
        raw_responses = [{"endpoint": return_list_path, "payload": response}]
        summaries = _as_list(envelope.get("return")) or _as_list(envelope.get("return_list"))
        details = []
        for item in summaries:
            if not isinstance(item, dict):
                continue
            return_id = item.get("return_sn") or item.get("return_id")
            if not return_id:
                continue
            detail = self._request(return_detail_path, {"return_sn": return_id})
            raw_responses.append({"endpoint": return_detail_path, "payload": detail})
            detail_record = _as_dict(detail.get("response"))
            details.append({**item, **detail_record})
        has_more = bool(envelope.get("more") or envelope.get("has_more"))
        return {
            "records": details or summaries,
            "next_cursor": str(page_no + 1) if has_more else "",
            "raw_responses": raw_responses,
        }


class TikTokReadonlyClient(ReadonlyClientBase):
    ORDER_LIST_PATH = settings.LIVE_TIKTOK_ORDER_LIST_PATH
    ORDER_DETAIL_PATH = settings.LIVE_TIKTOK_ORDER_DETAIL_PATH
    RETURN_LIST_PATH = settings.LIVE_TIKTOK_RETURN_LIST_PATH

    def _request(self, path, *, query=None, body=None, method="GET"):
        self.preflight()
        authorization = self.authorization
        if authorization is None or authorization.status != authorization.Status.ACTIVE:
            raise ValidationError("TikTok Shop store authorization is not active.")
        if authorization.expires_at and authorization.expires_at <= self.now():
            raise ValidationError("TOKEN_EXPIRED_REAUTH_REQUIRED")
        host = _required(self.platform_config.get("api_host"), "tiktok.api_host")
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
        query = {
            "shop_cipher": self.authorization.shop_cipher,
            "page_size": scope["page_size"],
            **({"page_token": cursor} if cursor else {}),
        }
        payload = self._request(
            order_list_path,
            query=query,
            body={"create_time_ge": scope["time_from"], "create_time_lt": scope["time_to"]},
            method="POST",
        )
        data = _as_dict(payload.get("data"))
        raw_responses = [{"endpoint": order_list_path, "payload": payload}]
        summaries = _as_list(data.get("orders"))
        order_ids = [str(item.get("id")) for item in summaries if isinstance(item, dict) and item.get("id")]
        details = []
        for start in range(0, len(order_ids), 50):
            detail = self._request(
                order_detail_path,
                query={"shop_cipher": self.authorization.shop_cipher, "ids": ",".join(order_ids[start : start + 50])},
            )
            raw_responses.append({"endpoint": order_detail_path, "payload": detail})
            details.extend(_as_list(_as_dict(detail.get("data")).get("orders")))
        return {
            "records": details or summaries,
            "next_cursor": str(data.get("next_page_token") or ""),
            "raw_responses": raw_responses,
        }

    def fetch_returns(self, cursor, scope):
        return_list_path = self._runtime_path("return_list_path", self.RETURN_LIST_PATH)
        query = {
            "shop_cipher": self.authorization.shop_cipher,
            "page_size": min(50, scope["page_size"]),
            **({"page_token": cursor} if cursor else {}),
        }
        payload = self._request(
            return_list_path,
            query=query,
            body={"create_time_ge": scope["time_from"], "create_time_lt": scope["time_to"]},
            method="POST",
        )
        data = _as_dict(payload.get("data"))
        records = _as_list(data.get("return_orders")) or _as_list(data.get("returns"))
        return {
            "records": records,
            "next_cursor": str(data.get("next_page_token") or ""),
            "raw_responses": [{"endpoint": return_list_path, "payload": payload}],
        }


class JifengWmsReadonlyClient(ReadonlyClientBase):
    INVENTORY_PATH = settings.LIVE_JIFENG_WMS_INVENTORY_PATH

    def fetch_inventory(self, cursor, scope):
        self.preflight()
        site = str(self.platform_config.get("site_code") or "").upper()
        if site not in {"PH", "TH", "MY"}:
            raise ValidationError("Jifeng WMS site must be PH, TH, or MY.")
        host = _required(self.platform_config.get("api_host"), f"jifeng_wms.{site}.api_host")
        client_id = _required(self.platform_config.get("client_id"), f"jifeng_wms.{site}.client_id")
        user_id = _required(self.platform_config.get("user_id"), f"jifeng_wms.{site}.user_id")
        warehouse_code = _required(self.platform_config.get("warehouse_code"), "jifeng_wms.warehouse_code")
        client_secret = self.custody.retrieve_secret(_required(self.config.credential_id, "jifeng_wms.credential_id"))
        access_token = self.custody.retrieve_access_token(_required(self.config.token_id, "jifeng_wms.token_id"))
        timestamp = str(int(self.now().timestamp() * 1000))
        nonce = str(secrets.randbelow(10**12)).zfill(12)
        sign_values = {
            "accessToken": access_token,
            "clientId": client_id,
            "method": "post",
            "nonce": nonce,
            "timestamp": timestamp,
            "url": self.INVENTORY_PATH,
            "userId": user_id,
        }
        sign_input = "&".join(f"{key}={sign_values[key]}" for key in sorted(sign_values))
        signature = hmac.new(client_secret.encode(), sign_input.encode(), hashlib.sha256).hexdigest()
        page_no = int(cursor or 1)
        body = {"pageNo": page_no, "pageSize": scope["page_size"], "warehouse": warehouse_code}
        response = self.http.request(
            "POST",
            f"{host.rstrip('/')}{self.INVENTORY_PATH}",
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
        payload = self._response_json(response)
        if int(payload.get("code") or 0) not in {0, 200}:
            raise ValidationError("Jifeng WMS rejected the readonly request.")
        data = payload.get("data")
        page = _as_dict(_as_dict(data).get("page"))
        source = page or _as_dict(data)
        records = []
        for name in ("list", "records", "items", "rows", "content"):
            if isinstance(source.get(name), list):
                records = source[name]
                break
        total_page = int(page.get("totalPage") or page_no)
        snapshot_at = self.now().isoformat()
        return {
            "records": [{**item, "_snapshot_at_utc": snapshot_at} for item in records if isinstance(item, dict)],
            "next_cursor": str(page_no + 1) if page_no < total_page else "",
            "raw_responses": [{"endpoint": self.INVENTORY_PATH, "payload": payload}],
        }


def default_sync_scope(config):
    scope = dict((config.platform_config or {}).get("sync_scope") or {})
    now = timezone.now()
    lookback_days = max(1, min(int(scope.get("lookback_days") or 1), 30))
    page_size = max(1, min(int(scope.get("page_size") or 50), 100))
    return {
        "time_from": int((now - timedelta(days=lookback_days)).timestamp()),
        "time_to": int(now.timestamp()),
        "page_size": page_size,
    }
