from datetime import UTC, datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.commerce.models import InventorySnapshot, RefundReturn, SalesOrder
from apps.commerce.services import upsert_inventory_snapshot
from apps.sales_management.services import upsert_normalized_order, upsert_normalized_refund

from .inventory_snapshot_contract import normalize_inventory_snapshot_record
from .models import MarketplaceStoreAuthorization, PlatformChoices, SyncJob
from .platform_capabilities import supports_resource
from .readonly_clients import (
    JifengWmsReadonlyClient,
    ShopeeReadonlyClient,
    TikTokReadonlyClient,
    default_sync_scope,
)
from .refund_return_contract import normalize_refund_return_record
from .sales_order_contract import normalize_sales_order_record


def _text(*values):
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _amount(*values):
    for value in values:
        if isinstance(value, dict):
            value = value.get("amount", value.get("value"))
        if value not in (None, ""):
            try:
                return str(Decimal(str(value)))
            except (TypeError, ValueError, ArithmeticError):
                pass
    return "0"


def _quantity(*values):
    for value in values:
        if value not in (None, ""):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass
    return 0


def _iso(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, str) and value and not value.isdigit():
        return value
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _boolean(value):
    if isinstance(value, bool):
        return value
    if value in {1, "1", "true", "TRUE"}:
        return True
    if value in {0, "0", "false", "FALSE"}:
        return False
    return None


def _normalized_order_status(raw_status):
    status = str(raw_status or "").upper()
    if "CANCEL" in status:
        return "cancelled"
    if status == "COMPLETED":
        return "completed"
    if status in {"DELIVERED", "FULFILLED", "READY_TO_SHIP", "SHIPPED", "AWAITING_SHIPMENT", "IN_TRANSIT"}:
        return "fulfilled"
    if status in {"CONFIRMED", "PAID", "UNPAID", "ON_HOLD"}:
        return "confirmed"
    return "pending"


class PlatformAdapter:
    adapter_name = "base"
    execution_mode = "unsupported"

    def bind_run(self, source_run):
        self.source_run = source_run

    def validate_configuration(self, sync_job):
        return None

    def fetch_page(self, sync_job, cursor_value=None):
        raise NotImplementedError

    def normalize_record(self, record):
        raise NotImplementedError

    def validate_record(self, record):
        raise NotImplementedError

    def persist_record(self, sync_job, record):
        raise NotImplementedError

    def get_next_cursor(self, page):
        raise NotImplementedError

    def should_continue(self, page, previous_cursor):
        return False


class MockPlatformAdapter(PlatformAdapter):
    adapter_name = "mock"
    execution_mode = "mock"

    def fetch_page(self, sync_job, cursor_value=None):
        records = sync_job.integration_config.account_alias
        page_records = [
            {"external_id": f"{records}-001", "name": "demo item", "api_secret": "not-a-real-secret"},
            {"external_id": f"{records}-002", "name": "placeholder item", "token": "placeholder-token"},
        ]
        if cursor_value == "done":
            page_records = []
        return {
            "records": page_records,
            "next_cursor": "done",
            "raw_responses": [{"endpoint": "mock://records", "payload": {"records": page_records}}],
        }

    def normalize_record(self, record):
        return {"external_id": record.get("external_id"), "name": record.get("name", "")}

    def validate_record(self, record):
        return bool(record.get("external_id"))

    def persist_record(self, sync_job, record):
        return {"action": "skipped", "idempotency_key": f"{sync_job.id}:{record['external_id']}"}

    def get_next_cursor(self, page):
        return page.get("next_cursor", "")


class SandboxPlaceholderAdapter(MockPlatformAdapter):
    adapter_name = "sandbox-placeholder"
    execution_mode = "sandbox"


class DisabledProductionAdapter(PlatformAdapter):
    adapter_name = "disabled-production"

    def _reject(self):
        raise ValidationError("Production readonly synchronization is not configured for this platform and resource.")

    def validate_configuration(self, sync_job):
        self._reject()

    def fetch_page(self, sync_job, cursor_value=None):
        self._reject()

    def normalize_record(self, record):
        self._reject()

    def validate_record(self, record):
        self._reject()

    def persist_record(self, sync_job, record):
        self._reject()

    def get_next_cursor(self, page):
        self._reject()


class ProductionReadonlyAdapter(PlatformAdapter):
    adapter_name = "production-readonly"
    execution_mode = "live_readonly"

    def __init__(self, config, client=None):
        self.config = config
        self.scope = default_sync_scope(config)
        self.authorization = None
        self.client = client
        self.source_run = None

    def _store_authorization(self, sync_job=None):
        if sync_job is not None and sync_job.store_authorization_id:
            authorization = sync_job.store_authorization
            if (
                authorization.tenant_id != sync_job.tenant_id
                or authorization.integration_config_id != self.config.id
                or authorization.platform != self.config.platform
                or authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE
            ):
                raise ValidationError("Sync job store authorization is not active in the configured tenant scope.")
            return authorization
        authorization_id = (self.config.platform_config or {}).get("store_authorization_id")
        queryset = MarketplaceStoreAuthorization.objects.filter(
            tenant=self.config.tenant,
            integration_config=self.config,
            platform=self.config.platform,
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
        ).select_related("store", "store__platform")
        if authorization_id:
            queryset = queryset.filter(pk=authorization_id)
        records = list(queryset[:2])
        if len(records) != 1:
            raise ValidationError("Sync config must resolve exactly one active tenant-owned store authorization.")
        return records[0]

    def validate_configuration(self, sync_job):
        if sync_job.integration_config_id != self.config.id or sync_job.tenant_id != self.config.tenant_id:
            raise ValidationError("Sync job and integration config scope do not match.")
        if self.config.environment not in {"pilot", "production"}:
            raise ValidationError("Production adapter requires pilot or production environment.")
        if not supports_resource(self.config.platform, sync_job.resource_type, self.execution_mode):
            raise ValidationError("Platform capability registry does not allow this resource and execution mode.")
        if self.config.platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
            self.authorization = self._store_authorization(sync_job)
        if sync_job.warehouse_authorization_id:
            authorization = sync_job.warehouse_authorization
            if (
                authorization.tenant_id != sync_job.tenant_id
                or authorization.integration_config_id != self.config.id
                or authorization.status != authorization.Status.ACTIVE
            ):
                raise ValidationError("Sync job warehouse authorization is not active in the configured tenant scope.")
        self._client().preflight()

    def _client(self):
        if self.client is not None:
            return self.client
        if self.config.platform == PlatformChoices.SHOPEE:
            self.client = ShopeeReadonlyClient(self.config, self.authorization)
        elif self.config.platform == PlatformChoices.TIKTOK:
            self.client = TikTokReadonlyClient(self.config, self.authorization)
        elif self.config.platform == PlatformChoices.JIFENG_WMS:
            self.client = JifengWmsReadonlyClient(self.config)
        else:
            raise ValidationError("Unsupported production readonly platform.")
        return self.client

    def fetch_page(self, sync_job, cursor_value=None):
        client = self._client()
        if sync_job.resource_type == SyncJob.ResourceType.SALES_ORDER:
            return client.fetch_orders(cursor_value, self.scope)
        if sync_job.resource_type == SyncJob.ResourceType.REFUND_RETURN:
            return client.fetch_returns(cursor_value, self.scope)
        if sync_job.resource_type == SyncJob.ResourceType.INVENTORY_SNAPSHOT:
            return client.fetch_inventory(cursor_value, self.scope)
        raise ValidationError("The selected resource is not supported by the production readonly adapter.")

    def get_next_cursor(self, page):
        return str(page.get("next_cursor") or "")

    def should_continue(self, page, previous_cursor):
        next_cursor = self.get_next_cursor(page)
        return bool(next_cursor and next_cursor != str(previous_cursor or ""))

    def validate_record(self, record):
        return isinstance(record, dict)

    def _require_run(self):
        if self.source_run is None:
            raise ValidationError("Production adapter is not bound to a SyncRun.")
        return self.source_run


class MarketplaceOrderAdapter(ProductionReadonlyAdapter):
    def normalize_record(self, record):
        store = self.authorization.store
        if self.config.platform == PlatformChoices.SHOPEE:
            items = record.get("item_list") if isinstance(record.get("item_list"), list) else []
            raw_status = _text(record.get("order_status"), "UNKNOWN")
            payload = {
                "contract_version": "sales_order.v1",
                "store_id": str(store.id),
                "source_order_id": _text(record.get("order_sn")),
                "ordered_at": _iso(record.get("create_time")),
                "source_updated_at": _iso(record.get("update_time")),
                "currency": _text(record.get("currency"), store.currency).upper(),
                "gross_amount": _amount(record.get("total_amount")),
                "shipping_amount": _amount(record.get("estimated_shipping_fee"), record.get("actual_shipping_fee")),
                "order_status": _normalized_order_status(raw_status),
                "region": self.authorization.region,
                "lines": [
                    {
                        "source_line_id": f"{record.get('order_sn')}:{item.get('item_id')}:{item.get('model_id')}:{index}",
                        "sku": _text(item.get("model_sku"), item.get("item_sku"), item.get("model_id"), item.get("item_id")),
                        "product_name": _text(item.get("item_name")),
                        "quantity": _quantity(item.get("model_quantity_purchased"), 1),
                        "unit_price": _amount(item.get("model_discounted_price"), item.get("model_original_price")),
                        "platform_product_id": _text(item.get("item_id")),
                        "platform_variant_id": _text(item.get("model_id")),
                        "raw_line_status": raw_status,
                    }
                    for index, item in enumerate(items, start=1)
                    if isinstance(item, dict)
                ],
            }
        else:
            payment = record.get("payment") if isinstance(record.get("payment"), dict) else {}
            items = record.get("line_items") if isinstance(record.get("line_items"), list) else []
            raw_status = _text(record.get("status"), "UNKNOWN")
            payload = {
                "contract_version": "sales_order.v1",
                "store_id": str(store.id),
                "source_order_id": _text(record.get("id")),
                "ordered_at": _iso(record.get("create_time")),
                "source_updated_at": _iso(record.get("update_time")),
                "currency": _text(payment.get("currency"), store.currency).upper(),
                "gross_amount": _amount(payment.get("total_amount")),
                "shipping_amount": _amount(payment.get("shipping_fee")),
                "order_status": _normalized_order_status(raw_status),
                "region": self.authorization.region,
                "lines": [
                    {
                        "source_line_id": _text(item.get("id"), f"{record.get('id')}:{index}"),
                        "sku": _text(item.get("seller_sku"), item.get("sku_id")),
                        "product_name": _text(item.get("product_name")),
                        "quantity": _quantity(item.get("quantity"), 1),
                        "unit_price": _amount(item.get("sale_price"), item.get("original_price")),
                        "platform_product_id": _text(item.get("product_id")),
                        "platform_variant_id": _text(item.get("sku_id")),
                        "raw_line_status": _text(item.get("display_status"), raw_status),
                    }
                    for index, item in enumerate(items, start=1)
                    if isinstance(item, dict)
                ],
            }
        return normalize_sales_order_record(self.config.platform, payload)

    def persist_record(self, sync_job, record):
        run = self._require_run()
        external_id = record["source_order_id"]
        existing = SalesOrder.objects.filter(
            tenant=sync_job.tenant, store_id=record["store_id"], external_order_id=external_id
        ).first()
        before_hash = existing.payload_hash if existing else ""
        saved = upsert_normalized_order(tenant=sync_job.tenant, payload=record, source_run=run)
        action = "created" if existing is None else "skipped" if before_hash == saved.payload_hash else "updated"
        return {"action": action, "idempotency_key": f"{sync_job.id}:{external_id}"}


class MarketplaceRefundAdapter(ProductionReadonlyAdapter):
    def normalize_record(self, record):
        store = self.authorization.store
        if self.config.platform == PlatformChoices.SHOPEE:
            return_id = _text(record.get("return_sn"), record.get("return_id"))
            order_id = _text(record.get("order_sn"), record.get("order_id"))
            case_type = _text(record.get("return_type"), record.get("solution"), "refund")
            raw_status = _text(record.get("status"), record.get("return_status"), "unknown")
            refund = record.get("refund_amount") if isinstance(record.get("refund_amount"), dict) else {}
            items = next((record.get(name) for name in ("item", "item_list", "return_item_list", "return_items") if isinstance(record.get(name), list)), [])
            currency = _text(record.get("currency"), refund.get("currency"), store.currency).upper()
            payload = {
                "contract_version": "refund_return.v1",
                "store_id": str(store.id),
                "external_return_id": return_id,
                "external_refund_id": _text(record.get("refund_id")),
                "external_order_id": order_id,
                "case_type": case_type,
                "raw_status": raw_status,
                "normalized_status": raw_status.lower(),
                "arbitration_status": _text(record.get("negotiation_status"), record.get("arbitration_status")),
                "reason_code": _text(record.get("reason"), record.get("return_reason")),
                "requested_at_utc": _iso(record.get("create_time")),
                "updated_at_utc": _iso(record.get("update_time")),
                "completed_at_utc": _iso(record.get("complete_time") or record.get("refund_time")) or None,
                "currency": currency,
                "refund_amount": _amount(record.get("refund_amount"), record.get("refund_total")),
                "refund_subtotal": _amount(refund.get("refund_subtotal"), record.get("refund_subtotal")),
                "refund_shipping_fee": _amount(refund.get("refund_shipping_fee"), record.get("refund_shipping_fee")),
                "refund_tax": _amount(refund.get("refund_tax"), record.get("refund_tax")),
                "requires_physical_return": "RETURN" in case_type.upper(),
                "is_partial_quantity_return": _boolean(record.get("is_partial_quantity_return")),
                "is_refund_amount_adjusted": _boolean(record.get("is_refund_amount_adjusted")),
                "items": [self._shopee_refund_item(item, return_id, index, currency) for index, item in enumerate(items, start=1) if isinstance(item, dict)],
            }
        else:
            return_id = _text(record.get("return_id"), record.get("reverse_order_id"), record.get("aftersales_id"))
            refund = record.get("refund_amount") if isinstance(record.get("refund_amount"), dict) else {}
            items = next((record.get(name) for name in ("return_line_items", "return_items", "line_items", "order_line_list") if isinstance(record.get(name), list)), [])
            case_type = _text(record.get("return_type"), record.get("aftersales_type"), "refund")
            raw_status = _text(record.get("return_status"), record.get("status"), "unknown")
            currency = _text(refund.get("currency"), record.get("currency"), store.currency).upper()
            payload = {
                "contract_version": "refund_return.v1",
                "store_id": str(store.id),
                "external_return_id": return_id,
                "external_refund_id": _text(record.get("refund_id")),
                "external_order_id": _text(record.get("order_id")),
                "case_type": case_type,
                "raw_status": raw_status,
                "normalized_status": raw_status.lower(),
                "arbitration_status": _text(record.get("arbitration_status")),
                "reason_code": _text(record.get("return_reason"), record.get("reason_code")),
                "requested_at_utc": _iso(record.get("create_time")),
                "updated_at_utc": _iso(record.get("update_time")),
                "completed_at_utc": _iso(record.get("complete_time") or record.get("refund_time")) or None,
                "currency": currency,
                "refund_amount": _amount(refund.get("refund_total"), record.get("refund_total")),
                "refund_subtotal": _amount(refund.get("refund_subtotal")),
                "refund_shipping_fee": _amount(refund.get("refund_shipping_fee")),
                "refund_tax": _amount(refund.get("refund_tax")),
                "requires_physical_return": None if not case_type else "RETURN" in case_type.upper(),
                "is_partial_quantity_return": None,
                "is_refund_amount_adjusted": None,
                "items": [self._tiktok_refund_item(item, return_id, index, currency) for index, item in enumerate(items, start=1) if isinstance(item, dict)],
            }
        return normalize_refund_return_record(self.config.platform, payload)

    @staticmethod
    def _shopee_refund_item(item, return_id, index, currency):
        return {
            "external_return_item_id": _text(item.get("return_item_id"), item.get("line_id"), f"{return_id}:{index}"),
            "external_order_item_id": _text(item.get("order_item_id")),
            "platform_product_id": _text(item.get("item_id")),
            "platform_variant_id": _text(item.get("model_id")),
            "seller_sku": _text(item.get("model_sku"), item.get("item_sku")),
            "item_name_snapshot": _text(item.get("item_name"), item.get("name")),
            "quantity": _quantity(item.get("amount"), item.get("quantity"), 1),
            "currency": currency,
            "refund_amount": _amount(item.get("refund_amount"), item.get("amount_refunded")),
        }

    @staticmethod
    def _tiktok_refund_item(item, return_id, index, currency):
        return {
            "external_return_item_id": _text(item.get("return_line_item_id"), item.get("id"), f"{return_id}:{index}"),
            "external_order_item_id": _text(item.get("order_line_item_id"), item.get("sub_order_line_item_id")),
            "platform_product_id": _text(item.get("product_id")),
            "platform_variant_id": _text(item.get("sku_id")),
            "seller_sku": _text(item.get("seller_sku")),
            "item_name_snapshot": _text(item.get("product_name")),
            "quantity": _quantity(item.get("quantity"), item.get("return_quantity"), 1),
            "currency": currency,
            "refund_amount": _amount(item.get("refund_amount")),
        }

    def persist_record(self, sync_job, record):
        run = self._require_run()
        existing = RefundReturn.objects.filter(
            tenant=sync_job.tenant, store_id=record["store_id"], external_return_id=record["external_return_id"]
        ).first()
        before_hash = existing.payload_hash if existing else ""
        saved = upsert_normalized_refund(tenant=sync_job.tenant, payload=record, source_run=run)
        action = "created" if existing is None else "skipped" if before_hash == saved.payload_hash else "updated"
        return {"action": action, "idempotency_key": f"{sync_job.id}:{record['external_return_id']}"}


class JifengInventoryAdapter(ProductionReadonlyAdapter):
    def normalize_record(self, record):
        config = self.config.platform_config or {}
        return normalize_inventory_snapshot_record(
            {
                "contract_version": "inventory_snapshot.v1",
                "site_code": _text(config.get("site_code")).upper(),
                "warehouse_id": str(config.get("warehouse_id") or ""),
                "source_sku": _text(record.get("sku"), record.get("skuCode"), record.get("code"), record.get("sellerSku")),
                "seller_sku": _text(record.get("sellerSku"), record.get("sku")),
                "on_hand_qty": _quantity(record.get("totalNum"), record.get("total"), record.get("quantity")),
                "available_qty": _quantity(record.get("availableNum"), record.get("available"), record.get("availableQuantity")),
                "reserved_qty": _quantity(record.get("lockedNum"), record.get("locked"), record.get("lockedQuantity")),
                "in_transit_qty": _quantity(record.get("onTheWayNum"), record.get("inTransit"), record.get("onWay")),
                "pending_putaway_qty": _quantity(record.get("pendingListingNum"), record.get("pendingPutaway")),
                "defective_qty": _quantity(record.get("nonGoodNum"), record.get("nonGood"), record.get("defectiveQuantity")),
                "snapshot_at_utc": _text(record.get("_snapshot_at_utc"), timezone.now().isoformat()),
            }
        )

    def persist_record(self, sync_job, record):
        run = self._require_run()
        existing = InventorySnapshot.objects.filter(
            tenant=sync_job.tenant,
            warehouse_id=record["warehouse_id"],
            source_sku=record["source_sku"],
            snapshot_at_utc=record["snapshot_at_utc"],
        ).first()
        before_hash = existing.payload_hash if existing else ""
        saved = upsert_inventory_snapshot(tenant=sync_job.tenant, payload=record, source_run=run)
        action = "created" if existing is None else "skipped" if before_hash == saved.payload_hash else "updated"
        return {"action": action, "idempotency_key": f"{sync_job.id}:{saved.id}"}


def get_adapter_for_config(config, resource_type=None):
    if config.environment == "mock":
        return MockPlatformAdapter() if supports_resource("mock", resource_type, "mock") else DisabledProductionAdapter()
    if config.environment == "sandbox":
        return SandboxPlaceholderAdapter()
    if config.environment not in {"pilot", "production"}:
        return DisabledProductionAdapter()
    if not supports_resource(config.platform, resource_type, "live_readonly"):
        return DisabledProductionAdapter()
    if resource_type == SyncJob.ResourceType.SALES_ORDER and config.platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
        return MarketplaceOrderAdapter(config)
    if resource_type == SyncJob.ResourceType.REFUND_RETURN and config.platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
        return MarketplaceRefundAdapter(config)
    if resource_type == SyncJob.ResourceType.INVENTORY_SNAPSHOT and config.platform == PlatformChoices.JIFENG_WMS:
        return JifengInventoryAdapter(config)
    return DisabledProductionAdapter()
