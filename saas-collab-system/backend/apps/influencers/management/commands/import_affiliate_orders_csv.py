import csv
import logging
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant

from ...attribution import (
    _order_values,
    affiliate_order_row_hash,
    affiliate_order_source_row_key,
    normalize_account,
    parse_decimal,
    parse_order_datetime,
    PERFORMANCE_CURRENCIES,
)
from ...models import AffiliateImportState, AffiliateOrderRevision, AffiliateOrderSnapshot
from ...tasks import refresh_affiliate_order_attributions_task


logger = logging.getLogger(__name__)


REQUIRED_FIELDS = (
    "data_time",
    "shop_abbr",
    "site",
    "order_id",
    "product_id",
    "sku_id",
    "creator_username",
    "payment_amount",
    "quantity",
    "currency",
    "fully_returned",
    "order_status",
)
FIELD_ALIASES = {
    "data_time": ("data_time", "order_time", "订单日期", "订单时间", "下单时间"),
    "shop_name": ("shop_name", "店铺名称", "店铺名"),
    "shop_abbr": ("shop_abbr", "shop", "店铺简称", "店铺"),
    "site": ("site", "site_code", "站点", "国家", "country", "marketplace"),
    "order_id": ("order_id", "order_no", "订单id", "订单号", "订单编号"),
    "product_id": ("product_id", "product", "商品id", "商品编号", "商品ID"),
    "product_name": ("product_name", "商品名称", "商品名"),
    "sku_id": ("sku_id", "sku", "商品sku", "SKU ID", "子商品id"),
    "product_price": ("product_price", "商品价格", "sku_price"),
    "payment_amount": ("payment_amount", "支付金额", "订单金额", "gmv"),
    "quantity": ("quantity", "数量", "商品数量"),
    "currency": ("currency", "currency_code", "币种", "货币"),
    "fully_returned": ("fully_returned", "全额退款", "是否全额退款"),
    "order_status": ("order_status", "status", "订单状态"),
    "creator_username": ("creator_username", "creator", "达人账号", "达人用户名", "creator_handle"),
    "actual_paid_commission": (
        "actual_paid_commission",
        "actual_commission",
        "实际达人佣金",
        "实际佣金",
    ),
    "estimated_paid_commission": (
        "estimated_paid_commission",
        "estimated_commission",
        "预估达人佣金",
        "预估佣金",
    ),
    "export_time": ("export_time", "导出时间"),
    "created_at": ("created_at", "创建时间", "记录创建时间"),
}


def _header_key(value):
    return "".join(str(value or "").strip().casefold().replace("\ufeff", "").split()).replace("_", "")


def _column_map(fieldnames):
    available = {_header_key(name): name for name in fieldnames if name is not None}
    mapping = {}
    missing = []
    for field in FIELD_ALIASES:
        for alias in FIELD_ALIASES[field]:
            original = available.get(_header_key(alias))
            if original is not None:
                mapping[field] = original
                break
        if field in REQUIRED_FIELDS and field not in mapping:
            missing.append(field)
    if missing:
        raise CommandError("CSV is missing required columns: " + ", ".join(missing))
    return mapping


def _value(row, mapping, field):
    return str(row.get(mapping.get(field), "") or "").strip()


def _parse_quantity(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("quantity: required")
    try:
        quantity = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity: invalid_integer") from exc
    if quantity < 0:
        raise ValueError("quantity: negative")
    return quantity


def _parse_row(row, mapping, source):
    if None in row:
        raise ValueError("row: extra_columns")
    data_time = parse_order_datetime(_value(row, mapping, "data_time"), field="data_time")
    shop_abbr = _value(row, mapping, "shop_abbr")
    site = _value(row, mapping, "site")
    order_id = _value(row, mapping, "order_id")
    product_id = _value(row, mapping, "product_id")
    sku_id = _value(row, mapping, "sku_id")
    creator_username = _value(row, mapping, "creator_username")
    required_text = {
        "shop_abbr": shop_abbr,
        "site": site,
        "order_id": order_id,
        "product_id": product_id,
        "sku_id": sku_id,
        "creator_username": creator_username,
        "fully_returned": _value(row, mapping, "fully_returned"),
        "order_status": _value(row, mapping, "order_status"),
    }
    missing = [field for field, value in required_text.items() if not value]
    if missing:
        raise ValueError("required_fields")
    currency = _value(row, mapping, "currency").upper()
    if currency not in PERFORMANCE_CURRENCIES:
        raise ValueError("currency: unsupported")
    payment_raw = _value(row, mapping, "payment_amount")
    actual_raw = _value(row, mapping, "actual_paid_commission")
    estimated_raw = _value(row, mapping, "estimated_paid_commission")
    product_price_raw = _value(row, mapping, "product_price")
    product_price = (
        parse_decimal(product_price_raw, field="product_price", required=False)
        if product_price_raw
        else None
    )
    source_updated_at = None
    for field in ("export_time", "created_at"):
        raw = _value(row, mapping, field)
        if raw:
            source_updated_at = parse_order_datetime(raw, field=field)
            break
    source_updated_at = source_updated_at or data_time
    values = {
        "source": source,
        "data_time": data_time,
        "shop_name": _value(row, mapping, "shop_name"),
        "shop_abbr": shop_abbr,
        "site": site,
        "order_id": order_id,
        "product_id": product_id,
        "product_name": _value(row, mapping, "product_name"),
        "sku_id": sku_id,
        "product_price": product_price,
        "payment_amount": parse_decimal(payment_raw, field="payment_amount"),
        "currency": currency,
        "quantity": _parse_quantity(_value(row, mapping, "quantity")),
        "fully_returned": required_text["fully_returned"],
        "order_status": required_text["order_status"],
        "creator_username": creator_username,
        "creator_username_normalized": normalize_account(creator_username),
        "actual_paid_commission": (
            parse_decimal(actual_raw, field="actual_paid_commission") if actual_raw else None
        ),
        "estimated_paid_commission": (
            parse_decimal(estimated_raw, field="estimated_paid_commission") if estimated_raw else None
        ),
        "source_updated_at": source_updated_at,
    }
    values["source_row_key"] = affiliate_order_source_row_key(
        data_time=data_time,
        shop_abbr=shop_abbr,
        site=site,
        order_id=order_id,
        sku_id=sku_id,
    )
    candidate = AffiliateOrderSnapshot(**values)
    values["row_hash"] = affiliate_order_row_hash(_order_values(candidate))
    return values


class Command(BaseCommand):
    help = "Import a whitelisted affiliate order CSV into tenant-scoped current facts."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--file", required=True)
        parser.add_argument("--source", required=True)
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--lease-seconds", type=int, default=900)

    def _acquire_lease(self, tenant, source, lease_seconds):
        now = timezone.now()
        with transaction.atomic():
            state, _ = AffiliateImportState.objects.select_for_update().get_or_create(
                tenant=tenant, source=source
            )
            if state.lease_expires_at and state.lease_expires_at > now:
                raise CommandError("An affiliate import lease is already active for this tenant/source.")
            token = uuid4().hex
            state.status = AffiliateImportState.Status.RUNNING
            state.lease_token = token
            state.lease_expires_at = now + timedelta(seconds=max(60, min(3600, lease_seconds)))
            state.last_error_code = ""
            state.save(update_fields=["status", "lease_token", "lease_expires_at", "last_error_code", "updated_at"])
        return token

    def _release_lease(self, tenant, source, token, *, status, counts, cursor="", last_data_time=None, last_source_updated_at=None):
        with transaction.atomic():
            state = AffiliateImportState.objects.select_for_update().filter(
                tenant=tenant, source=source, lease_token=token
            ).first()
            if state is None:
                return
            state.status = status
            state.lease_token = ""
            state.lease_expires_at = None
            state.cursor = cursor
            state.last_row_count = counts["created"] + counts["updated"] + counts["noop"]
            state.last_rejected_count = counts["rejected"]
            state.last_data_time = last_data_time
            state.last_source_updated_at = last_source_updated_at
            state.last_error_code = "" if status != AffiliateImportState.Status.FAILED else "import_failed"
            state.save()

    def _upsert(self, tenant, values):
        values = {**values, "store_id": self._store_id(values["shop_abbr"])}
        queryset = AffiliateOrderSnapshot.objects.select_for_update()
        current = queryset.filter(
            tenant=tenant,
            source=values["source"],
            source_row_key=values["source_row_key"],
        ).first()
        if current is None:
            create_values = {**values, "tenant": tenant}
            try:
                with transaction.atomic():
                    AffiliateOrderSnapshot.objects.create(**create_values)
            except IntegrityError:
                current = queryset.get(
                    tenant=tenant,
                    source=values["source"],
                    source_row_key=values["source_row_key"],
                )
                if current.row_hash == values["row_hash"]:
                    return "noop", current
                return self._update(tenant, current, values)
            return "created", None
        if current.row_hash == values["row_hash"]:
            return "noop", current
        incoming_source_updated_at = values.get("source_updated_at")
        current_source_updated_at = current.source_updated_at
        if current_source_updated_at and (
            incoming_source_updated_at is None
            or incoming_source_updated_at < current_source_updated_at
        ):
            return "rejected", current
        if (
            current_source_updated_at
            and incoming_source_updated_at
            and incoming_source_updated_at == current_source_updated_at
        ):
            return "conflict", current
        return self._update(tenant, current, values)

    def _update(self, tenant, current, values):
        before = _order_values(current)
        proposed = AffiliateOrderSnapshot(tenant=tenant, **values)
        after = _order_values(proposed)
        before_hash = current.row_hash
        update_values = {key: value for key, value in values.items() if key not in {"source", "source_row_key"}}
        for key, value in update_values.items():
            setattr(current, key, value)
        current.full_clean()
        current.save(update_fields=[*update_values, "updated_at"])

        previous_revision = AffiliateOrderRevision.objects.filter(
            tenant=tenant,
            source=values["source"],
            source_row_key=values["source_row_key"],
        ).order_by("-revision_no").values_list("revision_no", flat=True).first()
        AffiliateOrderRevision.objects.create(
            tenant=tenant,
            order_snapshot=current,
            source=values["source"],
            source_row_key=values["source_row_key"],
            revision_no=(previous_revision or 0) + 1,
            before_hash=before_hash,
            after_hash=values["row_hash"],
            before_values=before,
            after_values=after,
            source_updated_at=values["source_updated_at"],
        )
        return "updated", current

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        source = str(options["source"] or "").strip()
        path = Path(options["file"])
        batch_size = options["batch_size"]
        if not source or len(source) > 40:
            raise CommandError("source must be 1-40 characters.")
        if batch_size < 1 or batch_size > 5000:
            raise CommandError("batch-size must be between 1 and 5000.")
        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist as exc:
            raise CommandError("Tenant does not exist.") from exc
        if not path.is_file():
            raise CommandError("CSV file does not exist.")

        self._store_map = {}
        for row in StoreMaster.objects.filter(tenant=tenant).values("id", "code", "name"):
            for value in (row["code"], row["name"]):
                if value:
                    self._store_map[normalize_account(value)] = row["id"]

        counts = {"created": 0, "updated": 0, "noop": 0, "conflict": 0, "rejected": 0}
        rejection_reasons = {}
        token = None
        last_cursor = ""
        last_data_time = None
        last_source_updated_at = None
        refresh_enqueue_status = {"value": "not_scheduled"}
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise CommandError("CSV header is required.")
                mapping = _column_map(reader.fieldnames)
                token = self._acquire_lease(tenant, source, options["lease_seconds"])
                batch = []
                for row in reader:
                    try:
                        batch.append(_parse_row(row, mapping, source))
                    except (TypeError, ValueError, OverflowError) as exc:
                        counts["rejected"] += 1
                        reason = str(exc).split(":", 1)[0] or "invalid_row"
                        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                    if len(batch) >= batch_size:
                        self._process_batch(tenant, batch, counts)
                        last_cursor = batch[-1]["source_row_key"]
                        last_data_time = batch[-1]["data_time"]
                        last_source_updated_at = batch[-1]["source_updated_at"]
                        batch = []
                if batch:
                    self._process_batch(tenant, batch, counts)
                    last_cursor = batch[-1]["source_row_key"]
                    last_data_time = batch[-1]["data_time"]
                    last_source_updated_at = batch[-1]["source_updated_at"]
            with transaction.atomic():
                self._release_lease(
                    tenant,
                    source,
                    token,
                    status=AffiliateImportState.Status.IDLE,
                    counts=counts,
                    cursor=last_cursor,
                    last_data_time=last_data_time,
                    last_source_updated_at=last_source_updated_at,
                )

                def enqueue_refresh():
                    try:
                        refresh_affiliate_order_attributions_task.delay(tenant_id=tenant.pk)
                    except Exception:
                        # Import data is already committed; leave a visible status and
                        # allow an operator or scheduler to replay the idempotent task.
                        refresh_enqueue_status["value"] = "enqueue_failed"
                        logger.warning(
                            "Affiliate attribution refresh enqueue failed tenant=%s source=%s",
                            tenant.pk,
                            source,
                            exc_info=True,
                        )
                    else:
                        refresh_enqueue_status["value"] = "queued"

                transaction.on_commit(enqueue_refresh)
        except CommandError:
            if token:
                self._release_lease(
                    tenant, source, token, status=AffiliateImportState.Status.FAILED, counts=counts
                )
            raise
        except Exception as exc:
            if token:
                self._release_lease(
                    tenant, source, token, status=AffiliateImportState.Status.FAILED, counts=counts
                )
            raise CommandError("Affiliate import failed; no row content was logged.") from exc
        self.stdout.write(
            "created={created} updated={updated} noop={noop} conflict={conflict} rejected={rejected} "
            "attribution_refresh={refresh} rejection_reasons={reasons}".format(
                **counts,
                refresh=refresh_enqueue_status["value"],
                reasons=",".join(f"{key}:{value}" for key, value in sorted(rejection_reasons.items())) or "none",
            )
        )

    def _process_batch(self, tenant, batch, counts):
        with transaction.atomic():
            for values in batch:
                result, _ = self._upsert(tenant, values)
                counts[result] += 1
                if result == "conflict":
                    counts["rejected"] += 1

    def _store_id(self, shop_abbr):
        return self._store_map.get(normalize_account(shop_abbr))
