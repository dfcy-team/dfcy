"""Read-only preview and transactional confirmation for sample order CSVs."""

import hashlib
import json
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO

from django.core import signing
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import DatabaseError, OperationalError, connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from django.utils.decorators import method_decorator
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.views import APIView

from apps.audit.models import OperationLog
from apps.audit.services import MAX_SNAPSHOT_ITEMS, write_operation_log
from apps.common.exceptions import IdempotencyConflict, StateConflict
from apps.common.responses import success_response
from apps.masterdata.models import StatusChoices, StoreMaster, WarehouseMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission

from .models import (
    ImportBatch, Influencer, InfluencerProfile, SampleFulfillment, SampleItem, StoreProductListing,
    active_influencer_restriction_subquery, influencer_has_active_restriction, influencer_identity_queryset,
)
from .sample_import_csv import MAX_FILE_BYTES, MAX_ROWS, SOURCE_TIME_ZONE, parse_order_csv
from .sample_nickname import allocate_sample_nickname_draft
from .scopes import authorized_warehouses, filter_queryset, require_scope
from .services import SAMPLE_ORDER_CSV_SOURCE, _lock_tenant, create_sample_fulfillment


PERMISSION = "influencers.fulfillment.manage"
TOKEN_SALT = "influencers.sample-order-import.v1"
TOKEN_MAX_AGE = timedelta(hours=24)
LINK_TYPES = frozenset(value for value, _ in SampleFulfillment.LINK_TYPE_CHOICES if value != "DRJL")
RECEIPT_ACTION = "sample_order_import_confirm"
RECEIPT_TYPE = "sample_order_import_batch"


class OrderIssue(Exception):
    def __init__(self, code, message, *, status="invalid", **extra):
        self.result = {"status": status, "code": code, "message": message, **extra}
        super().__init__(message)


class ImportBusy(APIException):
    status_code = 503
    error_code = "SAMPLE_IMPORT_BUSY"
    default_detail = "有其他订单正在导入，请使用相同请求键稍后重试。"
    default_code = "sample_import_busy"


def _order_key(value):
    return value.strip().lower()


def _existing_order_keys(orders):
    keys = {_order_key(order["order_no"]) for order in orders}
    if not keys:
        return set()
    # The sole cross-tenant read returns only submitted keys, never record details.
    samples = SampleFulfillment.objects.order_by()
    original = samples.filter(source=SAMPLE_ORDER_CSV_SOURCE)
    return set(samples.annotate(csv_key=Lower(Trim("sample_order_no"))).filter(csv_key__in=keys)
               .values_list("csv_key", flat=True).distinct()) | set(
        original.annotate(csv_key=Lower(Trim("external_id"))).filter(csv_key__in=keys)
        .values_list("csv_key", flat=True).distinct()
    )


def _conflicting_order():
    return OrderIssue("order_conflict", "该订单号不可导入。", status="conflict")


def _match_key(value):
    return str(value or "").strip().casefold()


class ArchiveIndex:
    def __init__(self, user):
        self.user = user
        stores = StoreMaster.objects.filter(
            tenant_id=user.tenant_id, status=StatusChoices.ACTIVE,
            platform__tenant_id=user.tenant_id, platform__platform_type="tiktok",
        )
        self.allowed_stores = set(filter_queryset(user, stores, PERMISSION).values_list("pk", flat=True))
        self.allowed_warehouses = set(authorized_warehouses(user, PERMISSION).values_list("pk", flat=True))
        self.stores = {}
        self.by_shop = defaultdict(set)
        self.by_platform_shop = defaultdict(set)
        for row in stores.only("name", "code", "platform_store_name", "country_code", "platform_id"):
            self.stores[row.pk] = row
            for value in (row.code, row.name):
                self.by_shop[_match_key(value)].add(row.pk)
            self.by_platform_shop[_match_key(row.platform_store_name or row.name)].add(row.pk)
        self.warehouses = {}
        self.by_warehouse = defaultdict(set)
        for row in WarehouseMaster.objects.filter(
            tenant_id=user.tenant_id, status=StatusChoices.ACTIVE,
        ).only("code", "name", "country_code", "legacy_codes"):
            self.warehouses[row.pk] = row
            aliases = row.legacy_codes if isinstance(row.legacy_codes, list) else []
            for value in (row.code, row.name, *aliases):
                if isinstance(value, str) and value.strip():
                    key = _match_key(value)
                    country = row.country_code.upper()
                    self.by_warehouse[(country, key)].add(row.pk)
                    # The archive may append its country to the exported name.
                    suffix = "-" + country.casefold()
                    if key.endswith(suffix) and key[:-len(suffix)].strip():
                        self.by_warehouse[(country, key[:-len(suffix)].strip())].add(row.pk)

    def resolve(self, order):
        shop_ids = self.by_shop.get(_match_key(order["big_seller_store"]), set())
        platform_ids = self.by_platform_shop.get(_match_key(order["platform_store"]), set())
        if shop_ids and platform_ids:
            store_ids = shop_ids & platform_ids
        elif platform_ids:
            store_ids = platform_ids
        else:
            # Exported platform names may predate a rename. An exact archive
            # code/name remains valid; conflicting known identities above do not.
            store_ids = shop_ids
        country = order["country_code"]
        stores = {pk for pk in store_ids if self.stores[pk].country_code.upper() == country}
        if len(stores) != 1 or not stores <= self.allowed_stores:
            raise OrderIssue("store_unavailable", "未能唯一匹配已授权的同平台、同国家有效店铺。")
        warehouses = self.by_warehouse.get((country, _match_key(order["warehouse_name"])), set())
        if len(warehouses) != 1 or not warehouses <= self.allowed_warehouses:
            raise OrderIssue("warehouse_unavailable", "未能唯一匹配已授权的同国家有效发货仓库。")
        return self.stores[next(iter(stores))], self.warehouses[next(iter(warehouses))]

    def lock_for_confirm(self, order):
        store, warehouse = self.resolve(order)
        if (store.pk, warehouse.pk) != (order["store_id"], order["warehouse_id"]):
            raise OrderIssue("archives_changed", "店铺或仓库匹配已变化，请重新预览。")
        locked_store = filter_queryset(self.user, StoreMaster.objects, PERMISSION).select_for_update().filter(
            pk=store.pk, status=StatusChoices.ACTIVE, code=store.code, name=store.name,
            platform_store_name=store.platform_store_name, platform_id=store.platform_id,
            country_code=store.country_code, platform__platform_type="tiktok",
        ).first()
        locked_warehouse = authorized_warehouses(self.user, PERMISSION).select_for_update().filter(
            pk=warehouse.pk, code=warehouse.code, name=warehouse.name, country_code=warehouse.country_code,
        ).first()
        if locked_store is None or locked_warehouse is None or locked_warehouse.legacy_codes != warehouse.legacy_codes:
            raise OrderIssue("archives_changed", "店铺或仓库匹配已变化，请重新预览。")
        return locked_store, locked_warehouse


def preview_orders(user, upload):
    groups, row_count = parse_order_csv(upload)
    archives = ArchiveIndex(user)
    eligible = []
    for group in groups:
        group["preview_token"] = None
        if group["errors"]:
            continue
        try:
            store, warehouse = archives.resolve(group)
        except OrderIssue as exc:
            group["errors"].append({key: exc.result[key] for key in ("code", "message")})
            continue
        group.update(store_id=store.pk, store_name=store.name, warehouse_id=warehouse.pk)
        eligible.append(group)
    conflicts = _existing_order_keys(eligible)
    for group in eligible:
        if _order_key(group["order_no"]) in conflicts:
            exc = _conflicting_order()
            group["errors"].append({key: exc.result[key] for key in ("code", "message")})
        else:
            facts = {key: value for key, value in group.items() if key not in {"errors", "preview_token"}}
            group["preview_token"] = signing.dumps([user.tenant_id, user.pk, facts], salt=TOKEN_SALT, compress=True)
    valid_count = sum(bool(group["preview_token"]) for group in groups)
    return {
        "orders": groups, "row_count": row_count, "order_count": len(groups),
        "valid_count": valid_count, "invalid_count": len(groups) - valid_count,
        "source_timezone": SOURCE_TIME_ZONE,
        "owner": {"id": user.pk, "username": user.username, "full_name": user.full_name},
        "link_types": [{"value": value, "label": label} for value, label in SampleFulfillment.LINK_TYPE_CHOICES if value in LINK_TYPES],
    }


def _source_order(user, entry):
    token = entry.get("preview_token")
    if not isinstance(token, str) or not 1 <= len(token) <= MAX_FILE_BYTES:
        raise OrderIssue("preview_required", "请先预览有效的 CSV 订单。")
    try:
        tenant_id, actor_id, order = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature as exc:
        raise OrderIssue("preview_required", "预览无效或已过期，请重新上传 CSV。") from exc
    if (tenant_id, actor_id) != (user.tenant_id, user.pk):
        raise OrderIssue("preview_required", "预览无效，请使用当前账号重新上传 CSV。")
    if any(entry[key] != value for key, value in order.items() if key in entry):
        raise OrderIssue("preview_changed", "CSV 订单字段不可修改，请重新预览。")
    return order


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        return None
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        return None
    return value.strip()


def _enrichment(entry):
    nickname = _text(entry.get("nickname"), 120)
    if not nickname:
        raise OrderIssue("nickname_required", "请填写达人昵称（不超过 120 个字符）。")
    link_type = entry.get("link_type")
    if not isinstance(link_type, str) or link_type not in LINK_TYPES:
        raise OrderIssue("invalid_link_type", "请选择有效的独立送样类型。")
    influencer_id = entry.get("influencer_id")
    if influencer_id is not None and (type(influencer_id) is not int or not 0 < influencer_id <= 2**63 - 1):
        raise OrderIssue("invalid_influencer", "请选择已授权的达人。")
    confirmed = entry.get("confirm_recent_duplicate", False)
    reason = _text(entry.get("confirmation_reason", ""), 240)
    if type(confirmed) is not bool or reason is None:
        raise OrderIssue("invalid_confirmation", "重复确认须为布尔值，原因不能超过 240 个字符。")
    return " ".join(nickname.split()), link_type, influencer_id, confirmed, reason


def _active_creators(user):
    rows = Influencer.objects.filter(
        tenant_id=user.tenant_id, status=Influencer.Status.ACTIVE, platform__iexact="TikTok",
    )
    # The deployed archive-deletion hotfix also retains soft-deleted creators.
    if any(field.name == "is_deleted" for field in Influencer._meta.concrete_fields):
        rows = rows.filter(is_deleted=False)
    return rows


def _resolve_creator(user, nickname, selected_id, store):
    allowed = filter_queryset(user, _active_creators(user), PERMISSION)
    if selected_id is not None:
        creator = allowed.filter(pk=selected_id).first()
        if creator is None:
            raise OrderIssue("influencer_unavailable", "所选达人不可用于当前送样。")
        return creator
    exact = Influencer.objects.filter(tenant_id=user.tenant_id, platform__iexact="TikTok").filter(
        Q(name__iexact=nickname)
        | Q(profile__tenant_id=user.tenant_id, profile__display_name__iexact=nickname)
    )
    matches = list(exact.order_by("pk").values_list("pk", flat=True)[:2])
    if matches:
        candidates = allowed.filter(pk__in=exact.values("pk")).order_by("pk")
        if len(matches) == 1:
            creator = candidates.first()
            if creator is not None:
                return creator
        candidate_ids = list(candidates.values_list("pk", flat=True)[:20])
        if not candidate_ids:
            raise OrderIssue("influencer_unavailable", "该昵称不可用于当前送样，请核对达人档案。")
        raise OrderIssue(
            "ambiguous_influencer", "请从已授权候选中明确选择达人。",
            status="needs_influencer", candidate_ids=candidate_ids,
        )

    creator, created = allocate_sample_nickname_draft(user=user, nickname=nickname)
    if created:
        InfluencerProfile.objects.create(tenant_id=user.tenant_id, influencer=creator, market=store.country_code)
        write_operation_log(
            tenant=user.tenant, user=user, module="influencers", action="create_from_fulfillment",
            object_type="influencer", object_id=creator.pk,
            after_data={"code": creator.code, "name": creator.name, "platform": creator.platform, "source": SAMPLE_ORDER_CSV_SOURCE},
        )
    elif not allowed.filter(pk=creator.pk).exists():
        raise OrderIssue("influencer_unavailable", "该昵称不可用于当前送样，请核对达人档案。")
    return creator


def _recent_duplicate(user, creator, product_id, sent_at):
    item = SampleItem.objects.filter(
        tenant_id=user.tenant_id, fulfillment_id=OuterRef("pk"), external_product_id=product_id,
    )
    return SampleFulfillment.objects.filter(
        tenant_id=user.tenant_id, influencer_id__in=influencer_identity_queryset(creator).values("pk"),
        sample_sent_at__gte=sent_at - timedelta(days=30), sample_sent_at__lte=sent_at,
    ).filter(Q(external_product_id=product_id) | Exists(item)).exists()


def _confirm_order(user, batch, order, entry, archives, existing):
    store, warehouse = archives.lock_for_confirm(order)
    if _order_key(order["order_no"]) in existing:
        raise _conflicting_order()
    nickname, link_type, influencer_id, confirmed, reason = _enrichment(entry)
    creator = _resolve_creator(user, nickname, influencer_id, store)
    if influencer_has_active_restriction(creator):
        raise OrderIssue("influencer_restricted", "该达人当前不可送样。")
    sent_at = datetime.fromisoformat(order["sample_sent_at"])
    shipped_at = datetime.fromisoformat(order["shipped_at"]) if order["shipped_at"] else None
    product_id = order["external_product_id"]
    recent = _recent_duplicate(user, creator, product_id, sent_at)
    if recent and not (confirmed and reason):
        raise OrderIssue(
            "recent_duplicate", "该达人在下单时间前 30 天内已有同商品送样，请明确确认并填写原因。",
            status="needs_confirmation",
        )
    product_name = StoreProductListing.objects.filter(
        tenant_id=user.tenant_id, store=store, external_product_id=product_id, site_code=store.country_code,
    ).order_by("-source_updated_at", "-pk").values_list("product_name", flat=True).first() or ""
    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key=f"sample-order-csv:{_digest([batch.batch_key, _order_key(order['order_no'])])}",
        validated_data={
            "influencer": creator, "store": store, "owner": user, "link_type": link_type,
            "external_product_id": product_id, "product_name_snapshot": product_name,
            "sample_order_no": order["order_no"], "external_id": _order_key(order["order_no"]),
            "source": SAMPLE_ORDER_CSV_SOURCE,
        },
        item_payloads=[{
            "external_product_id": item["external_product_id"], "requested_sku": item["requested_sku"],
            "quantity": item["quantity"], "site_code": order["country_code"], "warehouse": warehouse,
        } for item in order["items"]],
        _order_csv_dates=(sent_at, shipped_at),
    )
    if not created:
        raise _conflicting_order()
    write_operation_log(
        tenant=user.tenant, user=user, module="influencers", action="sample_order_import_created",
        object_type="sample_fulfillment", object_id=fulfillment.pk,
        after_data={
            "batch_id": batch.pk, "order_no": order["order_no"], "product_id": product_id,
            "sample_sent_at": order["sample_sent_at"], "shipped_at": order["shipped_at"],
            "source_status": order["source_status"], "source_timezone": SOURCE_TIME_ZONE,
            "store_id": store.pk, "warehouse_id": warehouse.pk,
            "recent_duplicate_confirmed": recent, "confirmation_reason": reason if recent else "",
            "items": _pages(order["items"]), "source_row_count": len(order["row_numbers"]),
        },
    )
    return {"status": "created", "fulfillment_id": fulfillment.pk, "fulfillment_status": fulfillment.status}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


@contextmanager
def _import_transaction():
    # The MySQL advisory lock is database-wide and must outlive the commit.
    if connection.vendor == "mysql":
        if connection.in_atomic_block:
            raise RuntimeError("Sample import must own its database transaction.")
        name = "dfcy:sample-import:" + _digest(str(connection.settings_dict["NAME"]))[:32]
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, %s)", [name, 5])
            if cursor.fetchone()[0] != 1:
                raise ImportBusy()
        try:
            with transaction.atomic():
                yield
        finally:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", [name])
            except DatabaseError:
                connection.close()
        return
    with transaction.atomic():
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", [1684431737, 1935764848])
                if not cursor.fetchone()[0]:
                    raise ImportBusy()
            elif connection.vendor == "sqlite":
                # Acquire SQLite's writer reservation without modifying a business row.
                table = connection.ops.quote_name(ImportBatch._meta.db_table)
                try:
                    cursor.execute(f"UPDATE {table} SET id = id WHERE 0")
                except OperationalError as exc:
                    if "locked" in str(exc).lower():
                        raise ImportBusy() from exc
                    raise
            else:
                raise ImportBusy("当前数据库未配置订单导入锁，未写入。")
        yield


def _pages(rows):
    return [rows[index:index + MAX_SNAPSHOT_ITEMS] for index in range(0, len(rows), MAX_SNAPSHOT_ITEMS)]


def _batch_response(user, batch, results, *, replayed):
    if replayed:
        ids = {row["fulfillment_id"] for row in results if row["status"] == "created"}
        creators = filter_queryset(user, Influencer.objects, PERMISSION)
        allowed = filter_queryset(user, SampleFulfillment.objects, PERMISSION).filter(
            pk__in=ids, influencer_id__in=creators.values("pk"),
        )
        if allowed.count() != len(ids):
            raise PermissionDenied("当前数据范围不可查看该导入回执。")
    candidate_ids = {pk for row in results for pk in row.get("candidate_ids", ())}
    candidates = {
        pk: {"id": pk, "name": name, "display_name": display_name or name, "code": code, "is_blacklisted": restricted}
        for pk, name, display_name, code, restricted in filter_queryset(user, _active_creators(user), PERMISSION)
        .filter(pk__in=candidate_ids).annotate(
            is_blacklisted=Exists(active_influencer_restriction_subquery(user.tenant)),
        ).values_list("pk", "name", "profile__display_name", "code", "is_blacklisted")
    }
    for row in results:
        if "candidate_ids" in row:
            row["candidates"] = [candidates[pk] for pk in row.pop("candidate_ids") if pk in candidates]
    counts = dict.fromkeys(("created", "conflict", "needs_confirmation", "needs_influencer", "invalid"), 0)
    for row in results:
        counts[row["status"]] += 1
    return {
        "batch_id": batch.pk, "mode": "partial", "replayed": replayed, "results": results,
        "summary": counts, **{f"{key}_count": count for key, count in counts.items()},
    }


def _confirm_batch(user, entries, request_key, digest):
    batch_key = _digest([user.pk, request_key])
    with _import_transaction():
        _lock_tenant(user)
        require_scope(user, PERMISSION)
        prior = ImportBatch.objects.filter(
            tenant_id=user.tenant_id, source=SAMPLE_ORDER_CSV_SOURCE, batch_key=batch_key,
        ).first()
        if prior is not None:
            if prior.created_by_id != user.pk or prior.manifest_digest != digest:
                raise IdempotencyConflict()
            receipt = OperationLog.objects.filter(
                tenant_id=user.tenant_id, user=user, module="influencers", action=RECEIPT_ACTION,
                object_type=RECEIPT_TYPE, object_id=str(prior.pk),
            ).first()
            if receipt is None:
                raise StateConflict("该导入批次缺少确认回执，未重复写入。")
            results = [row for page in receipt.after_data["results"] for row in page]
            for row in results:
                if "row_numbers" in row:
                    row["row_numbers"] = [number for page in row["row_numbers"] for number in page]
            return _batch_response(user, prior, results, replayed=True)

        batch = ImportBatch.objects.create(
            tenant_id=user.tenant_id, created_by=user, source=SAMPLE_ORDER_CSV_SOURCE,
            batch_key=batch_key, manifest_digest=digest, row_count=len(entries),
        )
        results = []
        prepared = []
        source_row_count = 0
        for index, entry in enumerate(entries):
            result = {"index": index, "order_no": _text(entry.get("order_no"), 120) or ""}
            results.append(result)
            try:
                order = _source_order(user, entry)
                result.update(order_no=order["order_no"], row_numbers=order["row_numbers"])
                source_row_count += len(order["row_numbers"])
                prepared.append((index, order, entry))
            except OrderIssue as exc:
                result.update(exc.result)

        if source_row_count > MAX_ROWS:
            raise ValidationError({"orders": "确认订单合计不能超过 500 条 CSV 数据行。"})
        if prepared:
            archives = ArchiveIndex(user)
            existing = _existing_order_keys(order for _, order, _ in prepared)
            # Source chronology, not CSV order, determines the 30-day window.
            for index, order, entry in sorted(prepared, key=lambda row: (row[1]["sample_sent_at"], row[0])):
                try:
                    with transaction.atomic():
                        result = _confirm_order(user, batch, order, entry, archives, existing)
                except OrderIssue as exc:
                    result = exc.result
                except PermissionDenied:
                    result = OrderIssue("scope_changed", "当前授权范围不可导入此订单。").result
                except (ValidationError, ModelValidationError) as exc:
                    detail = exc.detail if isinstance(exc, ValidationError) else exc.messages
                    result = OrderIssue("fulfillment_validation", "此订单未通过履约校验。", details=detail).result
                else:
                    existing.add(_order_key(order["order_no"]))
                results[index].update(result)

        batch.status = ImportBatch.Status.COMPLETED
        batch.error_count = sum(row["status"] != "created" for row in results)
        batch.completed_at = timezone.now()
        batch.save(update_fields=("status", "error_count", "completed_at"))
        receipt_rows = [
            {**row, "row_numbers": _pages(row["row_numbers"])} if "row_numbers" in row else row
            for row in results
        ]
        write_operation_log(
            tenant=user.tenant, user=user, module="influencers", action=RECEIPT_ACTION,
            object_type=RECEIPT_TYPE, object_id=batch.pk,
            after_data={"mode": "partial", "results": _pages(receipt_rows), "source_timezone": SOURCE_TIME_ZONE},
        )
        return _batch_response(user, batch, results, replayed=False)


class SampleImportJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        limit = 2 * MAX_FILE_BYTES
        content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValidationError({"orders": "确认请求过大。"})
        return super().parse(BytesIO(content), media_type, parser_context)


class SampleImportPreviewView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = PERMISSION
    parser_classes = [MultiPartParser]

    def post(self, request):
        require_scope(request.user, PERMISSION)
        files = request.FILES.getlist("file")
        if len(files) != 1 or len(request.FILES) != 1:
            raise ValidationError({"file": "请上传一个 CSV 文件。"})
        return success_response(preview_orders(request.user, files[0]))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class SampleImportConfirmView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = PERMISSION
    parser_classes = [SampleImportJSONParser]

    def post(self, request):
        require_scope(request.user, PERMISSION)
        data = request.data
        if not isinstance(data, dict):
            raise ValidationError({"orders": "请求须为 JSON 对象。"})
        if data.get("source_timezone") != SOURCE_TIME_ZONE or data.get("timezone_confirmed") is not True:
            raise ValidationError({"timezone_confirmed": "必须明确确认 CSV 时间为北京时间（Asia/Shanghai）。"})
        key = _text(data.get("request_key"), 128)
        if not key:
            raise ValidationError({"request_key": "请提供 1 至 128 个字符的请求键。"})
        entries = data.get("orders")
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ROWS or not all(isinstance(row, dict) for row in entries):
            raise ValidationError({"orders": "请提交 1 至 500 个预览订单对象。"})
        return success_response(_confirm_batch(request.user, entries, key, _digest(data)))
