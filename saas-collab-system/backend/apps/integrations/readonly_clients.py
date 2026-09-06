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

from apps.common.module_gate import is_module_enabled

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
            raise ValidationError("Production readonly synchronization feature flag is disabled.")
        if self.config.environment not in {"pilot", "production"}:
            raise ValidationError("Readonly production synchronization requires pilot or production environment.")
        if self.config.status not in {"verified", "active"}:
            raise ValidationError("Integration config is not verified and active.")
        if not self.config.network_enabled or not self.config.sync_read_enabled:
            raise ValidationError("Integration config readonly network capability is disabled.")
        contract_key = (
            "product_contract_approved"
            if self.resource_type == "platform_product"
            else "contract_approved"
        )
        # Product contract approval is a system-admin versioned runtime
        # setting.  It is intentionally independent from the tenant config's
        # legacy order/return contract flag.  Existing resources retain their
        # historical check below.
        approval_config = (
            get_runtime_platform_config(str(getattr(self.config, "platform", "") or "").lower())
            if contract_key == "product_contract_approved"
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


class ShopeeReadonlyClient(ReadonlyClientBase):
    ORDER_LIST_PATH = settings.LIVE_SHOPEE_ORDER_LIST_PATH
    ORDER_DETAIL_PATH = settings.LIVE_SHOPEE_ORDER_DETAIL_PATH
    RETURN_LIST_PATH = settings.LIVE_SHOPEE_RETURN_LIST_PATH
    RETURN_DETAIL_PATH = settings.LIVE_SHOPEE_RETURN_DETAIL_PATH
    PRODUCT_LIST_PATH = settings.LIVE_SHOPEE_PRODUCT_LIST_PATH
    PRODUCT_BASE_INFO_PATH = settings.LIVE_SHOPEE_PRODUCT_BASE_INFO_PATH
    PRODUCT_MODEL_LIST_PATH = settings.LIVE_SHOPEE_PRODUCT_MODEL_LIST_PATH
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

        base_by_id = {}
        for start in range(0, len(item_ids), 50):
            base_response = self._request(base_path, {"item_id_list": item_ids[start : start + 50]})
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
                model_response = self._request(model_path, {"item_id": item_id})
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
        records = []
        for summary in summaries:
            if not isinstance(summary, dict):
                raise ValidationError("TikTok product search response contains an invalid product summary.")
            product_id = _text(summary.get("id"), summary.get("product_id"))
            if not product_id:
                raise ValidationError("TikTok product search response contains a product without id.")
            summary_status = _text(summary.get("status"), summary.get("product_status")).upper()
            if summary_status in self.DETAIL_UNAVAILABLE_STATUSES:
                records.extend(self._status_only_records(summary, product_id, summary_status))
                # The Search Products page remains complete and can advance
                # its opaque cursor even when a detail endpoint cannot serve a
                # tombstone.  Ingestion updates only exact existing variants;
                # unknown/missing variants are audited skips.
                continue
            path = detail_path.format(product_id=urllib.parse.quote(product_id, safe=""))
            detail = self._request(
                path,
                query={"shop_cipher": self.authorization.shop_cipher},
            )
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

    def fetch_inventory(self, cursor, scope):
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
        user_id = _required(self.platform_config.get("user_id"), f"jifeng_wms.{site}.user_id")
        # The warehouse query parameter belongs to the selected binding, not
        # to the shared API config.  Keep a legacy config fallback for older
        # pilot records, while production bindings should carry the explicit
        # provider-issued code.
        warehouse_code = _required(
            getattr(authorization, "external_warehouse_code", "") or self.platform_config.get("warehouse_code"),
            "jifeng_wms.external_warehouse_code",
        )
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


def default_sync_scope(config, override=None):
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
    page_size = max(1, min(int(scope.get("page_size") or 50), 100))
    # SyncJob stores the provider-neutral policy as query.statuses.  Preserve
    # it in the runtime scope so each client can map it to its own verified
    # request shape (Shopee query.item_status; TikTok JSON body.status).
    raw_statuses = scope.get("statuses", scope.get("query_statuses"))
    statuses = _status_values(raw_statuses)
    return {
        "time_from": int((now - timedelta(days=lookback_days)).timestamp()),
        "time_to": int(now.timestamp()),
        "page_size": page_size,
        # Full product snapshots are the safe default.  A product job may
        # explicitly opt into the documented update-time window without
        # changing the order/refund query policy.
        "product_full_sync": bool(scope.get("product_full_sync", True)),
        "statuses": statuses,
    }
