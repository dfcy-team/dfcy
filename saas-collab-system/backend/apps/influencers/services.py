import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Exists, Model, OuterRef, Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant

from .models import (
    FulfillmentStatusEvent,
    Influencer,
    InfluencerRestrictEvent,
    InfluencerRestriction,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
    StoreProductListing,
    VideoResult,
    influencer_identity_key,
    influencer_identity_queryset,
)
from .attribution import create_sample_attribution_snapshot


TERMINAL_OUTREACH_TASK_STATUSES = frozenset(
    {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}
)
OUTREACH_RESULT_TRANSITIONS = {
    OutreachTarget.OutreachResult.PENDING: frozenset(
        {
            OutreachTarget.OutreachResult.SUCCESS,
            OutreachTarget.OutreachResult.REJECTED,
            OutreachTarget.OutreachResult.NO_RESPONSE,
            OutreachTarget.OutreachResult.BLOCKED,
        }
    ),
    OutreachTarget.OutreachResult.SUCCESS: frozenset(),
    OutreachTarget.OutreachResult.REJECTED: frozenset(),
    OutreachTarget.OutreachResult.NO_RESPONSE: frozenset(),
    OutreachTarget.OutreachResult.BLOCKED: frozenset(),
}
OUTREACH_TASK_NO_MAX_ATTEMPTS = 5
SAMPLE_COMPLETION_STATUSES = frozenset(
    {
        SampleFulfillment.Status.PUBLISHED,
        SampleFulfillment.Status.COMPLETED,
        SampleFulfillment.Status.LIVE_CREATOR,
    }
)
SAMPLE_TERMINAL_STATUSES = frozenset(
    {
        SampleFulfillment.Status.COMPLETED,
        SampleFulfillment.Status.CANCELLED,
        SampleFulfillment.Status.BLACKLISTED,
    }
)
SAMPLE_TIMEOUT_CANDIDATE_STATUSES = frozenset(
    {
        SampleFulfillment.Status.PENDING,
        # Keep processing records from the pre-0012 state machine eligible for
        # the same timeout reconciliation while they are being normalized.
        SampleFulfillment.Status.PROCESSING,
        SampleFulfillment.Status.SHIPPED,
        SampleFulfillment.Status.DELIVERED,
    }
)
SAMPLE_VIDEO_RECONCILE_STATUSES = frozenset(
    set(SampleFulfillment.Status.values).difference(
        SAMPLE_TERMINAL_STATUSES | SAMPLE_COMPLETION_STATUSES
    )
)


def _generate_outreach_task_no(tenant):
    """Allocate the next compact, human-readable task number for a tenant."""
    numeric_suffixes = []
    for task_no in OutreachTask.objects.filter(
        tenant=tenant, task_no__startswith="DRJL"
    ).values_list("task_no", flat=True):
        match = re.fullmatch(r"DRJL(\d+)", task_no or "")
        if match:
            numeric_suffixes.append(int(match.group(1)))
    return f"DRJL{max(numeric_suffixes, default=0) + 1:04d}"


def _generate_sample_fulfillment_no(tenant, link_type):
    """Allocate a compact per-channel fulfillment number within a tenant."""
    prefix = link_type if link_type in dict(SampleFulfillment.LINK_TYPE_CHOICES) else "BDJL"
    numeric_suffixes = []
    for fulfillment_no in SampleFulfillment.objects.filter(
        tenant=tenant, fulfillment_no__startswith=prefix
    ).values_list("fulfillment_no", flat=True):
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", fulfillment_no or "")
        if match:
            numeric_suffixes.append(int(match.group(1)))
    return f"{prefix}{max(numeric_suffixes, default=0) + 1:04d}"


def _assert_task_accepts_target(task, *, allow_completed=False):
    blocked_statuses = {OutreachTask.Status.CANCELLED}
    if not allow_completed:
        blocked_statuses.add(OutreachTask.Status.COMPLETED)
    if task.status in blocked_statuses:
        raise ValidationError(
            {"outreach_task": "Completed or cancelled outreach tasks cannot change targets or samples."},
            code="conflict",
        )


def _canonical_scalar(value):
    """Reduce request data to deterministic JSON scalars and relation primary keys."""
    if isinstance(value, Model):
        return _canonical_scalar(value.pk)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_scalar(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_scalar(item) for item in value]
    if isinstance(value, set):
        return sorted(
            (_canonical_scalar(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return value


def _payload_hash(payload):
    encoded = json.dumps(
        _canonical_scalar(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit(user, action, object_type, instance, before=None, after=None):
    write_operation_log(
        tenant=user.tenant,
        user=user,
        module="influencers",
        action=action,
        object_type=object_type,
        object_id=instance.pk,
        before_data=before or {},
        after_data=after or {},
    )


def _save(instance):
    try:
        instance.save()
    except DjangoValidationError as exc:
        raise ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        ) from exc


def _cas_state_update(instance, *, tenant, expected_status, expected_version, **changes):
    queryset = type(instance).objects.filter(
        pk=instance.pk,
        tenant=tenant,
        status=expected_status,
        version=expected_version,
    )
    updated = QuerySet.update(queryset, **changes)
    if updated != 1:
        raise ValidationError(
            {"version": "Workflow record was changed by another request."},
            code="conflict",
        )
    instance.refresh_from_db()


def _pk(value):
    return getattr(value, "pk", value)


def _tenant_influencer(user, influencer_id, *, for_update):
    queryset = Influencer.objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        influencer = queryset.get(pk=influencer_id, tenant=user.tenant)
    except Influencer.DoesNotExist as exc:
        raise ValidationError(
            {"influencer": "Influencer does not exist in the current tenant."}
        ) from exc
    if influencer.status != Influencer.Status.ACTIVE:
        raise ValidationError(
            {"influencer": "Inactive influencers cannot be linked to outreach tasks or receive samples."},
            code="conflict",
        )
    return influencer


def _lock_tenant(user):
    """Serialize tenant-scoped workflow writes before locking child rows."""
    return Tenant.objects.select_for_update().get(pk=user.tenant_id)


def _locked_influencer(user, influencer_id):
    return _lock_influencer_identity(user=user, influencer=influencer_id)[0]


def _lock_influencer_identity(*, user, influencer):
    """Lock the complete tenant-scoped handle identity and return its member."""
    selected = Influencer.objects.get(pk=_pk(influencer), tenant_id=user.tenant_id)
    identity_profiles = list(influencer_identity_queryset(selected, for_update=True))
    locked = next((profile for profile in identity_profiles if profile.pk == selected.pk), None)
    if locked is None:
        raise ValidationError({"influencer": "Influencer identity group is empty."})
    if locked.status != Influencer.Status.ACTIVE:
        raise ValidationError(
            {"influencer": "Inactive influencers cannot be linked to outreach tasks or receive samples."},
            code="conflict",
        )
    return locked, [profile.pk for profile in identity_profiles]


def _locked_store(user, store_id):
    return _tenant_store(user, store_id, for_update=True)


def _tenant_store(user, store_id, *, for_update):
    queryset = StoreMaster.objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=store_id, tenant=user.tenant)
    except StoreMaster.DoesNotExist as exc:
        raise ValidationError(
            {"store": "Store does not exist in the current tenant."}
        ) from exc


def _locked_user(user, user_id, field="owner"):
    return _tenant_user(user, user_id, field=field, for_update=True)


def _tenant_user(user, user_id, *, field="owner", for_update):
    if user_id is None:
        raise ValidationError({field: f"{field.capitalize()} is required."})
    queryset = get_user_model().objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=user_id, tenant=user.tenant)
    except get_user_model().DoesNotExist as exc:
        raise ValidationError(
            {field: f"{field.capitalize()} does not exist in the current tenant."}
        ) from exc


def _assert_active_bd_owner(user, owner):
    if (
        not owner.is_active
        or owner.user_type != owner.UserType.INTERNAL
        or not owner.user_roles.filter(
            tenant=user.tenant,
            role__tenant=user.tenant,
            role__code="bd",
            role__status="active",
        ).exists()
    ):
        raise ValidationError({"owner": "Owner must be an active BD user in the current tenant."})


def _locked_spu(user, spu_id):
    if spu_id is None:
        return None
    try:
        return ProductSPU.objects.select_for_update().get(pk=spu_id, tenant=user.tenant)
    except ProductSPU.DoesNotExist as exc:
        raise ValidationError(
            {"spu": "Product does not exist in the current tenant."}
        ) from exc


def _locked_task(user, task_id):
    return _tenant_task(user, task_id, for_update=True)


def _tenant_task(user, task_id, *, for_update):
    queryset = OutreachTask.objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=task_id, tenant=user.tenant)
    except OutreachTask.DoesNotExist as exc:
        raise ValidationError(
            {"outreach_task": "Outreach task does not exist in the current tenant."}
        ) from exc


def _locked_target(user, target_id):
    return _tenant_target(user, target_id, for_update=True)


def _tenant_target(user, target_id, *, for_update):
    queryset = OutreachTarget.objects
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(pk=target_id, tenant=user.tenant)
    except OutreachTarget.DoesNotExist as exc:
        raise ValidationError(
            {"outreach_target": "Outreach target does not exist in the current tenant."}
        ) from exc


def _lock_task_relations(
    user,
    *,
    task_id,
    target_id,
    influencer_id=None,
    store_id=None,
    owner_id=None,
    external_product_id=None,
):
    """Discover relations without locks, then lock identity before task-owned rows."""
    task = _tenant_task(user, task_id, for_update=False)
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive samples."})
    _assert_task_accepts_target(task, allow_completed=True)

    influencer = None
    if target_id is not None:
        target = _tenant_target(user, target_id, for_update=False)
        if target.task_id != task.pk:
            raise ValidationError({"outreach_target": "Target must belong to the outreach task."})
        if target.is_deleted:
            raise ValidationError({"outreach_target": "Deleted outreach targets cannot receive samples."})
        influencer = _tenant_influencer(
            user,
            target.influencer_id,
            for_update=False,
        )
    else:
        if influencer_id is None:
            raise ValidationError(
                {"influencer": "Influencer is required when outreach_target is omitted."}
            )
        influencer = _tenant_influencer(
            user,
            _pk(influencer_id),
            for_update=False,
        )
        target = None

    if influencer_id is not None and _pk(influencer_id) != influencer.pk:
        raise ValidationError({"influencer": "Influencer must match the outreach target."})
    if target is None and task.influencer_id is not None and task.influencer_id != influencer.pk:
        raise ValidationError({"influencer": "Influencer must match the outreach task."})

    # Identity is the first influencer business lock. Task and target rows are
    # locked only after the complete handle group has been serialized.
    influencer = _assert_influencer_not_blacklisted(user=user, influencer=influencer)
    task = _locked_task(user, task.pk)
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive samples."})
    _assert_task_accepts_target(task, allow_completed=True)

    if target is not None:
        target = _locked_target(user, target.pk)
        if target.task_id != task.pk:
            raise ValidationError({"outreach_target": "Target must belong to the outreach task."})
        if target.is_deleted:
            raise ValidationError({"outreach_target": "Deleted outreach targets cannot receive samples."})
        if target.influencer_id != influencer.pk:
            raise ValidationError({"influencer": "Influencer must match the outreach target."})
    elif task.influencer_id is not None and task.influencer_id != influencer.pk:
        raise ValidationError({"influencer": "Influencer must match the outreach task."})

    store = _locked_store(user, task.store_id)
    if store_id is not None and _pk(store_id) != store.pk:
        raise ValidationError({"store": "Store must match the outreach task."})

    owner = _locked_user(user, task.owner_id)
    if owner_id is not None and _pk(owner_id) != owner.pk:
        raise ValidationError({"owner": "Owner must match the outreach task."})

    task_product_id = (task.external_product_id or "").strip()
    supplied_product_id = (str(external_product_id).strip() if external_product_id is not None else "")
    if supplied_product_id and supplied_product_id != task_product_id:
        raise ValidationError({"external_product_id": "Product must match the outreach task."})

    if task.spu_id:
        _locked_spu(user, task.spu_id)
    return task, target, influencer, store, owner


def _product_snapshot(user, task, store):
    product_id = (task.external_product_id or "").strip()
    product_name = (task.product_name_snapshot or "").strip()
    if task.spu_id:
        product_name = product_name or (
            ProductSPU.objects.filter(pk=task.spu_id, tenant=user.tenant)
            .values_list("product_name", flat=True)
            .first()
            or ""
        )
    if not product_name and product_id:
        product_name = product_name or (
            StoreProductListing.objects.filter(
                tenant=user.tenant,
                store_id=store.pk,
                external_product_id=product_id,
            )
            .order_by("-source_updated_at", "-id")
            .values_list("product_name", flat=True)
            .first()
            or ""
        )
    return product_id, product_name


def _normalize_item_payloads(item_payloads):
    normalized = []
    for payload in item_payloads:
        item = dict(payload)
        requested_sku = item.get("requested_sku")
        item["requested_sku"] = (
            str(requested_sku).strip() or None if requested_sku is not None else None
        )
        site_code = str(item.get("site_code") or "").strip()
        if not site_code:
            raise ValidationError({"items": "Each sample item requires site_code."})
        item["site_code"] = site_code
        try:
            quantity = int(item.get("quantity") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"items": "Each sample item quantity must be a positive integer."}) from exc
        if quantity < 1:
            raise ValidationError({"items": "Each sample item quantity must be positive."})
        item["quantity"] = quantity
        normalized.append(item)
    return normalized


def _normalize_quick_tags(value):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError({"quick_tags": "Quick tags must be a list."})
    normalized = []
    for raw_tag in value:
        tag = str(raw_tag or "").strip()
        if not tag:
            raise ValidationError({"quick_tags": "Quick tags cannot be empty."})
        if len(tag) > 80:
            raise ValidationError({"quick_tags": "Each quick tag must be at most 80 characters."})
        if tag not in normalized:
            normalized.append(tag)
    if len(normalized) > 20:
        raise ValidationError({"quick_tags": "At most 20 quick tags are allowed."})
    return normalized


def _sample_item_payload(item):
    """Keep only editable item facts when an append operation reuses an existing row."""
    return {
        "sku": item.sku,
        "external_product_id": item.external_product_id,
        "site_code": item.site_code,
        "requested_sku": item.requested_sku,
        "product_name": item.product_name,
        "quantity": item.quantity,
    }


def _recalculate_sample_pricing(*, user, fulfillment, item_payloads):
    """Replace item snapshots and aggregate price/cost facts in the same transaction."""
    item_payloads = _normalize_item_payloads(item_payloads)
    SampleItem.objects.filter(
        tenant=user.tenant,
        fulfillment=fulfillment,
    ).delete()

    sku_quantity = 0
    sales_total = Decimal("0")
    cost_total = Decimal("0")
    all_prices_matched = True
    all_costs_matched = True
    any_price_matched = False
    any_cost_matched = False
    snapshot_time = timezone.now()
    for raw_payload in item_payloads:
        payload = _inherit_item_product(
            raw_payload,
            product_id=fulfillment.external_product_id,
            product_name=fulfillment.product_name_snapshot,
        )
        # Computed snapshot fields must never be accepted from a client or reused verbatim.
        for field_name in (
            "id",
            "normalized_sku",
            "matched_sku_code",
            "matched_legacy_sku_code",
            "unit_price",
            "unit_cost",
            "sales_amount",
            "cost_amount",
            "currency",
            "price_match_status",
            "cost_match_status",
            "price_source",
            "cost_source",
            "price_snapshot_at",
            "cost_snapshot_at",
            "match_notes",
            "created_at",
            "updated_at",
        ):
            payload.pop(field_name, None)
        snapshot = _price_for_item(user.tenant, fulfillment.store_id, payload)
        normalized_sku, cost_sku, cost_status = _purchase_cost_for_payload(user.tenant, payload)
        quantity = payload.get("quantity", 1)
        unit_price = snapshot.effective_price if snapshot else None
        unit_cost = cost_sku.purchase_price if cost_sku else None
        sales_amount = unit_price * quantity if unit_price is not None else None
        cost_amount = unit_cost * quantity if unit_cost is not None else None
        item = SampleItem(
            tenant=user.tenant,
            fulfillment=fulfillment,
            unit_price=unit_price,
            unit_cost=unit_cost,
            currency=snapshot.currency if snapshot else "",
            price_match_status="matched" if snapshot else "not_imported",
            normalized_sku=normalized_sku,
            matched_sku_code=cost_sku.sku_code if cost_sku else "",
            matched_legacy_sku_code=cost_sku.legacy_sku_code if cost_sku else "",
            sales_amount=sales_amount,
            cost_amount=cost_amount,
            cost_match_status=cost_status,
            price_source=snapshot.source if snapshot else "",
            cost_source="products_productsku" if cost_sku else "",
            price_snapshot_at=snapshot_time if snapshot else None,
            cost_snapshot_at=snapshot_time if cost_sku else None,
            **payload,
        )
        _save(item)
        sku_quantity += quantity
        if sales_amount is None:
            all_prices_matched = False
        else:
            sales_total += sales_amount
            any_price_matched = True
        if cost_amount is None:
            all_costs_matched = False
        else:
            cost_total += cost_amount
            any_cost_matched = True

    has_items = sku_quantity > 0
    if not has_items:
        pricing_status = "pending"
    elif all_prices_matched and all_costs_matched:
        pricing_status = "full"
    elif any_price_matched or any_cost_matched:
        pricing_status = "partial"
    else:
        pricing_status = "not_found"
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk, tenant=user.tenant),
        sku_quantity=sku_quantity,
        sales_amount=sales_total if any_price_matched else None,
        calculated_cost=cost_total if any_cost_matched else None,
        pricing_status=pricing_status,
        priced_at=snapshot_time if has_items else None,
        updated_at=snapshot_time,
    )
    fulfillment.refresh_from_db()
    return fulfillment


def _inherit_item_product(payload, *, product_id, product_name):
    item = dict(payload)
    supplied_product_id = str(item.get("external_product_id") or "").strip()
    if product_id and supplied_product_id and supplied_product_id != product_id:
        raise ValidationError({"items": "Item product must match the outreach task."})
    item["external_product_id"] = supplied_product_id or product_id
    if not str(item.get("product_name") or "").strip() and product_name:
        item["product_name"] = product_name
    return item


def _price_for_item(tenant, store_id, payload):
    sku = str(payload.get("requested_sku") or "").strip()
    product_id = str(payload.get("external_product_id") or "").strip()
    site_code = str(payload.get("site_code") or "").strip()
    if not sku:
        return None
    queryset = SkuPriceSnapshot.objects.select_related("listing").filter(
        tenant=tenant,
        listing__tenant=tenant,
        listing__store_id=store_id,
        listing__site_code=site_code,
        external_sku__iexact=sku,
    )
    if product_id:
        queryset = queryset.filter(listing__external_product_id=product_id)
    return queryset.order_by("-source_updated_at", "-imported_at", "-id").first()


def _normalize_sku(value):
    return "-".join(part for part in str(value or "").strip().upper().replace("_", "-").split("-") if part)


def _purchase_cost_for_item(tenant, requested_sku):
    normalized = _normalize_sku(requested_sku)
    if not normalized:
        return normalized, None, "pending"
    exact_new = ProductSKU.objects.filter(
        tenant=tenant, is_active=True, sku_code__iexact=str(requested_sku).strip()
    ).order_by("id")
    if exact_new.count() == 1:
        sku = exact_new.first()
        return normalized, sku, "matched_new_sku" if sku.purchase_price is not None else "not_priced"
    exact_old = ProductSKU.objects.filter(
        tenant=tenant, is_active=True, legacy_sku_code__iexact=str(requested_sku).strip()
    ).order_by("id")
    if exact_old.count() == 1:
        sku = exact_old.first()
        return normalized, sku, "matched_legacy_sku" if sku.purchase_price is not None else "not_priced"
    candidates = list(ProductSKU.objects.filter(tenant=tenant, is_active=True).filter(
        Q(sku_code__iexact=normalized)
        | Q(legacy_sku_code__iexact=normalized)
        | Q(sku_code__iexact=normalized.replace("-", "_"))
        | Q(legacy_sku_code__iexact=normalized.replace("-", "_"))
    ).order_by("id")[:2])
    if len(candidates) == 1:
        sku = candidates[0]
        return normalized, sku, "matched_normalized" if sku.purchase_price is not None else "not_priced"
    return normalized, None, "ambiguous" if candidates else "not_found"


def _purchase_cost_for_payload(tenant, payload):
    selected_sku = payload.get("sku")
    requested_sku = payload.get("requested_sku")
    if selected_sku is not None:
        if selected_sku.tenant_id != tenant.id or not selected_sku.is_active:
            raise ValidationError({"sku": "SKU must be active and belong to the current tenant."})
        requested_normalized = _normalize_sku(requested_sku)
        new_normalized = _normalize_sku(selected_sku.sku_code)
        legacy_normalized = _normalize_sku(selected_sku.legacy_sku_code)
        if requested_normalized and requested_normalized not in {new_normalized, legacy_normalized}:
            raise ValidationError({"requested_sku": "Requested SKU must match the selected SKU."})
        matched_status = (
            "matched_legacy_sku"
            if requested_normalized and requested_normalized == legacy_normalized
            else "matched_new_sku"
        )
        status = matched_status if selected_sku.purchase_price is not None else "not_priced"
        return _normalize_sku(selected_sku.sku_code), selected_sku, status
    return _purchase_cost_for_item(tenant, requested_sku)


def _product_snapshot_fields(*, tenant, store, external_product_id, fallback_name):
    external_product_id = str(external_product_id or "").strip()
    listing = (
        StoreProductListing.objects.filter(
            tenant=tenant,
            store=store,
            external_product_id=external_product_id,
        )
        .order_by("-source_updated_at", "-updated_at", "-id")
        .first()
        if external_product_id
        else None
    )
    if listing:
        return {
            "external_product_id": external_product_id,
            "product_name_snapshot": listing.product_name,
            "product_match_status": "matched",
            "product_match_source": listing.source,
            "product_matched_at": timezone.now(),
        }
    return {
        "external_product_id": external_product_id,
        "product_name_snapshot": str(fallback_name or "").strip(),
        "product_match_status": "manual" if external_product_id else "pending",
        "product_match_source": "manual" if external_product_id else "",
        "product_matched_at": None,
    }


@transaction.atomic
def create_outreach_task(*, user, validated_data):
    data = dict(validated_data)
    # task_no is server-owned even for direct service callers that bypass the serializer.
    data.pop("task_no", None)
    owner_value = data.get("owner")
    if owner_value is None:
        raise ValidationError({"owner": "Owner is required."})
    owner = _tenant_user(user, _pk(owner_value), for_update=False)
    store = _tenant_store(user, _pk(data["store"]), for_update=False)
    if store.status != "active":
        raise ValidationError({"store": "Only active stores can be assigned to outreach tasks."})
    _assert_active_bd_owner(user, owner)
    influencer = None
    if "influencer" in data and data["influencer"] is not None:
        influencer = _tenant_influencer(
            user,
            _pk(data["influencer"]),
            for_update=False,
        )
        influencer = _assert_influencer_not_blacklisted(
            user=user,
            influencer=influencer,
            message="Blacklisted influencers cannot be linked to outreach tasks.",
            code="conflict",
        )
        store = _locked_store(user, store.pk)
        owner = _locked_user(user, owner.pk)
    else:
        store = _locked_store(user, store.pk)
        owner = _locked_user(user, owner.pk)
    if store.status != "active":
        raise ValidationError({"store": "Only active stores can be assigned to outreach tasks."})
    _assert_active_bd_owner(user, owner)
    spu = _locked_spu(user, _pk(data["spu"])) if data.get("spu") is not None else None
    data["owner"] = owner
    data["store"] = store
    data["influencer"] = influencer
    data["spu"] = spu
    data["dispatcher"] = user
    data["external_id"] = data.get("external_id") or None
    data["external_product_id"] = str(data.get("external_product_id") or "").strip()
    data["sku_prefix"] = str(data.get("sku_prefix") or "").strip()
    data.update(
        _product_snapshot_fields(
            tenant=user.tenant,
            store=store,
            external_product_id=data["external_product_id"],
            fallback_name=data.get("product_name_snapshot") or data.get("task_name"),
        )
    )
    data["dispatch_time"] = timezone.now()
    for _ in range(OUTREACH_TASK_NO_MAX_ATTEMPTS):
        task_no = _generate_outreach_task_no(user.tenant)
        if OutreachTask.objects.filter(tenant=user.tenant, task_no=task_no).exists():
            continue
        task = OutreachTask(tenant=user.tenant, task_no=task_no, **data)
        try:
            # Keep a collision retry inside a savepoint so the outer transaction remains usable.
            with transaction.atomic():
                _save(task)
        except ValidationError:
            if OutreachTask.objects.filter(tenant=user.tenant, task_no=task_no).exists():
                continue
            raise
        except IntegrityError as exc:
            message = str(exc).lower()
            if "task_no" not in message and "uniq_outreach_task_no" not in message:
                raise
            continue
        break
    else:
        raise ValidationError(
            {"task_no": "Unable to allocate a unique outreach task number."},
            code="conflict",
        )
    if influencer is not None:
        add_outreach_target(user=user, task=task, influencer=influencer)
    _audit(
        user,
        "outreach_create",
        "outreach_task",
        task,
        after={
            "task_no": task.task_no,
            "status": task.status,
            "dispatcher_id": user.pk,
            "dispatch_time": task.dispatch_time.isoformat(),
        },
    )
    return task


@transaction.atomic
def update_outreach_task(*, user, task, validated_data, expected_version):
    """Safely edit mutable task facts without touching workflow state timestamps."""
    task = _locked_task(user, _pk(task))
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot be updated."})
    if task.status in TERMINAL_OUTREACH_TASK_STATUSES:
        raise ValidationError(
            {"outreach_task": "Completed or cancelled outreach tasks cannot be updated."},
            code="conflict",
        )
    if task.version != expected_version:
        raise ValidationError(
            {"version": "Task was changed by another request."},
            code="conflict",
        )

    data = dict(validated_data)
    if not data:
        raise ValidationError({"detail": "At least one editable task field is required."})

    changes = {}
    if "task_name" in data:
        changes["task_name"] = str(data["task_name"] or "").strip()
    if "priority" in data:
        changes["priority"] = data["priority"]
    if "sku_prefix" in data:
        changes["sku_prefix"] = str(data["sku_prefix"] or "").strip()

    store = task.store
    if "store" in data:
        store = _locked_store(user, _pk(data["store"]))
        if store.status != "active":
            raise ValidationError({"store": "Only active stores can be assigned to outreach tasks."})
        changes["store"] = store

    if "owner" in data:
        owner = _locked_user(user, _pk(data["owner"]))
        _assert_active_bd_owner(user, owner)
        changes["owner"] = owner

    if "target_count" in data:
        target_count = int(data["target_count"])
        linked_count = len(_logical_outreach_target_results(user=user, task=task))
        if target_count < linked_count:
            raise ValidationError(
                {"target_count": "Target count cannot be lower than the linked influencer count."}
            )
        changes["target_count"] = target_count

    product_changed = "store" in data or "external_product_id" in data
    if product_changed:
        external_product_id = (
            str(data["external_product_id"] or "").strip()
            if "external_product_id" in data
            else task.external_product_id
        )
        changes.update(
            _product_snapshot_fields(
                tenant=user.tenant,
                store=store,
                external_product_id=external_product_id,
                fallback_name=changes.get("task_name", task.task_name),
            )
        )

    before = {
        "task_name": task.task_name,
        "priority": task.priority,
        "store": task.store_id,
        "external_product_id": task.external_product_id,
        "sku_prefix": task.sku_prefix,
        "target_count": task.target_count,
        "owner": task.owner_id,
        "version": task.version,
    }
    after = {
        "task_name": changes.get("task_name", task.task_name),
        "priority": changes.get("priority", task.priority),
        "store": _pk(changes.get("store", task.store_id)),
        "external_product_id": changes.get("external_product_id", task.external_product_id),
        "sku_prefix": changes.get("sku_prefix", task.sku_prefix),
        "target_count": changes.get("target_count", task.target_count),
        "owner": _pk(changes.get("owner", task.owner_id)),
        "version": task.version + 1,
    }
    now = timezone.now()
    changes.update(version=task.version + 1, updated_at=now)
    updated = QuerySet.update(
        OutreachTask.objects.filter(
            pk=task.pk,
            tenant=user.tenant,
            is_deleted=False,
            version=expected_version,
        ),
        **changes,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Task was changed by another request."},
            code="conflict",
        )
    task.refresh_from_db()
    _audit(
        user,
        "outreach_update",
        "outreach_task",
        task,
        before=before,
        after=after,
    )
    return task


@transaction.atomic
def add_outreach_target(
    *, user, task, influencer, notes="", first_linked_at=None, expected_version=None
):
    influencer = _tenant_influencer(user, _pk(influencer), for_update=False)
    influencer, identity_ids = _assert_influencer_not_blacklisted(
        user=user,
        influencer=influencer,
        message="Blacklisted influencers cannot be linked to outreach tasks.",
        code="conflict",
        return_identity_ids=True,
    )
    task = _locked_task(user, _pk(task))
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive targets."})
    _assert_task_accepts_target(task)
    now = timezone.now()
    target = (
        OutreachTarget.objects.select_for_update()
        .filter(
            tenant=user.tenant,
            task=task,
            influencer_id__in=identity_ids,
        )
        .order_by("is_deleted", "id")
        .first()
    )
    created = target is None
    if (
        (target is None or target.is_deleted)
        and task.target_count
        and len(_logical_outreach_target_results(user=user, task=task)) >= task.target_count
    ):
        raise ValidationError({"target_count": "The outreach task has reached its target count."})
    if target is None:
        target = OutreachTarget(
            tenant=user.tenant,
            task=task,
            influencer=influencer,
            first_linked_at=first_linked_at or now,
            notes=notes or "",
        )
        _save(target)
    elif target.is_deleted:
        if expected_version is None or target.version != expected_version:
            raise ValidationError(
                {"version": "The deleted outreach target version is required for restore."},
                code="conflict",
            )
        updated = QuerySet.update(
            OutreachTarget.objects.filter(
                pk=target.pk,
                tenant=user.tenant,
                version=expected_version,
            ),
            is_deleted=False,
            deleted_at=None,
            version=target.version + 1,
            notes=notes if notes is not None else target.notes,
            updated_at=now,
        )
        if updated != 1:
            raise ValidationError(
                {"version": "Outreach target was changed by another request."},
                code="conflict",
            )
        target.refresh_from_db()
    if task.outreach_at is None:
        QuerySet.update(
            OutreachTask.objects.filter(pk=task.pk, tenant=user.tenant),
            outreach_at=now,
            updated_at=now,
        )
        task.refresh_from_db()
    _audit(
        user,
        "outreach_target_add" if created else "outreach_target_restore",
        "outreach_target",
        target,
        after={"task_id": task.pk, "influencer_id": target.influencer_id, "is_deleted": target.is_deleted},
    )
    return target, created


@transaction.atomic
def update_outreach_target(
    *, user, task, target, expected_version, outreach_result=None, notes=None
):
    task = _locked_task(user, _pk(task))
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot be updated."})
    _assert_task_accepts_target(task)
    target = _locked_target(user, _pk(target))
    if target.task_id != task.pk:
        raise ValidationError({"outreach_target": "Target must belong to the outreach task."})
    if target.is_deleted:
        raise ValidationError({"outreach_target": "Deleted outreach targets cannot be updated."})
    if target.version != expected_version:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    changes = {"version": target.version + 1, "updated_at": timezone.now()}
    before = {"outreach_result": target.outreach_result, "notes": target.notes}
    if outreach_result is not None:
        if outreach_result not in OutreachTarget.OutreachResult.values:
            raise ValidationError({"outreach_result": "Unsupported outreach result."})
        if (
            outreach_result != target.outreach_result
            and outreach_result not in OUTREACH_RESULT_TRANSITIONS[target.outreach_result]
        ):
            raise ValidationError(
                {"outreach_result": "This outreach result transition is not allowed."}
            )
        changes["outreach_result"] = outreach_result
    if notes is not None:
        changes["notes"] = notes
    updated = QuerySet.update(
        OutreachTarget.objects.filter(
            pk=target.pk,
            tenant=user.tenant,
            version=expected_version,
        ),
        **changes,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    target.refresh_from_db()
    _maybe_auto_complete_outreach_task(user, task)
    _audit(
        user,
        "outreach_target_update",
        "outreach_target",
        target,
        before=before,
        after={"outreach_result": target.outreach_result, "notes": target.notes},
    )
    return target


def _maybe_auto_complete_outreach_task(user, task):
    if task.status not in {OutreachTask.Status.PENDING, OutreachTask.Status.IN_PROGRESS}:
        return task
    if task.target_count <= 0:
        return task
    logical_results = _logical_outreach_target_results(user=user, task=task)
    if not logical_results or OutreachTarget.OutreachResult.PENDING in logical_results.values():
        return task
    if len(logical_results) < task.target_count:
        return task
    now = timezone.now()
    changes = {
        "status": OutreachTask.Status.COMPLETED,
        "version": task.version + 1,
        "finalized_at": now,
        "outreach_at": task.outreach_at or now,
        "updated_at": now,
    }
    if task.started_at is None:
        changes["started_at"] = now
    updated = QuerySet.update(
        OutreachTask.objects.filter(
            pk=task.pk,
            tenant=user.tenant,
            status=task.status,
            version=task.version,
        ),
        **changes,
    )
    if updated:
        task.refresh_from_db()
        _audit(
            user,
            "outreach_auto_complete",
            "outreach_task",
            task,
            after={"status": task.status, "version": task.version},
        )
    return task


@transaction.atomic
def soft_delete_outreach_target(*, user, task, target, expected_version):
    task = _locked_task(user, _pk(task))
    _assert_task_accepts_target(task)
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot be changed."})
    target = _locked_target(user, _pk(target))
    if target.task_id != task.pk:
        raise ValidationError({"outreach_target": "Target must belong to the outreach task."})
    if target.is_deleted:
        return target
    if target.version != expected_version:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    now = timezone.now()
    updated = QuerySet.update(
        OutreachTarget.objects.filter(
            pk=target.pk,
            tenant=user.tenant,
            version=expected_version,
        ),
        is_deleted=True,
        deleted_at=now,
        version=target.version + 1,
        updated_at=now,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    target.refresh_from_db()
    _audit(user, "outreach_target_delete", "outreach_target", target, after={"is_deleted": True})
    return target


@transaction.atomic
def soft_delete_outreach_task(*, user, task, expected_version):
    if expected_version is None:
        raise ValidationError({"version": "Expected task version is required."})
    task = _locked_task(user, _pk(task))
    now = timezone.now()
    updated = QuerySet.update(
        OutreachTask.objects.filter(
            pk=task.pk,
            tenant=user.tenant,
            is_deleted=False,
            version=expected_version,
        ),
        is_deleted=True,
        deleted_at=now,
        version=expected_version + 1,
        updated_at=now,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Outreach task was changed by another request."},
            code="conflict",
        )
    task.refresh_from_db()
    _audit(user, "outreach_delete", "outreach_task", task, after={"is_deleted": True})
    return task


@transaction.atomic
def restore_outreach_task(*, user, task, expected_version):
    task = _locked_task(user, _pk(task))
    if not task.is_deleted:
        if task.version != expected_version:
            raise ValidationError(
                {"version": "Task was changed by another request."}, code="conflict"
            )
        return task
    now = timezone.now()
    updated = QuerySet.update(
        OutreachTask.objects.filter(
            pk=task.pk,
            tenant=user.tenant,
            is_deleted=True,
            version=expected_version,
        ),
        is_deleted=False,
        deleted_at=None,
        version=expected_version + 1,
        updated_at=now,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Task was changed by another request."}, code="conflict"
        )
    task.refresh_from_db()
    _audit(
        user,
        "outreach_restore",
        "outreach_task",
        task,
        after={"is_deleted": False, "version": task.version},
    )
    recompute_outreach_task_completion(user=user, task=task)
    return task


def _logical_outreach_target_results(*, user, task):
    """Collapse active target rows to one deterministic result per creator identity."""
    logical_results = {}
    rows = OutreachTarget.objects.filter(
        tenant=user.tenant,
        task=task,
        is_deleted=False,
    ).order_by("id").values_list(
        "influencer_id",
        "influencer__platform",
        "influencer__handle",
        "outreach_result",
    )
    for influencer_id, platform, handle, result in rows:
        key = influencer_identity_key(
            influencer_id=influencer_id,
            platform=platform,
            handle=handle,
        )
        current = logical_results.get(key)
        if current is None or (
            current == OutreachTarget.OutreachResult.PENDING
            and result != OutreachTarget.OutreachResult.PENDING
        ):
            logical_results[key] = result
    return logical_results


def outreach_task_progress(*, user, task):
    task = OutreachTask.objects.filter(
        pk=_pk(task), tenant=user.tenant, is_deleted=False
    ).first()
    if task is None:
        raise ValidationError({"outreach_task": "Outreach task does not exist in the current tenant."})
    result_counts = {result: 0 for result in OutreachTarget.OutreachResult.values}
    for result in _logical_outreach_target_results(user=user, task=task).values():
        result_counts[result] = result_counts.get(result, 0) + 1
    linked_count = sum(result_counts.values())
    terminal_count = linked_count - result_counts.get(OutreachTarget.OutreachResult.PENDING, 0)
    return {
        "task_id": task.pk,
        "target_count": task.target_count,
        "linked_count": linked_count,
        "remaining_count": max(task.target_count - linked_count, 0),
        "terminal_count": terminal_count,
        "pending_count": result_counts.get(OutreachTarget.OutreachResult.PENDING, 0),
        "result_counts": result_counts,
        "status": task.status,
        "is_complete": task.status == OutreachTask.Status.COMPLETED,
    }


@transaction.atomic
def transition_outreach_task(*, user, task, status, expected_version):
    task = OutreachTask.objects.select_for_update().get(pk=task.pk, tenant=user.tenant)
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot transition."})
    if task.version != expected_version:
        raise ValidationError({"version": "Task was changed by another request."}, code="conflict")
    if status not in OutreachTask.Status.values:
        raise ValidationError({"status": "Unsupported task status."})
    allowed = {
        OutreachTask.Status.PENDING: {OutreachTask.Status.IN_PROGRESS, OutreachTask.Status.CANCELLED},
        OutreachTask.Status.IN_PROGRESS: {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED},
        OutreachTask.Status.COMPLETED: set(),
        OutreachTask.Status.CANCELLED: set(),
    }
    if status not in allowed[task.status]:
        raise ValidationError({"status": f"Transition from {task.status} to {status} is not allowed."})
    before = {"status": task.status, "version": task.version}
    now = timezone.now()
    changes = {"status": status, "version": task.version + 1, "updated_at": now}
    if status == OutreachTask.Status.IN_PROGRESS:
        changes["started_at"] = task.started_at or now
        changes["outreach_at"] = task.outreach_at or now
    if status in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}:
        changes["finalized_at"] = now
    _cas_state_update(
        task,
        tenant=user.tenant,
        expected_status=before["status"],
        expected_version=before["version"],
        **changes,
    )
    _audit(
        user,
        "outreach_status",
        "outreach_task",
        task,
        before=before,
        after={"status": task.status, "version": task.version},
    )
    return task


def published_video_results_queryset(fulfillment):
    return VideoResult.objects.filter(
        tenant=fulfillment.tenant,
        sample_fulfillment=fulfillment,
        published_at__isnull=False,
    )


@transaction.atomic
def recompute_outreach_task_completion(*, user, task):
    """Complete an active task once its effective, non-deleted samples reach the target."""
    _lock_tenant(user)
    task = _locked_task(user, _pk(task))
    if task.is_deleted or task.status not in {
        OutreachTask.Status.PENDING,
        OutreachTask.Status.IN_PROGRESS,
    }:
        return task
    sample_count = SampleFulfillment.objects.filter(
        tenant=user.tenant,
        outreach_task=task,
        is_deleted=False,
    ).count()
    if task.target_count <= 0 or sample_count < task.target_count:
        return task

    now = timezone.now()
    changes = {
        "status": OutreachTask.Status.COMPLETED,
        "version": task.version + 1,
        "finalized_at": now,
        "outreach_at": task.outreach_at or now,
        "updated_at": now,
    }
    if task.started_at is None:
        changes["started_at"] = now
    updated = QuerySet.update(
        OutreachTask.objects.filter(
            pk=task.pk,
            tenant=user.tenant,
            is_deleted=False,
            status=task.status,
            version=task.version,
        ),
        **changes,
    )
    if updated:
        task.refresh_from_db()
        _audit(
            user,
            "outreach_sample_auto_complete",
            "outreach_task",
            task,
            after={
                "status": task.status,
                "version": task.version,
                "sample_count": sample_count,
                "target_count": task.target_count,
            },
        )
    return task


def _assert_influencer_not_blacklisted(
    *,
    user,
    influencer,
    message=None,
    code=None,
    return_identity_ids=False,
):
    # Serialize restriction changes with sample/target creation and re-read the
    # active restrictions while holding every identity lock in primary-key
    # order. Do not lock the selected row first: two duplicate profiles could
    # otherwise acquire the same group in opposite order and deadlock.
    locked, identity_ids = _lock_influencer_identity(user=user, influencer=influencer)
    blacklisted = InfluencerRestriction.objects.filter(
        tenant_id=user.tenant_id,
        influencer_id__in=identity_ids,
        is_blacklisted=True,
    ).exists()
    if blacklisted:
        detail = {"influencer": message or "Blacklisted influencers cannot receive samples."}
        if code:
            raise ValidationError(detail, code=code)
        raise ValidationError(detail)
    return (locked, identity_ids) if return_identity_ids else locked


def _read_sample_fulfillment(*, user, fulfillment, is_deleted):
    return SampleFulfillment.objects.get(
        pk=_pk(fulfillment),
        tenant=user.tenant,
        is_deleted=is_deleted,
    )


def _locked_sample_fulfillment(*, user, fulfillment):
    return SampleFulfillment.objects.select_for_update().get(
        pk=_pk(fulfillment),
        tenant=user.tenant,
    )


def _revalidate_sample_fulfillment(
    *,
    fulfillment,
    observed,
    locked_influencer,
    expected_version,
    expected_deleted,
):
    if fulfillment.version != expected_version:
        raise ValidationError(
            {"version": "Fulfillment was changed by another request."},
            code="conflict",
        )
    if fulfillment.is_deleted != expected_deleted:
        raise ValidationError(
            {"is_deleted": "Fulfillment was changed by another request."},
            code="conflict",
        )
    if fulfillment.status != observed.status:
        raise ValidationError(
            {"status": "Fulfillment was changed by another request."},
            code="conflict",
        )
    if (
        fulfillment.influencer_id != observed.influencer_id
        or fulfillment.influencer_id != locked_influencer.pk
    ):
        raise ValidationError(
            {"influencer": "Fulfillment influencer was changed by another request."},
            code="conflict",
        )


def _recompute_related_task(*, user, fulfillment):
    if fulfillment.outreach_task_id:
        recompute_outreach_task_completion(user=user, task=fulfillment.outreach_task_id)


@transaction.atomic
def create_sample_fulfillment(*, user, request_key, validated_data, item_payloads):
    if not request_key or len(request_key) > 128:
        raise ValidationError({"idempotency_key": "Idempotency-Key must be 1-128 characters."})
    data = dict(validated_data)
    item_payloads = _normalize_item_payloads(item_payloads)
    request_hash = _payload_hash({"fulfillment": data, "items": item_payloads})
    existing = SampleFulfillment.objects.select_for_update().filter(
        tenant=user.tenant, request_key=request_key
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise ValidationError(
                {"idempotency_key": "Key was already used with a different payload."},
                code="conflict",
            )
        return existing, False

    if "influencer" in data and data["influencer"] is None:
        raise ValidationError({"influencer": "Influencer is required."})
    if "owner" in data and data["owner"] is None:
        raise ValidationError({"owner": "Owner is required."})

    task = data.get("outreach_task")
    if task is not None:
        # BD samples are created only from an outreach task and always carry its context.
        data["link_type"] = "DRJL"
        task, target, influencer, store, owner = _lock_task_relations(
            user,
            task_id=_pk(task),
            target_id=_pk(data["outreach_target"]) if data.get("outreach_target") is not None else None,
            influencer_id=data.get("influencer"),
            store_id=data.get("store"),
            owner_id=data.get("owner"),
            external_product_id=data.get("external_product_id"),
        )
        product_id, product_name = _product_snapshot(user, task, store)
    else:
        target = None
        if data.get("link_type") in (None, "", "DRJL"):
            raise ValidationError(
                {"link_type": "BD outreach samples must be created from an outreach task."}
            )
        if data.get("outreach_target") is not None:
            raise ValidationError({"outreach_target": "A standalone sample cannot use an outreach target."})
        if data.get("influencer") is None:
            raise ValidationError({"influencer": "Influencer is required."})
        if data.get("store") is None:
            raise ValidationError({"store": "Store is required for standalone samples."})
        # The complete normalized-handle identity group is locked below in a
        # stable primary-key order. Locking this selected row first can invert
        # the blacklist operation's lock order for duplicate profiles.
        influencer = _tenant_influencer(
            user,
            _pk(data["influencer"]),
            for_update=False,
        )
        influencer = _assert_influencer_not_blacklisted(user=user, influencer=influencer)
        identity_locked = True
        store = _locked_store(user, _pk(data["store"]))
        owner = _locked_user(user, _pk(data.get("owner") or user.pk))
        product_id = str(data.get("external_product_id") or "").strip()
        if not product_id:
            raise ValidationError(
                {"external_product_id": "Standalone samples require an external product ID."}
            )
        product_name = str(data.get("product_name_snapshot") or "").strip()

    fulfillment_data = dict(data)
    has_sample_order = bool(str(data.get("sample_order_no") or "").strip())
    initial_status = SampleFulfillment.Status.PENDING
    sample_sent_at = timezone.now()
    initial_shipped_at = timezone.now() if has_sample_order else None
    deadline_base = initial_shipped_at or sample_sent_at
    fulfillment_data.update(
        {
            "outreach_task": task,
            "outreach_target": target,
            "influencer": influencer,
            "store": store,
            "owner": owner,
            "product_name_snapshot": product_name,
            "external_product_id": product_id,
            "request_key": request_key,
            "request_hash": request_hash,
            "fulfillment_no": str(data.get("fulfillment_no") or "").strip()
            or _generate_sample_fulfillment_no(user.tenant, data.get("link_type") or "DRJL"),
            "status": initial_status,
            "sample_sent_at": sample_sent_at,
            "shipped_at": None,
            "video_deadline_at": deadline_base + timedelta(days=20),
            "quick_tags": _normalize_quick_tags(data.get("quick_tags", [])),
            "is_deleted": False,
            "deleted_at": None,
            "deleted_by": None,
        }
    )
    fulfillment_data.pop("items", None)
    fulfillment_data.pop("product_name_snapshot", None)
    fulfillment_data["product_name_snapshot"] = product_name
    fulfillment_data.pop("request_key", None)
    fulfillment_data["request_key"] = request_key
    fulfillment_data.pop("request_hash", None)
    fulfillment_data["request_hash"] = request_hash

    fulfillment = SampleFulfillment(tenant=user.tenant, **fulfillment_data)
    try:
        with transaction.atomic():
            _save(fulfillment)
    except IntegrityError as exc:
        existing = SampleFulfillment.objects.select_for_update().filter(
            tenant=user.tenant, request_key=request_key
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValidationError(
                    {"idempotency_key": "Key was already used with a different payload."},
                    code="conflict",
                ) from exc
            return existing, False
        competing_number = SampleFulfillment.objects.select_for_update().filter(
            tenant=user.tenant, fulfillment_no=fulfillment.fulfillment_no
        ).first()
        if competing_number is not None:
            raise ValidationError(
                {"fulfillment_no": "Fulfillment number already exists."}, code="conflict"
            ) from exc
        raise

    fulfillment = _recalculate_sample_pricing(
        user=user,
        fulfillment=fulfillment,
        item_payloads=item_payloads,
    )
    create_sample_attribution_snapshot(
        tenant=user.tenant,
        fulfillment=fulfillment,
        owner=owner,
        influencer=influencer,
        store=store,
    )
    FulfillmentStatusEvent.objects.create(
        tenant=user.tenant,
        fulfillment=fulfillment,
        from_status="",
        to_status=SampleFulfillment.Status.PENDING,
        actor=user,
        reason="created",
    )
    if has_sample_order:
        before_version = fulfillment.version
        _cas_state_update(
            fulfillment,
            tenant=user.tenant,
            expected_status=SampleFulfillment.Status.PENDING,
            expected_version=before_version,
            status=SampleFulfillment.Status.SHIPPED,
            shipped_at=initial_shipped_at,
            version=before_version + 1,
            updated_at=timezone.now(),
        )
        fulfillment.refresh_from_db()
        FulfillmentStatusEvent.objects.create(
            tenant=user.tenant,
            fulfillment=fulfillment,
            from_status=SampleFulfillment.Status.PENDING,
            to_status=SampleFulfillment.Status.SHIPPED,
            actor=user,
            reason="sample_order_no_added",
        )
    _audit(
        user,
        "sample_create",
        "sample_fulfillment",
        fulfillment,
        after={
            "fulfillment_no": fulfillment.fulfillment_no,
            "status": fulfillment.status,
            "outreach_target_id": target.pk if target is not None else None,
        },
    )
    if task is not None:
        recompute_outreach_task_completion(user=user, task=task)
    return fulfillment, True


@transaction.atomic
def transition_sample_fulfillment(
    *, user, fulfillment, status, expected_version, reason="", confirm_terminal=False
):
    fulfillment = SampleFulfillment.objects.select_for_update().get(
        pk=fulfillment.pk, tenant=user.tenant, is_deleted=False
    )
    if fulfillment.version != expected_version:
        raise ValidationError(
            {"version": "Fulfillment was changed by another request."}, code="conflict"
        )
    # ``processing`` is a legacy state retained as a service compatibility
    # value (see models.py).  It is intentionally not part of the current
    # model choices, but old callers may still need the audited transition.
    supported_statuses = set(SampleFulfillment.Status.values)
    supported_statuses.add(SampleFulfillment.Status.PROCESSING)
    if status not in supported_statuses:
        raise ValidationError({"status": "Unsupported fulfillment status."})
    if (
        status in SAMPLE_TERMINAL_STATUSES
        and status != fulfillment.status
        and not confirm_terminal
    ):
        raise ValidationError(
            {"confirmation": "Explicit confirmation is required for terminal status changes."},
            code="confirmation_required",
        )
    allowed = {
        SampleFulfillment.Status.PENDING: {
            SampleFulfillment.Status.PROCESSING,
            SampleFulfillment.Status.SHIPPED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.PROCESSING: {
            SampleFulfillment.Status.SHIPPED,
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.SHIPPED: {
            SampleFulfillment.Status.DELIVERED,
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.DELIVERED: {
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.PUBLISHED: {
            SampleFulfillment.Status.LIVE_CREATOR,
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.LIVE_CREATOR: {
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.OVERDUE: {
            SampleFulfillment.Status.PUBLISHED,
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.COMPLETED: set(),
        SampleFulfillment.Status.CANCELLED: set(),
        SampleFulfillment.Status.BLACKLISTED: set(),
    }
    if status not in allowed[fulfillment.status]:
        raise ValidationError(
            {"status": f"Transition from {fulfillment.status} to {status} is not allowed."}
        )
    before_status = fulfillment.status
    now = timezone.now()
    changes = {
        "status": status,
        "version": fulfillment.version + 1,
        "updated_at": now,
    }
    if status == SampleFulfillment.Status.SHIPPED and fulfillment.shipped_at is None:
        changes["shipped_at"] = now
        if fulfillment.video_deadline_at is None:
            changes["video_deadline_at"] = now + timedelta(days=20)
    if status in SAMPLE_TERMINAL_STATUSES:
        changes["finalized_at"] = now
    _cas_state_update(
        fulfillment,
        tenant=user.tenant,
        expected_status=before_status,
        expected_version=expected_version,
        **changes,
    )
    FulfillmentStatusEvent.objects.create(
        tenant=user.tenant,
        fulfillment=fulfillment,
        from_status=before_status,
        to_status=status,
        actor=user,
        reason=reason,
    )
    _audit(
        user,
        "sample_status",
        "sample_fulfillment",
        fulfillment,
        before={"status": before_status},
        after={"status": status, "version": fulfillment.version},
    )
    _recompute_related_task(user=user, fulfillment=fulfillment)
    return fulfillment


@transaction.atomic
def update_sample_fulfillment(
    *,
    user,
    fulfillment,
    expected_version,
    validated_data,
    item_payloads=None,
    append_item_payloads=None,
    items_mode="replace",
):
    """Edit sample facts and atomically rebuild any requested SKU snapshots."""
    observed = _read_sample_fulfillment(
        user=user,
        fulfillment=fulfillment,
        is_deleted=False,
    )
    unlocked_influencer = _tenant_influencer(
        user,
        observed.influencer_id,
        for_update=False,
    )
    locked_influencer = _assert_influencer_not_blacklisted(
        user=user,
        influencer=unlocked_influencer,
    )
    fulfillment = _locked_sample_fulfillment(user=user, fulfillment=observed)
    _revalidate_sample_fulfillment(
        fulfillment=fulfillment,
        observed=observed,
        locked_influencer=locked_influencer,
        expected_version=expected_version,
        expected_deleted=False,
    )

    data = dict(validated_data or {})
    if item_payloads is not None and append_item_payloads is not None:
        raise ValidationError({"items": "Use either replacement items or append_items, not both."})
    if items_mode not in {"replace", "append"}:
        raise ValidationError({"items_mode": "Items mode must be replace or append."})
    if append_item_payloads is not None:
        items_mode = "append"
        item_payloads = append_item_payloads
    has_item_change = item_payloads is not None
    if not data and not has_item_change:
        raise ValidationError({"detail": "At least one editable fulfillment field is required."})

    changes = {}
    for field_name in ("sample_order_no", "notes"):
        if field_name in data:
            changes[field_name] = str(data[field_name] or "").strip()
    if "link_type" in data:
        if data["link_type"] not in dict(SampleFulfillment.LINK_TYPE_CHOICES):
            raise ValidationError({"link_type": "Unsupported link type."})
        changes["link_type"] = data["link_type"]
    if "quick_tags" in data:
        changes["quick_tags"] = _normalize_quick_tags(data["quick_tags"])

    before = {
        "sample_order_no": fulfillment.sample_order_no,
        "notes": fulfillment.notes,
        "link_type": fulfillment.link_type,
        "quick_tags": fulfillment.quick_tags,
        "version": fulfillment.version,
        "sku_quantity": fulfillment.sku_quantity,
        "calculated_cost": str(fulfillment.calculated_cost) if fulfillment.calculated_cost is not None else None,
    }
    now = timezone.now()
    auto_ship = (
        fulfillment.status == SampleFulfillment.Status.PENDING
        and bool(str(changes.get("sample_order_no", fulfillment.sample_order_no) or "").strip())
    )
    before_status = fulfillment.status
    if auto_ship:
        changes.update(
            status=SampleFulfillment.Status.SHIPPED,
            shipped_at=fulfillment.shipped_at or now,
            video_deadline_at=fulfillment.video_deadline_at or now + timedelta(days=20),
        )
    changes.update(version=fulfillment.version + 1, updated_at=now)
    updated = QuerySet.update(
        SampleFulfillment.objects.filter(
            pk=fulfillment.pk,
            tenant=user.tenant,
            is_deleted=False,
            version=expected_version,
        ),
        **changes,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Fulfillment was changed by another request."},
            code="conflict",
        )
    fulfillment.refresh_from_db()
    if auto_ship:
        FulfillmentStatusEvent.objects.create(
            tenant=user.tenant,
            fulfillment=fulfillment,
            from_status=before_status,
            to_status=SampleFulfillment.Status.SHIPPED,
            actor=user,
            reason="sample_order_no_added",
        )

    if has_item_change:
        payloads = list(item_payloads or [])
        if items_mode == "append":
            existing_payloads = list(
                fulfillment.items.order_by("id").all()
            )
            payloads = [_sample_item_payload(item) for item in existing_payloads] + payloads
        fulfillment = _recalculate_sample_pricing(
            user=user,
            fulfillment=fulfillment,
            item_payloads=payloads,
        )
    else:
        fulfillment.refresh_from_db()

    _audit(
        user,
        "sample_update",
        "sample_fulfillment",
        fulfillment,
        before=before,
        after={
            "sample_order_no": fulfillment.sample_order_no,
            "notes": fulfillment.notes,
            "link_type": fulfillment.link_type,
            "quick_tags": fulfillment.quick_tags,
            "version": fulfillment.version,
            "sku_quantity": fulfillment.sku_quantity,
            "calculated_cost": str(fulfillment.calculated_cost) if fulfillment.calculated_cost is not None else None,
        },
    )
    _recompute_related_task(user=user, fulfillment=fulfillment)
    return fulfillment


@transaction.atomic
def soft_delete_sample_fulfillment(*, user, fulfillment, expected_version):
    fulfillment = SampleFulfillment.objects.select_for_update().get(
        pk=_pk(fulfillment), tenant=user.tenant, is_deleted=False
    )
    if fulfillment.version != expected_version:
        raise ValidationError(
            {"version": "Fulfillment was changed by another request."},
            code="conflict",
        )
    now = timezone.now()
    updated = QuerySet.update(
        SampleFulfillment.objects.filter(
            pk=fulfillment.pk,
            tenant=user.tenant,
            is_deleted=False,
            version=expected_version,
        ),
        is_deleted=True,
        deleted_at=now,
        deleted_by=user,
        version=expected_version + 1,
        updated_at=now,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Fulfillment was changed by another request."},
            code="conflict",
        )
    fulfillment.refresh_from_db()
    _audit(
        user,
        "sample_delete",
        "sample_fulfillment",
        fulfillment,
        after={"is_deleted": True, "version": fulfillment.version},
    )
    _recompute_related_task(user=user, fulfillment=fulfillment)
    return fulfillment


@transaction.atomic
def restore_sample_fulfillment(*, user, fulfillment, expected_version):
    observed = _read_sample_fulfillment(
        user=user,
        fulfillment=fulfillment,
        is_deleted=True,
    )
    unlocked_influencer = _tenant_influencer(
        user,
        observed.influencer_id,
        for_update=False,
    )
    locked_influencer = _assert_influencer_not_blacklisted(
        user=user,
        influencer=unlocked_influencer,
    )
    fulfillment = _locked_sample_fulfillment(user=user, fulfillment=observed)
    _revalidate_sample_fulfillment(
        fulfillment=fulfillment,
        observed=observed,
        locked_influencer=locked_influencer,
        expected_version=expected_version,
        expected_deleted=True,
    )
    task = _locked_task(user, fulfillment.outreach_task_id) if fulfillment.outreach_task_id else None
    if task is not None and task.is_deleted:
        raise ValidationError(
            {"outreach_task": "Restore the deleted outreach task before restoring its sample."},
            code="conflict",
        )
    now = timezone.now()
    updated = QuerySet.update(
        SampleFulfillment.objects.filter(
            pk=fulfillment.pk,
            tenant=user.tenant,
            is_deleted=True,
            version=expected_version,
        ),
        is_deleted=False,
        deleted_at=None,
        deleted_by=None,
        version=expected_version + 1,
        updated_at=now,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Fulfillment was changed by another request."},
            code="conflict",
        )
    fulfillment.refresh_from_db()
    _audit(
        user,
        "sample_restore",
        "sample_fulfillment",
        fulfillment,
        after={"is_deleted": False, "version": fulfillment.version},
    )
    if task is not None:
        recompute_outreach_task_completion(user=user, task=task)
    return fulfillment


@transaction.atomic
def set_influencer_blacklist(*, user, influencer, blacklisted, reason=""):
    # Identity edits use this same tenant lock, so the canonical handle group
    # cannot change between reading the selected profile and locking its peers.
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    selected = Influencer.objects.get(pk=_pk(influencer), tenant=user.tenant)
    identity_profiles = list(
        influencer_identity_queryset(selected, for_update=True)
    )
    influencer = next((profile for profile in identity_profiles if profile.pk == selected.pk), None)
    if influencer is None:
        raise ValidationError({"influencer": "Influencer identity group is empty."})
    identity_ids = [profile.pk for profile in identity_profiles]
    action = (
        InfluencerRestrictEvent.Action.BLACKLIST
        if blacklisted
        else InfluencerRestrictEvent.Action.UNBLACKLIST
    )
    event_reason = reason or ("Manual blacklist" if blacklisted else "Manual unblacklist")
    restriction = None
    event = None
    for profile in identity_profiles:
        current_restriction, _ = InfluencerRestriction.objects.update_or_create(
            tenant=user.tenant,
            influencer=profile,
            defaults={
                "is_blacklisted": blacklisted,
                "reason": reason,
                "created_by": user,
            },
        )
        current_event = InfluencerRestrictEvent.objects.create(
            tenant=user.tenant,
            influencer=profile,
            action=action,
            reason=event_reason,
            actor=user,
        )
        if profile.pk == influencer.pk:
            restriction = current_restriction
            event = current_event

    if restriction is None or event is None:
        raise ValidationError({"influencer": "Influencer identity group is empty."})
    if blacklisted:
        affected_task_ids = set()
        rows = list(
            SampleFulfillment.objects.select_for_update().filter(
                tenant=user.tenant,
                influencer_id__in=identity_ids,
                is_deleted=False,
            ).exclude(
                status__in={
                    SampleFulfillment.Status.COMPLETED,
                    SampleFulfillment.Status.CANCELLED,
                    SampleFulfillment.Status.BLACKLISTED,
                }
            ).order_by("id")
        )
        now = timezone.now()
        for fulfillment in rows:
            before_status = fulfillment.status
            before_version = fulfillment.version
            _cas_state_update(
                fulfillment,
                tenant=user.tenant,
                expected_status=before_status,
                expected_version=before_version,
                status=SampleFulfillment.Status.BLACKLISTED,
                finalized_at=now,
                version=before_version + 1,
                updated_at=now,
            )
            FulfillmentStatusEvent.objects.create(
                tenant=user.tenant,
                fulfillment=fulfillment,
                from_status=before_status,
                to_status=SampleFulfillment.Status.BLACKLISTED,
                actor=user,
                reason=reason or "influencer_blacklisted",
            )
            _audit(
                user,
                "sample_blacklist",
                "sample_fulfillment",
                fulfillment,
                before={"status": before_status, "version": before_version},
                after={"status": fulfillment.status, "version": fulfillment.version},
            )
            if fulfillment.outreach_task_id:
                affected_task_ids.add(fulfillment.outreach_task_id)
        # Keep task recomputation in this transaction so blacklist propagation
        # and the derived task state commit or roll back together.  The tenant
        # lock is acquired first by both this path and recompute, which keeps
        # the child-row lock order deterministic for concurrent writers.
        for task_id in sorted(affected_task_ids):
            recompute_outreach_task_completion(user=user, task=task_id)
    return restriction, event


@transaction.atomic
def refresh_sample_fulfillment_video_status(*, user, fulfillment):
    """Promote an unfinished sample when a published video is linked."""
    fulfillment = SampleFulfillment.objects.select_for_update().get(
        pk=_pk(fulfillment), tenant=user.tenant
    )
    if (
        fulfillment.is_deleted
        or fulfillment.status not in SAMPLE_VIDEO_RECONCILE_STATUSES
        or not published_video_results_queryset(fulfillment).exists()
    ):
        return fulfillment
    now = timezone.now()
    expected_status = fulfillment.status
    expected_version = fulfillment.version
    _cas_state_update(
        fulfillment,
        tenant=user.tenant,
        expected_status=expected_status,
        expected_version=expected_version,
        status=SampleFulfillment.Status.PUBLISHED,
        version=expected_version + 1,
        updated_at=now,
    )
    FulfillmentStatusEvent.objects.create(
        tenant=user.tenant,
        fulfillment=fulfillment,
        from_status=expected_status,
        to_status=SampleFulfillment.Status.PUBLISHED,
        actor=user,
        reason="published_video_matched",
    )
    _audit(
        user,
        "sample_video_reconcile",
        "sample_fulfillment",
        fulfillment,
        before={"status": expected_status, "version": expected_version},
        after={"status": fulfillment.status, "version": fulfillment.version},
    )
    _recompute_related_task(user=user, fulfillment=fulfillment)
    return fulfillment


def mark_overdue_sample_fulfillments(*, actor, tenant=None, now=None, batch_size=100):
    """Idempotently mark expired, unmatched active samples as overdue."""
    if actor is None or getattr(actor, "tenant_id", None) is None:
        raise ValidationError({"actor": "An internal tenant actor is required."})
    if tenant is None:
        tenant = actor.tenant
    if tenant.pk != actor.tenant_id:
        raise ValidationError({"actor": "The actor must belong to the selected tenant."})
    now = now or timezone.now()
    if not isinstance(batch_size, int) or batch_size < 1 or batch_size > 500:
        raise ValidationError({"batch_size": "Batch size must be between 1 and 500."})
    marked = 0
    skipped_with_video = 0
    while True:
        published_video = VideoResult.objects.filter(
            tenant=tenant,
            sample_fulfillment_id=OuterRef("pk"),
            published_at__isnull=False,
        )
        candidates = list(
            SampleFulfillment.objects.filter(
                tenant=tenant,
                is_deleted=False,
                video_deadline_at__lt=now,
                status__in=SAMPLE_TIMEOUT_CANDIDATE_STATUSES,
            )
            .filter(Q(outreach_task__isnull=True) | Q(outreach_task__is_deleted=False))
            .annotate(has_published_video=Exists(published_video))
            .order_by("id")
            .values_list("id", "has_published_video")[:batch_size]
        )
        if not candidates:
            break

        matched_ids = [sample_id for sample_id, has_video in candidates if has_video]
        overdue_ids = [sample_id for sample_id, has_video in candidates if not has_video]
        for sample_id in matched_ids:
            refresh_sample_fulfillment_video_status(user=actor, fulfillment=sample_id)
            skipped_with_video += 1

        if overdue_ids:
            reconcile_after_lock = []
            with transaction.atomic():
                locked_rows = list(
                    SampleFulfillment.objects.select_for_update()
                    .filter(
                        tenant=tenant,
                        pk__in=overdue_ids,
                        is_deleted=False,
                        video_deadline_at__lt=now,
                        status__in=SAMPLE_TIMEOUT_CANDIDATE_STATUSES,
                    )
                    .filter(Q(outreach_task__isnull=True) | Q(outreach_task__is_deleted=False))
                    .order_by("id")
                )
                affected_task_ids = set()
                for fulfillment in locked_rows:
                    # A video can be linked after the initial candidate scan. Recheck while
                    # holding the fulfillment lock before committing an overdue transition.
                    if VideoResult.objects.filter(
                        tenant=tenant,
                        sample_fulfillment_id=fulfillment.pk,
                        published_at__isnull=False,
                    ).exists():
                        reconcile_after_lock.append(fulfillment.pk)
                        skipped_with_video += 1
                        continue
                    from_status = fulfillment.status
                    expected_version = fulfillment.version
                    updated = QuerySet.update(
                        SampleFulfillment.objects.filter(
                            pk=fulfillment.pk,
                            tenant=tenant,
                            is_deleted=False,
                            status=from_status,
                            version=expected_version,
                        ),
                        status=SampleFulfillment.Status.OVERDUE,
                        version=expected_version + 1,
                        updated_at=now,
                    )
                    if updated != 1:
                        continue
                    fulfillment.refresh_from_db()
                    FulfillmentStatusEvent.objects.create(
                        tenant=tenant,
                        fulfillment=fulfillment,
                        from_status=from_status,
                        to_status=SampleFulfillment.Status.OVERDUE,
                        actor=actor,
                        reason="video_deadline_expired",
                    )
                    _audit(
                        actor,
                        "sample_auto_overdue",
                        "sample_fulfillment",
                        fulfillment,
                        after={"status": fulfillment.status, "version": fulfillment.version},
                    )
                    if fulfillment.outreach_task_id:
                        affected_task_ids.add(fulfillment.outreach_task_id)
                    marked += 1
                for task_id in sorted(affected_task_ids):
                    recompute_outreach_task_completion(user=actor, task=task_id)
            for fulfillment_id in reconcile_after_lock:
                refresh_sample_fulfillment_video_status(
                    user=actor,
                    fulfillment=fulfillment_id,
                )
    return {"marked": marked, "skipped_with_video": skipped_with_video}
