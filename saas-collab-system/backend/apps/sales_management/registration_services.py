import copy
import hashlib
import io
import json
from datetime import date
from decimal import Decimal

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.commerce.models import SalesOrder, ShipmentRecord, RefundReturn
from apps.common.exceptions import StateConflict
from apps.integrations.models import MarketplaceProductMapping
from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission
from apps.products.models import ProductSKU
from apps.workflows.models import ApprovalRequest, WorkflowAuditEvent
from apps.workflows.services import write_workflow_audit

from .registration_models import OrderRegistration, PendingOrderDetail, RegistrationEvidence
from .registration_rules import adjusted_lines, gcash_payment_date, gcash_remark, money, promotion_cost
from .scopes import filter_sales_queryset


PREFIX = {"exchange": "sales_management.exchange", "promotion": "sales_management.promotion", "gcash": "finance.gcash"}
EDITABLE = {"draft", "rejected", "withdrawn"}
FIELDS = {
    "exchange": {"changes", "reason", "note"},
    "promotion": {"order_amount", "fee_amount", "fee_currency", "exchange_rate", "rate_date", "rate_source", "note"},
    "gcash": {"type", "amount", "currency", "paid_at", "reason", "note", "recipient", "phone", "payment_account", "transaction_reference"},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def require(user, kind, action, *, cache=None):
    if getattr(user, "user_type", None) != "internal" or kind not in PREFIX or not check_user_permission(user, f"{PREFIX[kind]}.{action}", cache=cache):
        raise PermissionDenied("没有当前登记操作权限。")


def scoped(user, kind, action="view", *, include_deleted=False, permission_cache=None):
    require(user, kind, action, cache=permission_cache)
    rows = OrderRegistration.objects.filter(tenant=user.tenant, kind=kind)
    if not include_deleted:
        rows = rows.filter(deleted_at__isnull=True)
    return filter_sales_queryset(user, f"{PREFIX[kind]}.{action}", rows,
                                 {"store_ids": "store_id", "platforms": "store__platform__platform_type", "regions": "store__country_code"},
                                 permission_cache=permission_cache, resource_code="finance.gcash" if kind == "gcash" else "sales_management.sales")


def store_for(user, kind, action, store_id, *, permission_cache=None):
    require(user, kind, action, cache=permission_cache)
    qs = filter_sales_queryset(user, f"{PREFIX[kind]}.{action}", StoreMaster.objects.filter(tenant=user.tenant),
                               {"store_ids": "id", "platforms": "platform__platform_type", "regions": "country_code"},
                               permission_cache=permission_cache, resource_code="finance.gcash" if kind == "gcash" else "sales_management.sales")
    try:
        return qs.get(pk=store_id)
    except (StoreMaster.DoesNotExist, ValueError, TypeError):
        raise PermissionDenied("店铺不在当前授权范围。") from None


def masked(payload):
    value = copy.deepcopy(payload)
    for field in ("phone", "recipient", "payment_account", "transaction_reference"):
        if value.get(field):
            value[field] = "***" + str(value[field])[-4:]
    return value


def audit(row, user, action, before=None, reason=""):
    write_workflow_audit(row, resource_type="order_registration", actor=user, action=action, to_status=row.status,
                         detail={"before": masked(before or {}), "after": masked(row.payload), "version": row.version, "reason": reason})


def pending_detail(order):
    lines = {}
    for item in order.items.all():
        if not item.internal_sku_id:
            raise ValidationError("原订单存在未关联内部SKU的商品，请先完成映射。")
        lines[item.internal_sku_id] = lines.get(item.internal_sku_id, 0) + item.quantity
    if not lines:
        raise ValidationError("原订单没有可用商品明细。")
    original = [{"sku_id": sku, "quantity": qty} for sku, qty in sorted(lines.items())]
    source_hash = digest(original)
    detail, _ = PendingOrderDetail.objects.get_or_create(order=order, defaults={"lines": original, "original_lines": original, "source_hash": source_hash})
    if not detail.adjusted and detail.source_hash != source_hash:
        detail.lines = original
        detail.original_lines = original
        detail.source_hash = source_hash
        detail.version += 1
        detail.save()
    return detail


def exchange_ready(order, detail):
    if order.normalized_status not in {"pending", "confirmed"} or order.cancelled_at_utc:
        raise StateConflict("订单已取消、失效或不再待发货。")
    if detail.outbound_reference or ShipmentRecord.objects.filter(tenant=order.tenant, store=order.store).filter(
        sales_order=order).exists():
        raise StateConflict("订单已关联出库／发运，不能进行发货前换货。")


def validated_payload(kind, data, store, order):
    if not isinstance(data, dict) or set(data) - FIELDS[kind]:
        raise ValidationError("登记包含未支持字段；计算结果、凭据及状态不可直接填写。")
    data = copy.deepcopy(data)
    for field, value in data.items():
        if field != "changes" and (isinstance(value, (dict, list)) or len(str(value)) > 500):
            raise ValidationError({field: "字段格式无效或超过500字符。"})
    if kind == "promotion":
        if order.currency != store.currency:
            raise ValidationError("来源订单币种与店铺站点币种不一致，请先核对。")
        if data.get("rate_date"):
            try:
                date.fromisoformat(data["rate_date"])
            except (ValueError, TypeError):
                raise ValidationError({"rate_date": "请输入有效日期。"}) from None
        data = {**promotion_cost(data, store.currency), "note": data.get("note", ""),
                "source_order_amount": str(order.order_total_amount), "source_amount_field": "order_total_amount"}
    elif kind == "gcash":
        if data.get("type") not in {"refund", "other"}:
            raise ValidationError("类型只能为退款或其他。")
        if data["type"] == "refund" and not order:
            raise ValidationError("退款必须关联当前店铺订单。")
        data["note"] = gcash_remark(data.pop("reason", ""), data.get("note", ""))
        if not data["note"] or len(data["note"]) > 500:
            raise ValidationError({"note": "请填写备注（退款原因或其他支出用途），最多500字符。"})
        data["amount"] = str(money(data.get("amount"), data.get("currency"), "amount"))
        data["paid_at"] = gcash_payment_date(data.get("paid_at", ""))
        if data.get("phone") and (not isinstance(data["phone"], str) or not data["phone"].replace("+", "", 1).isdigit()):
            raise ValidationError("手机号必须为文本数字，可包含开头的加号。")
    elif not str(data.get("reason", "")).strip():
        raise ValidationError("请填写换货原因。")
    return data


@transaction.atomic
def create_registration(user, kind, store_id, order_id, data, key, batch_key="", permission_action="create", *, historical=False, permission_cache=None):
    if type(historical) is not bool or (historical and kind != "exchange"):
        raise ValidationError("历史补录仅适用于换货登记，模式必须为布尔值。")
    store = store_for(user, kind, permission_action, store_id, permission_cache=permission_cache)
    StoreMaster.objects.select_for_update().get(pk=store.pk)
    if not isinstance(key, str) or not 1 <= len(key) <= 100:
        raise ValidationError("登记标识必须为1至100字符。")
    request_hash = digest([kind, store.id, order_id, data])
    if historical:
        request_hash = digest(["historical_exchange", request_hash])
    existing = OrderRegistration.objects.filter(tenant=user.tenant, idempotency_key=key).first()
    if existing:
        if existing.deleted_at:
            raise StateConflict("原登记已删除，请到已删除记录中核对并恢复，不能重复创建。")
        if existing.request_hash != request_hash:
            raise StateConflict("登记标识已被不同内容使用。")
        return existing, False
    order = None
    if order_id:
        try:
            order = SalesOrder.objects.select_for_update().get(pk=order_id, tenant=user.tenant, store=store)
        except (SalesOrder.DoesNotExist, ValueError, TypeError):
            raise ValidationError("订单不属于当前店铺。") from None
    if kind != "gcash" and not order:
        raise ValidationError("必须关联订单。")
    payload = validated_payload(kind, data, store, order)
    active_order, snapshot = None, {}
    if kind == "exchange" and historical:
        lines = {}
        facts = []
        for item in order.items.all():
            if not item.internal_sku_id:
                raise ValidationError("原订单存在未关联内部SKU的商品，请先核对历史商品。")
            lines[item.internal_sku_id] = lines.get(item.internal_sku_id, 0) + item.quantity
            facts.append({"item_id": item.pk, "seller_sku": item.seller_sku,
                          "sku_id": item.internal_sku_id, "quantity": item.quantity})
        if not lines:
            raise ValidationError("原订单没有可核对的商品明细。")
        original = [{"sku_id": sku, "quantity": qty} for sku, qty in sorted(lines.items())]
        after = adjusted_lines(original, payload.get("changes"))
        ids = set(lines) | {line["sku_id"] for line in after}
        if ProductSKU.objects.filter(tenant=order.tenant, pk__in=ids, is_active=True).count() != len(ids):
            raise ValidationError("SKU失效或不属于当前租户。")
        snapshot = {"historical": True, "order_status": order.normalized_status, "order_items": facts,
                    "original": original, "before": original, "after": after, "detail_applied": False}
    elif kind == "exchange":
        detail = pending_detail(order)
        exchange_ready(order, detail)
        if OrderRegistration.objects.filter(active_exchange_order=order).exists():
            raise StateConflict("同一订单已有未结束换货申请。")
        after = validate_adjustment(order, detail, payload)
        active_order = order
        snapshot = {"original": detail.original_lines, "before": detail.lines, "after": after, "detail_version": detail.version}
    row = OrderRegistration.objects.create(tenant=user.tenant, store=store, order=order, kind=kind, payload=payload,
                                          snapshot=snapshot, requested_by=user, idempotency_key=key, request_hash=request_hash,
                                          active_exchange_order=active_order, batch_key=batch_key)
    if historical:
        row.status = "historical_recorded"
        row.save(update_fields=["status"])
    audit(row, user, "historical_record" if historical else "create")
    return row, True


def validate_adjustment(order, detail, payload):
    after = adjusted_lines(detail.lines, payload.get("changes"))
    ids = {row["sku_id"] for row in after} | {row["sku_id"] for row in detail.lines}
    if ProductSKU.objects.filter(tenant=order.tenant, id__in=ids, is_active=True).count() != len(ids):
        raise ValidationError("SKU失效或不属于当前租户。")
    added = {row["new_sku_id"] for row in payload["changes"] if row["action"] in {"add", "replace"}}
    mapped = set(MarketplaceProductMapping.objects.filter(tenant=order.tenant, store_mapping__store=order.store,
                                                         sku_id__in=added, status="mapped").values_list("sku_id", flat=True))
    # Existing order facts with a bound internal SKU are also authoritative mappings.
    mapped.update(order.items.filter(internal_sku_id__in=added).values_list("internal_sku_id", flat=True))
    if added - mapped:
        raise ValidationError("新增SKU尚未完成当前店铺商品映射。")
    return after


def locked_registration(user, kind, pk, action, *, include_deleted=False, permission_cache=None):
    row = scoped(user, kind, action, include_deleted=include_deleted, permission_cache=permission_cache).filter(pk=pk).first()
    if not row:
        raise PermissionDenied("登记不在当前授权范围。")
    StoreMaster.objects.select_for_update().get(pk=row.store_id)
    if row.order_id:
        SalesOrder.objects.select_for_update().get(pk=row.order_id)
    row = OrderRegistration.objects.select_for_update().select_related("order", "store", "approval").get(pk=row.pk)
    if row.deleted_at and not include_deleted:
        raise PermissionDenied("登记已删除，请到已删除记录恢复后再操作。")
    return row


@transaction.atomic
def set_registration_deleted(user, kind, pk, version, reason="", *, restore=False):
    row = locked_registration(user, kind, pk, "edit", include_deleted=True)
    if type(version) is not int or version <= 0 or not isinstance(reason, str) or len(reason) > 500:
        raise ValidationError("请提供当前版本号及不超过500字符的原因。")
    if row.version != version:
        raise StateConflict("登记版本已变化，请刷新后重试。")
    if row.status not in EDITABLE:
        raise StateConflict("仅草稿、已驳回或已撤回记录可删除／恢复；审批中须先撤回，正式登记须作废，已完成换货保留历史。")
    if restore:
        if not row.deleted_at:
            raise StateConflict("该登记未删除，无需恢复。")
        if kind == "exchange":
            if OrderRegistration.objects.filter(active_exchange_order=row.order).exclude(pk=row.pk).exists():
                raise StateConflict("该订单已有另一张处理中换货登记，不能恢复占用。")
            detail = pending_detail(row.order)
            exchange_ready(row.order, detail)
            row.snapshot = {"original": detail.original_lines, "before": detail.lines,
                            "after": validate_adjustment(row.order, detail, row.payload), "detail_version": detail.version}
            row.active_exchange_order = row.order
        row.deleted_at, row.deleted_by, row.delete_reason = None, None, ""
    else:
        if row.deleted_at:
            raise StateConflict("该登记已删除，请勿重复操作。")
        if not reason.strip():
            raise ValidationError("请填写删除原因。")
        row.deleted_at, row.deleted_by, row.delete_reason = timezone.now(), user, reason.strip()
        row.active_exchange_order = None
    row.version += 1
    row.save()
    audit(row, user, "restore" if restore else "delete", reason=reason.strip())
    return row


@transaction.atomic
def edit_registration(user, kind, pk, payload, version, reason=""):
    row = locked_registration(user, kind, pk, "edit")
    if not isinstance(payload, dict) or type(version) is not int or not isinstance(reason, str) or len(reason) > 500:
        raise ValidationError("登记内容、版本号或更正原因格式无效。")
    if row.version != version:
        raise StateConflict("登记版本已变化，请刷新后重试。")
    if row.status not in EDITABLE and not (kind in {"gcash", "promotion"} and row.status == "registered" and str(reason).strip()):
        raise StateConflict("待审批内容已锁定；已登记更正必须提供原因。")
    before = copy.deepcopy(row.payload)
    # Accept only user fields; calculated/source fields never round-trip as inputs.
    current = {k: v for k, v in row.payload.items() if k in FIELDS[kind]}
    if kind == "gcash":
        current["note"] = gcash_remark(current.pop("reason", ""), current.get("note", ""))
    data = validated_payload(kind, {**current, **payload}, row.store, row.order)
    if kind == "exchange":
        detail = pending_detail(row.order)
        exchange_ready(row.order, detail)
        row.snapshot = {"original": detail.original_lines, "before": detail.lines,
                        "after": validate_adjustment(row.order, detail, data), "detail_version": detail.version}
    row.payload = data
    if kind == "gcash" and row.status == "registered":
        row.transaction_key = gcash_key(row)
        prevent_duplicate_transaction(row)
    if kind == "promotion" and row.status == "registered":
        row.snapshot = copy.deepcopy(data)
    row.version += 1
    row.save()
    audit(row, user, "correct" if row.status == "registered" else "edit", before, reason)
    return row


def gcash_key(row):
    account = row.payload.get("payment_account") or ""
    reference = row.payload.get("transaction_reference") or ""
    if not isinstance(account, str) or not isinstance(reference, str):
        raise ValidationError("付款账户标识和交易参考号如有填写，必须为文本。")
    if not account.strip() or not reference.strip():
        return None
    return digest([row.tenant_id, account.strip(), reference.strip()])


def prevent_duplicate_transaction(row):
    if row.transaction_key and OrderRegistration.objects.exclude(pk=row.pk).filter(transaction_key=row.transaction_key).exists():
        raise StateConflict("此付款账户的交易参考号已登记，包括作废记录。")


def registration_action(user, kind, pk, action, note="", *, expected_version=None, expected_approval_id=None):
    row = _registration_decision(user, kind, pk, action, note, expected_version=expected_version, expected_approval_id=expected_approval_id)
    if kind == "exchange" and action in {"approve", "apply"}:
        try:
            return apply_exchange_detail(user, row.pk)
        except (APIException, DatabaseError, RuntimeError) as exc:
            # The approved snapshot is retained. A failed detail update is never
            # represented as completed, and retry cannot change approved contents.
            with transaction.atomic():
                current = locked_registration(user, kind, row.pk, "approve")
                if current.status == "completed":
                    return current
                if current.status not in {"pending_update", "update_failed"}:
                    raise
                current.status = "update_failed"
                current.snapshot["update_error"] = "state_conflict" if isinstance(exc, StateConflict) else "detail_update_failed"
                current.version += 1
                current.save()
                audit(current, user, "update_failed")
                return current
    return row


@transaction.atomic
def _registration_decision(user, kind, pk, action, note="", *, expected_version=None, expected_approval_id=None):
    if not isinstance(note, str) or len(note) > 500:
        raise ValidationError("操作说明必须为不超过500字符的文本。")
    permission = {"submit": "submit", "approve": "approve", "reject": "approve", "withdraw": "submit", "register": "edit", "void": "edit", "cancel": "edit", "apply": "approve"}.get(action)
    allowed = {"exchange": {"submit", "approve", "reject", "withdraw", "cancel", "apply"},
               "promotion": {"register", "void", "cancel", "withdraw"}, "gcash": {"register", "void"}}
    if not permission or action not in allowed.get(kind, set()):
        raise ValidationError("不支持当前登记操作。")
    if kind == "promotion" and action == "withdraw":
        permission = "edit"
    row = locked_registration(user, kind, pk, permission)
    if row.status == "historical_recorded" or row.snapshot.get("historical"):
        raise StateConflict("历史补录仅供留档，不能提交审批或执行商品调整。")
    if expected_version is not None and row.version != expected_version:
        raise StateConflict("登记内容／审批版本已变更，请重新查看后操作。")
    if expected_approval_id is not None and row.approval_id != expected_approval_id:
        raise StateConflict("该审批不是当前提交版本，不能处理新申请。")
    if action in {"submit", "withdraw"} and row.requested_by_id != user.id:
        raise PermissionDenied("只有申请人可以提交或撤回。")
    before = copy.deepcopy(row.payload)
    if action == "apply":
        if kind != "exchange" or row.status not in {"pending_update", "update_failed"} or not row.approval_id or row.approval.status != "approved":
            raise StateConflict("只有已审批通过但明细尚未更新的申请可重试更新。")
        return row
    if action == "cancel":
        if row.status == "update_failed" and kind == "exchange":
            require(user, kind, "approve")
            if not str(note).strip():
                raise ValidationError("取消更新异常申请必须说明原因；审批记录仍保留。")
        elif row.status not in EDITABLE:
            raise StateConflict("只能取消草稿、驳回或撤回登记。")
        row.status = "cancelled"
        row.active_exchange_order = None
    elif action == "register":
        if kind == "gcash":
            if row.status != "draft" or not row.evidence.exists():
                raise StateConflict("只能登记已上传完整截图的草稿。")
            row.transaction_key = gcash_key(row)
            prevent_duplicate_transaction(row)
        else:
            if row.status not in EDITABLE | {"approved"}:
                raise StateConflict("只能确认草稿、驳回、撤回或旧审批已通过的推广登记；旧待审批记录需先撤回。")
            row.payload = validated_payload(kind, {k: v for k, v in row.payload.items() if k in FIELDS[kind]}, row.store, row.order)
            row.snapshot = copy.deepcopy(row.payload)
        row.status = "registered"
    elif action == "void":
        if row.status != "registered" or not str(note).strip():
            raise StateConflict("仅可作废已登记记录，且必须说明原因；不会撤销实际交易。")
        row.status = "void"
    elif action == "submit":
        if row.status not in EDITABLE:
            raise StateConflict("只能提交草稿、驳回或撤回申请。")
        if kind == "exchange":
            detail = pending_detail(row.order)
            exchange_ready(row.order, detail)
            after = validate_adjustment(row.order, detail, row.payload)
            row.snapshot = {"original": detail.original_lines, "before": detail.lines, "after": after, "detail_version": detail.version}
        approval = ApprovalRequest.objects.create(tenant=row.tenant, approval_type="purchase",
                                                  title=f"{row.get_kind_display()} #{row.pk}", business_type="order_registration", business_id=str(row.pk),
                                                  requested_by=user, reason=row.payload.get("reason", ""), idempotency_key=f"registration:{row.pk}:{row.version}")
        row.approval = approval
        row.status = "pending"
    else:
        if row.status != "pending" or not row.approval_id or row.approval.status != "pending":
            raise StateConflict("只能处理当前待审批申请，重复审批不会再次执行。")
        if action in {"approve", "reject"} and row.requested_by_id == user.id:
            raise PermissionDenied("申请人不能审批自己提交的登记。")
        if action == "approve" and kind == "exchange":
            detail = pending_detail(row.order)
            exchange_ready(row.order, detail)
            if detail.version != row.snapshot["detail_version"] or detail.lines != row.snapshot["before"]:
                raise StateConflict("待发货明细已变更，审批停止，请撤回后重新提交。")
            after = validate_adjustment(row.order, detail, row.payload)
            if after != row.snapshot["after"]:
                raise StateConflict("商品映射或申请快照已变化。")
        row.status = {"approve": "pending_update" if kind == "exchange" else "approved", "reject": "rejected", "withdraw": "withdrawn"}[action]
        row.approval.status = {"approve": "approved", "reject": "rejected", "withdraw": "withdrawn"}[action]
        row.approval.reviewed_by = user if action != "withdraw" else None
        row.approval.decision_note = note
        from django.utils import timezone
        row.approval.decided_at = timezone.now()
        row.approval.save()
    if row.status == "completed":
        row.active_exchange_order = None
    row.version += 1
    try:
        row.save()
    except IntegrityError:
        raise StateConflict("登记与其他并发操作冲突，请刷新核对。") from None
    audit(row, user, action, before, note)
    return row


@transaction.atomic
def apply_exchange_detail(user, pk):
    row = locked_registration(user, "exchange", pk, "approve")
    if row.status == "historical_recorded" or row.snapshot.get("historical"):
        raise StateConflict("历史补录不能更新待发货明细。")
    if row.status == "completed":
        return row
    if row.status not in {"pending_update", "update_failed"} or row.approval.status != "approved":
        raise StateConflict("申请尚未审批通过或已取消。")
    detail = pending_detail(row.order)
    exchange_ready(row.order, detail)
    if detail.version != row.snapshot["detail_version"] or detail.lines != row.snapshot["before"]:
        raise StateConflict("待发货明细已变化，请取消本次异常申请后重新申请审批。")
    after = validate_adjustment(row.order, detail, row.payload)
    if after != row.snapshot["after"]:
        raise StateConflict("批准的商品快照已变化。")
    detail.lines = after
    detail.adjusted = True
    detail.version += 1
    detail.save()
    row.snapshot.pop("update_error", None)
    row.status = "completed"
    row.active_exchange_order = None
    row.version += 1
    row.save()
    audit(row, user, "detail_updated")
    return row


@transaction.atomic
def upload_evidence(user, kind, pk, uploaded, permission_action="edit", *, permission_cache=None):
    row = locked_registration(user, kind, pk, permission_action, permission_cache=permission_cache)
    if row.status not in EDITABLE:
        raise StateConflict("仅草稿／驳回／撤回状态可上传凭证。")
    if not uploaded or uploaded.size > 5 * 1024 * 1024 or row.evidence.count() >= 10:
        raise ValidationError("最多10张截图，每张不超过5MB。")
    content = uploaded.read()
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"PNG", "JPEG"} or image.width * image.height > 20000000:
                raise ValueError()
            media = "image/png" if image.format == "PNG" else "image/jpeg"
            image.verify()
    except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError("只允许完整的PNG／JPEG截图。") from None
    evidence, _ = RegistrationEvidence.objects.get_or_create(registration=row, sha256=hashlib.sha256(content).hexdigest(),
                                                             defaults={"name": uploaded.name[:180], "media_type": media, "content": content, "uploaded_by": user})
    audit(row, user, "evidence_upload")
    return evidence


def representation(row, user):
    data = copy.deepcopy(row.payload)
    if row.kind == "gcash":
        data["note"] = gcash_remark(data.pop("reason", ""), data.get("note", ""))
    if row.kind == "gcash" and data.get("paid_at"):
        data["paid_at"] = gcash_payment_date(data["paid_at"])
    sensitive = row.kind == "gcash" and check_user_permission(user, "finance.gcash.sensitive") and scoped(user, "gcash", "sensitive", include_deleted=True).filter(pk=row.pk).exists()
    if row.kind == "gcash" and not sensitive:
        data = masked(data)
    gcash_totals = {}
    platform_totals = {}
    sku_details = []
    if row.kind == "exchange":
        sku_ids = {line.get("sku_id") for key in ("original", "before", "after") for line in row.snapshot.get(key, [])}
        sku_ids.update(change.get(field) for change in data.get("changes", []) for field in ("old_sku_id", "new_sku_id"))
        sku_details = list(ProductSKU.objects.filter(tenant=row.tenant, pk__in=[pk for pk in sku_ids if type(pk) is int])
                           .order_by("pk").values("id", "sku_code", "legacy_sku_code"))
    if row.kind == "gcash" and row.order_id:
        refunds = OrderRegistration.objects.filter(tenant=row.tenant, order=row.order, store=row.store, kind="gcash", status="registered", payload__type="refund")
        for payload in refunds.values_list("payload", flat=True):
            currency = payload["currency"]
            gcash_totals[currency] = gcash_totals.get(currency, Decimal(0)) + Decimal(payload["amount"])
        from django.db.models import Sum
        for refund in RefundReturn.objects.filter(tenant=row.tenant, store=row.store, sales_order=row.order, normalized_status="completed").values("currency").annotate(total=Sum("refund_amount")):
            platform_totals[refund["currency"]] = str(refund["total"])
    return {"id": row.pk, "kind": row.kind, "status": row.status, "version": row.version, "store_id": row.store_id,
            "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None, "deleted_by_name": row.deleted_by.username if row.deleted_by_id else "", "delete_reason": row.delete_reason,
            "approval_status": row.approval.status if row.approval_id else None, "detail_updated": row.status == "completed" if row.kind == "exchange" else None,
            "store": row.store.name, "store_code": row.store.code, "order_id": row.order_id, "order_number": row.order.external_order_id if row.order_id else "",
            "payload": data, "snapshot": row.snapshot, "sku_details": sku_details, "requested_by": row.requested_by_id,
            "requested_by_name": row.requested_by.username, "can_view_evidence": row.kind != "gcash" or sensitive,
            "created_at": row.created_at.isoformat(), "evidence_count": row.evidence.count(), "evidence": [{"id": e.id, "name": e.name} for e in row.evidence.all()] if row.kind != "gcash" or sensitive else [],
            "duplicate_order_count": OrderRegistration.objects.filter(tenant=row.tenant, kind=row.kind, order=row.order, deleted_at__isnull=True).exclude(pk=row.pk).count() if row.order_id else 0,
            "gcash_registered_refunds": {currency: str(total) for currency, total in gcash_totals.items()}, "platform_completed_refunds": platform_totals,
            "audit": list(WorkflowAuditEvent.objects.filter(tenant=row.tenant, resource_type="order_registration", resource_id=str(row.pk)).order_by("created_at", "id").values("action", "actor_id", "actor__username", "to_status", "masked_detail", "created_at"))}
