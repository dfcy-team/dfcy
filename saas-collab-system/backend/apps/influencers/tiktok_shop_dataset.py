"""Bounded, credential-free TikTok Shop export artifacts for a reviewed trial."""

import hashlib
import json
import os
import time as retry_time
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from billiard.exceptions import SoftTimeLimitExceeded

from django.utils import timezone

from apps.integrations.production_settings import get_runtime_platform_config
from apps.integrations.readonly_clients import TikTokReadonlyClient
from .settlement import normalize_settlement_status


KINDS = frozenset({"affiliate_orders", "creators", "videos"})
MAX_ARTIFACT_BYTES = 200 * 1024 * 1024
AFFILIATE_MONEY_FIELDS = (
    "price", "estimated_commission_base", "estimated_paid_commission", "actual_commission_base",
    "actual_paid_commission", "actual_paid_shop_ads_commission",
)
AFFILIATE_CONTRACT_VERSION = "affiliate-daily-v3"
AFFILIATE_COUNT_UNIT = "sku_row"


class DatasetError(ValueError):
    """Only fixed diagnostic codes, never provider messages or signed URLs."""


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _text(value, maximum=255):
    if value is None:
        return ""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise DatasetError("invalid_text")
    value = str(value).strip()
    if len(value) > maximum:
        raise DatasetError("oversized_text")
    return value


def _number(value, integer=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DatasetError("invalid_number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise DatasetError("invalid_number") from exc
    if not number.is_finite() or number < 0:
        raise DatasetError("invalid_number")
    if integer:
        if number != number.to_integral_value() or number > 2**63 - 1:
            raise DatasetError("invalid_integer")
        return int(number)
    return str(number)


def _money(value):
    if value is None:
        return {"amount": None, "currency": None}
    if not isinstance(value, dict):
        raise DatasetError("invalid_money")
    currency = _text(value.get("currency"), 3).upper() or None
    if currency and (len(currency) != 3 or not currency.isalpha() or not currency.isascii()):
        raise DatasetError("invalid_currency")
    return {"amount": _number(value.get("amount")), "currency": currency}


def validate_window(start_date, end_date, *, today=None):
    start, end = date.fromisoformat(str(start_date)), date.fromisoformat(str(end_date))
    if start > end or (end - start).days >= 7:
        raise DatasetError("trial_window_must_be_one_to_seven_days")
    if today is not None and end >= today:
        raise DatasetError("only_completed_shop_days_allowed")
    return start, end


def project_order(order, sku):
    if not isinstance(order, dict) or not isinstance(sku, dict):
        raise DatasetError("invalid_affiliate_row")
    payload = {name: _text(sku.get(name), 160) for name in (
        "sku_id", "product_id", "creator_username", "content_id", "content_type", "commission_model",
    )}
    payload.update(order_id=_text(order.get("id"), 160), create_time=_number(order.get("create_time"), True),
                   quantity=_number(sku.get("quantity"), True), fully_return=_text(sku.get("fully_return"), 20) or None,
                   commission_rate=_number(sku.get("commission_rate")))
    try:
        payload["settlement_status"] = normalize_settlement_status(sku.get("settlement_status"))
    except ValueError:
        raise DatasetError("unknown_settlement_status") from None
    for field in AFFILIATE_MONEY_FIELDS:
        payload[field] = _money(sku.get(field))
    ads = payload["actual_paid_shop_ads_commission"]
    sku_currencies = {
        payload[field]["currency"] for field in AFFILIATE_MONEY_FIELDS
        if field != "actual_paid_shop_ads_commission"
        and (payload[field]["amount"] is not None or payload[field]["currency"] is not None)
    }
    if (
        ads["amount"] is not None and ads["currency"] is None
        or ads["currency"] is not None and any(value != ads["currency"] for value in sku_currencies)
    ):
        raise DatasetError("affiliate_currency_mismatch")
    # Commission bases are not automatically the order's payment or GMV.
    payload["payment_amount"] = None
    payload["canonical_import_blocker"] = "sku_payment_semantics_not_verified"
    return payload


def project_creator(creator, creator_id, influencer_id):
    if not isinstance(creator, dict):
        raise DatasetError("creator_profile_missing")
    return {"external_influencer_id": creator_id, "influencer_id": influencer_id,
            "username": _text(creator.get("username"), 255), "nickname": _text(creator.get("nickname"), 160),
            "follower_count": _number(creator.get("follower_count"), True),
            "selection_region": _text(creator.get("selection_region"), 8),
            "canonical_import_blocker": "creator_snapshot_dependency_not_in_main"}


def _published_time(value):
    if value in (None, ""):
        return None, None
    if isinstance(value, str) and len(value) == 19 and value[10] == " ":
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise DatasetError("invalid_video_post_time") from None
        if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
            raise DatasetError("invalid_video_post_time")
        # The API supplies no offset here. Preserve the source, not a guessed UTC instant.
        return None, value
    try:
        seconds = _number(value, True)
        return datetime.fromtimestamp(seconds, tz=UTC).isoformat(), None
    except (DatasetError, OverflowError, OSError, ValueError):
        raise DatasetError("invalid_video_post_time") from None


def project_video(video, metric_date):
    if not isinstance(video, dict):
        raise DatasetError("invalid_video_row")
    creator = video.get("creator") or {}
    performance = video.get("total_performance")
    if performance is None:
        performance = video
    if not isinstance(creator, dict) or not isinstance(performance, dict):
        raise DatasetError("invalid_video_shape")
    video_id = _text(video.get("video_id"), 160)
    list_id = _text(video.get("id"), 160)
    if video_id and list_id and video_id != list_id:
        raise DatasetError("conflicting_video_identifiers")
    metrics = {}
    for field in ("views", "likes", "comments", "shares", "orders", "sku_orders", "items_sold", "product_impressions", "product_clicks", "unique_customers", "customers"):
        metrics[field] = _number(performance.get(field), True)
    for field in ("gmv", "direct_gmv", "indirect_gmv", "gpm"):
        metrics[field] = _money(performance.get(field))
    published_at, source_published_at = _published_time(video.get("video_post_time"))
    return {"external_video_id": video_id or list_id,
            "creator_open_id": _text(creator.get("open_id"), 160),
            "creator_username": _text(creator.get("user_name"), 160),
            "creator_nickname": _text(creator.get("nick_name"), 160),
            "author_type": _text(creator.get("author_type"), 30),
            "title": _text(video.get("title"), 8192), "published_at": published_at,
            "source_published_at": source_published_at,
            "metric_date": metric_date, "currency": metrics["gmv"]["currency"], "metrics": metrics,
            "canonical_metric_blocker": "nullable_daily_metric_contract_required"}


class TikTokDatasetClient(TikTokReadonlyClient):
    """Reuse custody, signed requests and approved network gates; no renewal."""

    request_count = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The guarded transport otherwise retries HTTP/provider failures too.
        self.http.max_retries = 0

    def _request(self, *args, **kwargs):
        self.request_count += 1
        return super()._request(*args, **kwargs)

    def _response_json(self, response):
        payload = super()._response_json(response)
        code = payload.get("code")
        if type(code) not in (int, str) or str(code) != "0" or not isinstance(payload.get("data"), dict):
            safe_code = str(code) if type(code) in (int, str) and str(code).isascii() and str(code).isdecimal() else "invalid_envelope"
            raise DatasetError("provider_" + safe_code)
        return payload

    def _require_scope(self, scope):
        if scope not in (self.authorization.scopes or []):
            raise DatasetError("scope_not_authorized:" + scope)

    def verify_shop(self):
        self._require_scope("seller.authorization.info")
        shops = self._request("/authorization/202309/shops")["data"].get("shops")
        if not isinstance(shops, list):
            raise DatasetError("authorized_shops_missing")
        matches = [shop for shop in shops if isinstance(shop, dict)
                   and str(shop.get("id")) == self.authorization.platform_store_id
                   and shop.get("cipher") == self.authorization.shop_cipher]
        if len(matches) != 1:
            raise DatasetError("authorized_shop_identity_mismatch")

    def _transport_request(self, *args, **kwargs):
        for attempt in range(3):
            try:
                return self._request(*args, **kwargs)
            except (TimeoutError, SoftTimeLimitExceeded):
                raise
            except Exception as exc:
                transient = isinstance(exc, ConnectionError) or (
                    getattr(exc, "category", None) in {"timeout_uncertain", "network_uncertain"})
                if not transient or attempt == 2:
                    raise
                retry_time.sleep(0.1 * (attempt + 1))

    def _collect_affiliate_sku_pages(self, path, field, *, query, body, project, max_pages, staging, checkpoint):
        token, seen_tokens, seen_skus, rows, total, parent_times = "", set(), set(), [], None, {}
        self.last_page_summary = {}
        for page in range(1, max_pages + 1):
            descriptor = {"store_id": self.authorization.store_id, "path": path, "field": field,
                          "query": query, "body": body, "page": page,
                          "version": AFFILIATE_CONTRACT_VERSION, "count_unit": AFFILIATE_COUNT_UNIT}
            saved = checkpoint.load(descriptor) if checkpoint else None
            if saved is not None:
                required = {"version", "count_unit", "input_token", "next_token", "total", "rows",
                            "source_count", "parent_headers", "sku_row_count", "unique_sku_count", "observed_at"}
                if (not isinstance(saved, dict) or not required <= saved.keys()
                        or saved["version"] != AFFILIATE_CONTRACT_VERSION
                        or saved["count_unit"] != AFFILIATE_COUNT_UNIT):
                    raise DatasetError("affiliate_checkpoint_proof_required")
                if saved["input_token"] != token:
                    raise DatasetError("checkpoint_cursor_mismatch")
                values, headers = saved["rows"], saved["parent_headers"]
                observed_at, current_total, next_token = saved["observed_at"], saved["total"], saved["next_token"]
                if (not isinstance(values, list) or not isinstance(headers, list)
                        or type(saved["source_count"]) is not int or not 0 <= saved["source_count"] <= 50
                        or len(headers) != saved["source_count"]
                        or any(type(saved[key]) is not int or saved[key] != len(values)
                               for key in ("sku_row_count", "unique_sku_count"))):
                    raise DatasetError("affiliate_checkpoint_count_mismatch")
            else:
                params = {"shop_cipher": self.authorization.shop_cipher, "page_size": 50, **query}
                if token:
                    params["page_token"] = token
                request = self._transport_request if staging else self._request
                data = request(path, query=params, body=body, method="POST" if body is not None else "GET")["data"]
                values = data.get(field)
                if not isinstance(values, list) or len(values) > 50:
                    raise DatasetError("affiliate_page_records_invalid")
                observed_at, current_total = timezone.now().isoformat(), data.get("total_count")
                next_token = data.get("next_page_token") or ""
                headers = []
                for value in values:
                    if not isinstance(value, dict) or not isinstance(value.get("skus"), list) or not value["skus"]:
                        raise DatasetError("affiliate_skus_missing")
                    headers.append({"order_id": _text(value.get("id"), 160),
                                    "create_time": _number(value.get("create_time"), True),
                                    "sku_count": len(value["skus"])})
            if type(current_total) is not int or not 0 <= current_total <= 2**63 - 1:
                raise DatasetError("affiliate_total_count_required")
            if total is not None and total != current_total:
                raise DatasetError("page_total_changed")
            total = current_total
            try:
                observed_time = datetime.fromisoformat(observed_at)
            except (ValueError, TypeError):
                raise DatasetError("affiliate_observation_required") from None
            if timezone.is_naive(observed_time):
                raise DatasetError("affiliate_observation_required")
            expected_counts = {}
            for header in headers:
                if (not isinstance(header, dict) or set(header) != {"order_id", "create_time", "sku_count"}
                        or not isinstance(header["order_id"], str) or not header["order_id"]
                        or _text(header["order_id"], 160) != header["order_id"]
                        or type(header["create_time"]) is not int or not 0 <= header["create_time"] <= 2**63 - 1
                        or type(header["sku_count"]) is not int or header["sku_count"] < 1):
                    raise DatasetError("affiliate_parent_header_required")
                parent = header["order_id"]
                if parent in parent_times and parent_times[parent] != header["create_time"]:
                    raise DatasetError("affiliate_parent_header_conflict")
                parent_times[parent] = header["create_time"]
                expected_counts[parent] = expected_counts.get(parent, 0) + header["sku_count"]
            page_rows, observed_counts = [], {}
            for value in values:
                if not isinstance(value, dict):
                    raise DatasetError("invalid_page_record")
                projected = [value] if saved is not None else [project(value, sku) for sku in value["skus"]]
                for item in projected:
                    identity = [item.get(key) for key in ("order_id", "sku_id", "product_id")]
                    if any(not isinstance(key, str) or not key or _text(key, 160) != key for key in identity):
                        raise DatasetError("affiliate_identity_missing")
                    parent = identity[0]
                    if (parent not in expected_counts or type(item.get("create_time")) is not int
                            or item["create_time"] != parent_times[parent]):
                        raise DatasetError("affiliate_checkpoint_parent_mismatch")
                    if saved is not None and item.get("affiliate_observed_at") != observed_at:
                        raise DatasetError("affiliate_checkpoint_observation_mismatch")
                    key = tuple(identity[:2])
                    if key in seen_skus:
                        raise DatasetError("affiliate_duplicate_order_sku")
                    seen_skus.add(key)
                    observed_counts[parent] = observed_counts.get(parent, 0) + 1
                    page_rows.append({**item, "affiliate_observed_at": observed_at})
            if observed_counts != expected_counts:
                raise DatasetError("affiliate_checkpoint_parent_mismatch")
            rows.extend(page_rows)
            if len(rows) > total:
                raise DatasetError("pagination_total_mismatch")
            if not isinstance(next_token, str) or _text(next_token, 4096) != next_token:
                raise DatasetError("affiliate_page_token_invalid")
            if next_token and (not values or next_token in seen_tokens):
                raise DatasetError("pagination_not_advancing")
            if checkpoint and saved is None:
                checkpoint.save(descriptor, {"version": AFFILIATE_CONTRACT_VERSION, "count_unit": AFFILIATE_COUNT_UNIT,
                    "rows": page_rows, "input_token": token, "next_token": next_token, "total": total,
                    "source_count": len(headers), "parent_headers": headers, "sku_row_count": len(page_rows),
                    "unique_sku_count": len(page_rows), "observed_at": observed_at})
            if not next_token:
                if len(rows) != total:
                    raise DatasetError("pagination_total_mismatch")
                self.last_page_summary = {"version": AFFILIATE_CONTRACT_VERSION, "count_unit": AFFILIATE_COUNT_UNIT,
                    "status": "complete", "reason": "pagination_exhausted", "expected_count": total,
                    "observed_count": len(rows), "sku_row_count": len(rows), "unique_sku_count": len(seen_skus),
                    "parent_count": len(parent_times), "page_count": page, "pagination_exhausted": True}
                return rows, page
            seen_tokens.add(next_token)
            token = next_token
        raise DatasetError("pagination_limit_exceeded")

    def collect_pages(self, path, field, *, query, body=None, project, max_pages=100, sku_total=False,
                      staging=False, checkpoint=None):
        if not 1 <= max_pages <= 100:
            raise DatasetError("invalid_page_limit")
        if sku_total and getattr(self, "strict_affiliate_contract", False):
            return self._collect_affiliate_sku_pages(path, field, query=query, body=body, project=project,
                max_pages=max_pages, staging=staging, checkpoint=checkpoint)
        token, seen_tokens, seen_rows, rows, total, source_records = "", set(), set(), [], None, 0
        for page in range(1, max_pages + 1):
            params = {"shop_cipher": self.authorization.shop_cipher, "page_size": 50, **query}
            if token:
                params["page_token"] = token
            descriptor = {"store_id": self.authorization.store_id, "path": path, "field": field,
                          "query": query, "body": body, "page": page} if checkpoint else None
            saved = checkpoint.load(descriptor) if checkpoint else None
            if saved is not None and saved.get("input_token") != token:
                raise DatasetError("checkpoint_cursor_mismatch")
            if saved is None:
                request = self._transport_request if staging else self._request
                data = request(path, query=params, body=body, method="POST" if body is not None else "GET")["data"]
                values = data.get(field)
            else:
                data = {"next_page_token": saved["next_token"]}
                if saved["total"] is not None:
                    data["total_count"] = saved["total"]
                values = saved["rows"]
            if not isinstance(values, list):
                raise DatasetError("page_records_missing")
            if not isinstance(values, list):
                raise DatasetError("page_records_missing")
            if saved is None and len(values) > 50:
                raise DatasetError("page_record_limit_exceeded")
            source_records += saved["source_count"] if saved is not None else len(values)
            if "total_count" in data:
                current_total = _number(data["total_count"], True)
                if current_total is None or (total is not None and total != current_total):
                    raise DatasetError("page_total_changed")
                total = current_total
            page_rows = []
            for value in values:
                if not isinstance(value, dict):
                    raise DatasetError("invalid_page_record")
                if saved is not None:
                    projected = [value]
                elif sku_total:
                    skus = value.get("skus")
                    if not isinstance(skus, list) or not skus:
                        raise DatasetError("affiliate_skus_missing")
                    projected = [project(value, sku) for sku in skus]
                else:
                    projected = [project(value)]
                for item in projected:
                    if sku_total:
                        identity = [item[key] for key in ("order_id", "sku_id", "product_id", "creator_username", "content_id", "commission_model")]
                        if not all(identity[:3]):
                            raise DatasetError("affiliate_identity_missing")
                    else:
                        identity = item.get("external_video_id")
                        if not identity:
                            raise DatasetError("video_identity_missing")
                    key = canonical_bytes(identity)
                    if key in seen_rows:
                        raise DatasetError("duplicate_page_identity")
                    seen_rows.add(key)
                    rows.append(item)
                    page_rows.append(item)
            next_token = _text(data.get("next_page_token"), 4096)
            if next_token and (not values or next_token in seen_tokens):
                raise DatasetError("pagination_not_advancing")
            if checkpoint and saved is None:
                checkpoint.save(descriptor, {"rows": page_rows, "input_token": token, "next_token": next_token,
                                            "source_count": len(values), "total": total})
            token = next_token
            if not token:
                # Affiliate total_count units vary across contracts. Require an
                # exact observed order or SKU count, without declaring either GMV.
                observed_counts = {len(rows), source_records} if sku_total else {len(rows)}
                if total is not None and total not in observed_counts:
                    if not staging or sku_total:
                        raise DatasetError("pagination_total_mismatch")
                self.last_page_summary = {"status": "partial" if total is not None and total not in observed_counts else "complete",
                    "reason": "pagination_total_mismatch" if total is not None and total not in observed_counts else "pagination_exhausted",
                    "expected_count": total, "observed_count": len(rows), "page_count": page, "pagination_exhausted": True}
                return rows, page
            if not values or token in seen_tokens:
                raise DatasetError("pagination_not_advancing")
            seen_tokens.add(token)
        raise DatasetError("pagination_limit_exceeded")

    def affiliate_orders(self, start, end, zone, *, staging=False, checkpoint=None):
        self.resource_type = None
        self._require_scope("seller.affiliate_collaboration.read")
        begin = int(datetime.combine(start, time.min, tzinfo=zone).timestamp())
        finish = int(datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone).timestamp())

        def project_window_order(order, sku):
            if getattr(self, "strict_affiliate_money", False) and any(
                isinstance(sku.get(field), dict) and isinstance(sku[field].get("amount"), (float, bool))
                for field in AFFILIATE_MONEY_FIELDS
            ):
                raise DatasetError("affiliate_money_must_be_exact_decimal")
            row = project_order(order, sku)
            if row["create_time"] is None or not begin <= row["create_time"] < finish:
                raise DatasetError("affiliate_row_outside_verified_window")
            return row

        rows, pages = self.collect_pages("/affiliate_seller/202410/orders/search", "orders", query={},
                                         body={"create_time_ge": begin, "create_time_lt": finish},
                                         project=project_window_order, sku_total=True, staging=staging, checkpoint=checkpoint)
        if any(row["create_time"] is None or not begin <= row["create_time"] < finish for row in rows):
            raise DatasetError("affiliate_row_outside_verified_window")
        return rows, pages

    def video_day(self, day, *, staging=False, checkpoint=None):
        self.resource_type = None
        self._require_scope("data.shop_analytics.public.read")
        return self.collect_pages("/analytics/202605/shop_videos/performance", "videos",
                                  query={"start_date_ge": day.isoformat(), "end_date_lt": (day + timedelta(days=1)).isoformat(), "currency": "LOCAL"},
                                  project=lambda value: project_video(value, day.isoformat()), staging=staging, checkpoint=checkpoint)

    def enrich_orders(self, rows, *, checkpoint=None):
        ids = sorted({row["order_id"] for row in rows})
        evidence = {}
        self.resource_type = "sales_order"
        try:
            self._require_scope("seller.order.info")
            path = self._runtime_path("order_detail_path", self.ORDER_DETAIL_PATH)
            self.preflight()
        except (TimeoutError, SoftTimeLimitExceeded):
            raise
        except Exception:
            path = None
        for offset in range(0, len(ids), 50):
            batch = ids[offset:offset + 50]
            descriptor = {"store_id": self.authorization.store_id, "kind": "ordinary_order_detail", "ids": batch, "path": path}
            saved = checkpoint.load(descriptor) if checkpoint and path else None
            if saved is not None:
                evidence.update(saved)
                continue
            if path is None:
                continue
            try:
                orders = self._transport_request(path, query={"shop_cipher": self.authorization.shop_cipher,
                                                               "ids": ",".join(batch)})["data"].get("orders")
                if not isinstance(orders, list):
                    raise DatasetError("order_details_missing")
                projected = {}
                for order in orders:
                    if not isinstance(order, dict):
                        raise DatasetError("invalid_order_detail_identity")
                    order_id = _text(order.get("id"), 160)
                    if order_id not in batch or order_id in projected:
                        raise DatasetError("invalid_order_detail_identity")
                    payment = order.get("payment") or {}
                    amount = payment.get("total_amount")
                    money = _money({"amount": None if amount == "" else amount, "currency": payment.get("currency")})
                    prices, line_ids = {}, set()
                    for sku in order.get("line_items", []):
                        if not isinstance(sku, dict):
                            raise DatasetError("invalid_order_detail_identity")
                        sku_id = _text(sku.get("sku_id"), 160)
                        if not sku_id:
                            raise DatasetError("invalid_order_detail_identity")
                        line_id = _text(sku.get("id"), 160)
                        if line_id and line_id in line_ids:
                            raise DatasetError("invalid_order_detail_identity")
                        if line_id:
                            line_ids.add(line_id)
                        price = _money({"amount": sku.get("sale_price"), "currency": money["currency"]})
                        if sku_id in prices and prices[sku_id] != price:
                            # Conflicting prices cannot prove one SKU unit price.
                            prices[sku_id] = {"amount": None, "currency": money["currency"]}
                        else:
                            prices[sku_id] = price
                    projected[order_id] = {"payment": money, "prices": prices}
                evidence.update(projected)
                if checkpoint and set(projected) == set(batch):
                    checkpoint.save(descriptor, projected)
            except (TimeoutError, SoftTimeLimitExceeded):
                raise
            except DatasetError as exc:
                if str(exc) == "invalid_order_detail_identity":
                    raise
            except Exception:
                pass
        for row in rows:
            detail = evidence.get(row["order_id"])
            payment = detail["payment"] if detail else {"amount": None, "currency": None}
            row["order_payment"] = {**payment, "status": "matched" if detail and payment["amount"] is not None else "missing",
                                    "source": "ordinary_order_detail"}
            if detail and row["price"]["amount"] is None:
                price = detail["prices"].get(row["sku_id"])
                if price is not None and price["amount"] is not None:
                    row["price"] = price
                    row["product_price_source"] = "ordinary_order_detail"

    def creator(self, creator_id, influencer_id, *, staging=False):
        if not creator_id.isascii() or not creator_id.isdecimal() or not 1 <= len(creator_id) <= 20 or int(creator_id) == 0:
            raise DatasetError("untrusted_creator_id")
        runtime = get_runtime_platform_config("tiktok")
        if not runtime.get("affiliate_seller_creator_read_approved"):
            raise DatasetError("creator_read_contract_not_approved")
        self.resource_type = "affiliate_creator_profile"
        self._require_scope("seller.creator_marketplace.read")
        request = self._transport_request if staging else self._request
        data = request(f"/affiliate_seller/202406/marketplace_creators/{creator_id}",
                             query={"shop_cipher": self.authorization.shop_cipher, "data_groups": "BASIC_CREATOR_INFORMATION"})["data"]
        return project_creator(data.get("creator"), creator_id, influencer_id)


def _write_new(path, content):
    if len(content) + sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file()) > MAX_ARTIFACT_BYTES:
        raise DatasetError("artifact_size_exceeded")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)


def export_artifact(*, output_dir, actor, authorizations, start_date, end_date, creator_seeds, client_factory=TikTokDatasetClient,
                    staging=False, resume=False, enrich_orders=False):
    if resume and not staging or enrich_orders and not staging:
        raise DatasetError("staging_required")
    if staging:
        return _export_staging(output_dir=output_dir, actor=actor, authorizations=authorizations, start_date=start_date,
                               end_date=end_date, creator_seeds=creator_seeds, client_factory=client_factory,
                               resume=resume, enrich_orders=enrich_orders)
    start, end = validate_window(start_date, end_date)
    root = Path(output_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "tenant_id": actor.tenant_id, "start_date": start.isoformat(), "end_date": end.isoformat(),
                "created_at": timezone.now().isoformat(), "stores": [], "components": [],
                "creator_selection": "existing_trusted_id_subset_not_date_filtered", "creator_limit": len(creator_seeds)}
    for auth in authorizations:
        zone = ZoneInfo(auth.store.timezone)
        validate_window(start, end, today=timezone.now().astimezone(zone).date())
        manifest["stores"].append({"store_id": auth.store_id, "store_code": auth.store.code,
                                   "platform_shop_id": auth.platform_store_id, "timezone": str(zone)})
        client = client_factory(auth.integration_config, auth)
        identity_reason = ""
        try:
            client.verify_shop()
        except (TimeoutError, SoftTimeLimitExceeded):
            raise
        except Exception as exc:
            identity_reason = str(exc) if isinstance(exc, DatasetError) else "shop_identity_not_verified"
        for kind in sorted(KINDS):
            component = {"kind": kind, "store_id": auth.store_id, "status": "failed", "row_count": 0, "request_count": 0}
            requests_before = getattr(client, "request_count", 0)
            try:
                if identity_reason:
                    raise DatasetError(identity_reason)
                if kind == "affiliate_orders":
                    payloads, count = client.affiliate_orders(start, end, zone)
                elif kind == "creators":
                    payloads = [client.creator(creator_id, influencer_id) for creator_id, influencer_id in creator_seeds]
                    count = len(creator_seeds)
                else:
                    payloads, count, day = [], 0, start
                    while day <= end:
                        values, pages = client.video_day(day)
                        payloads.extend(values)
                        count += pages
                        day += timedelta(days=1)
                filename = f"store-{auth.store_id}-{kind}.jsonl"
                content = b"".join(canonical_bytes({"kind": kind, "tenant_id": actor.tenant_id, "store_id": auth.store_id,
                                                   "store_code": auth.store.code, "payload": payload}) + b"\n" for payload in payloads)
                _write_new(root / filename, content)
                component.update(status="complete", file=filename, sha256=digest_bytes(content), row_count=len(payloads), request_count=count)
            except (TimeoutError, SoftTimeLimitExceeded):
                raise
            except Exception as exc:
                component["reason"] = str(exc) if isinstance(exc, DatasetError) else "request_failed_no_data_assumed"
                component["request_count"] = getattr(client, "request_count", 0) - requests_before
            manifest["components"].append(component)
    content = canonical_bytes(manifest) + b"\n"
    _write_new(root / "manifest.json", content)
    return manifest, digest_bytes(content)


def _export_staging(*, output_dir, actor, authorizations, start_date, end_date, creator_seeds,
                    client_factory, resume, enrich_orders):
    from .tiktok_dataset_checkpoint import DatasetCheckpoint

    start, end = validate_window(start_date, end_date)
    authorizations = list(authorizations)
    if not 1 <= len(authorizations) <= 2 or not 0 <= len(creator_seeds) <= 20:
        raise DatasetError("invalid_trial_scope")
    if len({seed[0] for seed in creator_seeds}) != len(creator_seeds):
        raise DatasetError("duplicate_creator_identity")
    stores = []
    bindings = []
    for auth in authorizations:
        if auth.store_id in {store["store_id"] for store in stores}:
            raise DatasetError("duplicate_manifest_store")
        zone = ZoneInfo(auth.store.timezone)
        validate_window(start, end, today=timezone.now().astimezone(zone).date())
        stores.append({"store_id": auth.store_id, "store_code": auth.store.code,
                       "platform_shop_id": auth.platform_store_id, "timezone": str(zone)})
        bindings.append({"store_id": auth.store_id, "platform_shop_id": auth.platform_store_id,
                         "authorization_id": auth.pk, "config_id": auth.integration_config.pk,
                         "scopes": sorted(auth.scopes or []),
                         "auth_config_fingerprint": digest_bytes(canonical_bytes({
                             "shop_cipher": auth.shop_cipher,
                             "environment": getattr(auth.integration_config, "environment", None),
                             "credential_id": getattr(auth.integration_config, "credential_id", None),
                             "network_enabled": getattr(auth.integration_config, "network_enabled", None),
                             "sync_read_enabled": getattr(auth.integration_config, "sync_read_enabled", None),
                             "runtime": {key: get_runtime_platform_config("tiktok").get(key) for key in (
                                 "api_host", "contract_approved", "order_detail_path", "affiliate_seller_creator_read_approved")},
                         }))})
    scope = {"tenant_id": actor.tenant_id, "stores": stores, "bindings": bindings,
             "start_date": start.isoformat(), "end_date": end.isoformat(),
             "creator_seeds": [list(seed) for seed in creator_seeds], "enrich_orders": enrich_orders}
    manifest = {"schema_version": 2, "tenant_id": actor.tenant_id, "start_date": start.isoformat(),
                "end_date": end.isoformat(), "created_at": timezone.now().isoformat(), "stores": stores,
                "components": [], "creator_selection": "existing_trusted_id_subset_not_date_filtered",
                "creator_limit": len(creator_seeds)}
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    with DatasetCheckpoint(output_dir, scope, resume=resume) as checkpoint:
        for auth in authorizations:
            client = client_factory(auth.integration_config, auth)
            verified = True
            try:
                client.verify_shop()
            except (TimeoutError, SoftTimeLimitExceeded):
                raise
            except Exception:
                verified = False
            for kind in sorted(KINDS):
                before = getattr(client, "request_count", 0)
                component = {"kind": kind, "store_id": auth.store_id, "status": "failed",
                             "row_count": 0, "request_count": 0, "days": []}
                payloads = []
                creator_values = None
                invalid_identity = False
                for day in days:
                    checkpoint.begin_day()
                    evidence = {"date": day.isoformat(), "status": "failed", "reason": "request_failed_no_data_assumed",
                                "expected_count": None, "observed_count": 0, "page_count": 0,
                                "pagination_exhausted": False}
                    try:
                        if not verified:
                            raise DatasetError("shop_identity_not_verified")
                        if kind == "videos":
                            values, _ = client.video_day(day, staging=True, checkpoint=checkpoint)
                            evidence.update(client.last_page_summary)
                        elif kind == "affiliate_orders":
                            values, _ = client.affiliate_orders(day, day, ZoneInfo(auth.store.timezone),
                                                               staging=True, checkpoint=checkpoint)
                            evidence.update(client.last_page_summary)
                            if enrich_orders:
                                client.enrich_orders(values, checkpoint=checkpoint)
                        else:
                            if creator_values is None:
                                creator_values = []
                                for creator_id, influencer_id in creator_seeds:
                                    descriptor = {"store_id": auth.store_id, "kind": kind, "creator_id": creator_id,
                                                  "influencer_id": influencer_id}
                                    value = checkpoint.load(descriptor)
                                    if value is None:
                                        value = client.creator(creator_id, influencer_id, staging=True)
                                        value.update(fetched_at=timezone.now().isoformat(), id_namespace="seller.creator_marketplace.creator_user_id")
                                        checkpoint.save(descriptor, value)
                                    creator_values.append(value)
                            values = creator_values if day == start else []
                            evidence.update(status="complete", reason="snapshot_not_date_filtered", observed_count=len(creator_values),
                                            page_count=len(creator_values), pagination_exhausted=True)
                        payloads.extend(values)
                    except (TimeoutError, SoftTimeLimitExceeded):
                        raise
                    except Exception as exc:
                        # Listing can succeed before detail enrichment fails. No rows were emitted.
                        evidence.update(status="failed", expected_count=None, observed_count=0,
                                        page_count=0, pagination_exhausted=False)
                        if isinstance(exc, DatasetError):
                            checkpoint.fail_day()
                        if isinstance(exc, DatasetError) and str(exc) in {
                            "duplicate_page_identity", "video_identity_missing", "conflicting_video_identifiers",
                            "affiliate_identity_missing", "invalid_order_detail_identity", "invalid_page_record",
                            "invalid_video_shape", "invalid_video_row", "invalid_affiliate_row",
                            "invalid_text", "oversized_text", "invalid_number", "invalid_integer", "invalid_money",
                            "invalid_currency", "affiliate_skus_missing", "invalid_video_post_time",
                        }:
                            invalid_identity = True
                        if kind == "creators":
                            creator_values = None
                        # Do not persist exception strings: provider exceptions may contain signed URLs.
                        evidence["reason"] = "shop_identity_not_verified" if not verified else "component_validation_or_request_failed"
                        if isinstance(exc, DatasetError) and str(exc) in {
                            "pagination_total_mismatch", "duplicate_page_identity", "video_identity_missing",
                            "conflicting_video_identifiers", "pagination_not_advancing", "pagination_limit_exceeded",
                            "affiliate_identity_missing", "affiliate_row_outside_verified_window",
                            "checkpoint_page_digest_mismatch", "checkpoint_cursor_mismatch", "artifact_size_exceeded",
                        }:
                            evidence["reason"] = str(exc)
                    component["days"].append(evidence)
                statuses = {day["status"] for day in component["days"]}
                if kind == "videos":
                    component["status"] = "complete" if statuses == {"complete"} else (
                        "failed" if statuses == {"failed"} else "partial")
                else:
                    component["status"] = "complete" if statuses == {"complete"} else "failed"
                if invalid_identity:
                    component["status"] = "failed"
                    for evidence in component["days"]:
                        evidence.update(status="failed", reason="component_validation_failed", expected_count=None,
                                        observed_count=0, page_count=0, pagination_exhausted=False)
                component["request_count"] = getattr(client, "request_count", 0) - before
                if component["status"] != "failed":
                    filename = f"store-{auth.store_id}-{kind}.jsonl"
                    content = b"".join(canonical_bytes({"kind": kind, "tenant_id": actor.tenant_id, "store_id": auth.store_id,
                        "store_code": auth.store.code, "payload": value}) + b"\n" for value in payloads)
                    checkpoint.write_artifact(filename, content)
                    component.update(file=filename, sha256=digest_bytes(content), row_count=len(payloads))
                manifest["components"].append(component)
        content = canonical_bytes(manifest) + b"\n"
        checkpoint.write_artifact("manifest.json", content)
    return manifest, digest_bytes(content)


def load_artifact(manifest_path, expected_digest):
    """Verify bytes and boundaries before exposing any rows to a writer."""
    path = Path(manifest_path)
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise DatasetError("invalid_manifest_file")
    content = path.read_bytes()
    if not isinstance(expected_digest, str) or len(expected_digest) != 64 or digest_bytes(content) != expected_digest:
        raise DatasetError("manifest_digest_mismatch")
    manifest = json.loads(content)
    version = manifest.get("schema_version")
    if type(version) is not int or version not in (1, 2) or type(manifest.get("tenant_id")) is not int:
        raise DatasetError("invalid_manifest_schema")
    start, end = validate_window(manifest["start_date"], manifest["end_date"])
    stores = manifest.get("stores")
    components = manifest.get("components")
    if not isinstance(stores, list) or not 1 <= len(stores) <= 2 or not isinstance(components, list):
        raise DatasetError("invalid_manifest_scope")
    store_map = {store["store_id"]: store for store in stores}
    if len(store_map) != len(stores) or any(type(key) is not int for key in store_map):
        raise DatasetError("duplicate_manifest_store")
    seen_components, rows, total_bytes = set(), [], 0
    for component in components:
        key = (component.get("store_id"), component.get("kind"))
        if key in seen_components or key[0] not in store_map or key[1] not in KINDS:
            raise DatasetError("invalid_component_scope")
        seen_components.add(key)
        if version == 2:
            days = component.get("days")
            expected_days = {(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)}
            if not isinstance(days, list) or len(days) != len(expected_days):
                raise DatasetError("component_day_set_incomplete")
            dates = set()
            for evidence in days:
                if not isinstance(evidence, dict):
                    raise DatasetError("invalid_day_evidence")
                current = evidence.get("date")
                expected, observed, pages = evidence.get("expected_count"), evidence.get("observed_count"), evidence.get("page_count")
                reason = evidence.get("reason")
                if (not isinstance(current, str) or current not in expected_days or current in dates
                        or evidence.get("status") not in {"complete", "partial", "failed"}
                        or type(observed) is not int or observed < 0
                        or expected is not None and (type(expected) is not int or expected < 0)
                        or type(pages) is not int or not 0 <= pages <= 100
                        or type(evidence.get("pagination_exhausted")) is not bool
                        or not isinstance(reason, str) or not reason or len(reason) > 100
                        or not reason.isascii() or not all(c.isalnum() or c == "_" for c in reason)):
                    raise DatasetError("invalid_day_evidence")
                if evidence["status"] == "partial" and key[1] != "videos":
                    raise DatasetError("invalid_day_quality")
                if evidence["status"] == "complete" and not evidence["pagination_exhausted"]:
                    raise DatasetError("unproven_complete_day")
                if key[1] == "videos" and evidence["status"] == "complete" and expected is not None and observed != expected:
                    raise DatasetError("unproven_complete_day")
                if evidence["status"] == "failed" and observed:
                    raise DatasetError("failed_day_has_rows")
                dates.add(current)
            statuses = {evidence["status"] for evidence in days}
            actual = "complete" if statuses == {"complete"} else (
                "failed" if key[1] != "videos" or statuses == {"failed"} else "partial")
            if component.get("status") != actual:
                raise DatasetError("component_day_quality_mismatch")
        if component.get("status") == "failed":
            if version == 2 and (component.get("row_count") != 0 or component.get("file")):
                raise DatasetError("failed_component_has_rows")
            continue
        if component.get("status") != "complete" and not (version == 2 and key[1] == "videos" and component.get("status") == "partial"):
            raise DatasetError("invalid_component_status")
        name = component.get("file")
        if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name or ":" in name or name == "manifest.json":
            raise DatasetError("unsafe_component_path")
        file = path.parent / name
        if file.is_symlink() or not file.is_file():
            raise DatasetError("invalid_component_file")
        total_bytes += file.stat().st_size
        if total_bytes > MAX_ARTIFACT_BYTES:
            raise DatasetError("artifact_size_exceeded")
        data = file.read_bytes()
        if digest_bytes(data) != component.get("sha256"):
            raise DatasetError("component_digest_mismatch")
        values = [json.loads(line) for line in data.splitlines()]
        if type(component.get("row_count")) is not int or len(values) != component["row_count"]:
            raise DatasetError("component_row_count_mismatch")
        for row in values:
            if (row.get("tenant_id") != manifest["tenant_id"] or type(row.get("tenant_id")) is not int
                    or row.get("store_id") != key[0] or type(row.get("store_id")) is not int
                    or row.get("store_code") != store_map[key[0]].get("store_code") or row.get("kind") != key[1]
                    or not isinstance(row.get("payload"), dict)):
                raise DatasetError("row_boundary_mismatch")
            if key[1] == "videos" and not start <= date.fromisoformat(row["payload"].get("metric_date", "")) <= end:
                raise DatasetError("row_date_outside_window")
            rows.append(row)
        if version == 2 and key[1] in {"videos", "affiliate_orders"}:
            observed_dates = []
            for row in values:
                if key[1] == "videos":
                    observed_dates.append(row["payload"]["metric_date"])
                else:
                    created = _number(row["payload"].get("create_time"), True)
                    if created is None:
                        raise DatasetError("affiliate_row_outside_verified_window")
                    day = datetime.fromtimestamp(created, UTC).astimezone(
                        ZoneInfo(store_map[key[0]]["timezone"])).date()
                    if not start <= day <= end:
                        raise DatasetError("affiliate_row_outside_verified_window")
                    observed_dates.append(day.isoformat())
            for evidence in component["days"]:
                if observed_dates.count(evidence["date"]) != evidence["observed_count"]:
                    raise DatasetError("day_observation_count_mismatch")
    if seen_components != {(store_id, kind) for store_id in store_map for kind in KINDS}:
        raise DatasetError("component_set_incomplete")
    return manifest, rows
