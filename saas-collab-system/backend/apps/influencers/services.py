import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Exists, Model, OuterRef, Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
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
    ImportBatch,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    BdSampleAttributionSnapshot,
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

# This is intentionally a source-specific compatibility path for the
# controlled Feishu full export.  It is not a second generic status endpoint:
# callers must identify this source and provide a stable source event key.
FEISHU_FULL_SAMPLE_STATUS_SOURCE = FulfillmentStatusEvent.SOURCE_IMPORT
FEISHU_PERSONNEL_POLICY = "feishu_unmatched_to_liyejun_v1"
FEISHU_PERSONNEL_RESOLUTIONS = frozenset(
    {"exact_match", "unmatched_fallback", "blank_dispatcher_uses_owner"}
)
FEISHU_PERSONNEL_FALLBACK_USERNAME = "liyejun"
FEISHU_FULL_SAMPLE_STATUS_MAP = {
    "pending": SampleFulfillment.Status.PENDING,
    "待发样": SampleFulfillment.Status.PENDING,
    "shipped": SampleFulfillment.Status.SHIPPED,
    "已发货": SampleFulfillment.Status.SHIPPED,
    "published": SampleFulfillment.Status.PUBLISHED,
    "已发布": SampleFulfillment.Status.PUBLISHED,
}
FEISHU_FULL_TASK_STATUS_MAP = {
    "pending": OutreachTask.Status.PENDING,
    "待处理": OutreachTask.Status.PENDING,
    "in_progress": OutreachTask.Status.IN_PROGRESS,
    "in-progress": OutreachTask.Status.IN_PROGRESS,
    "进行中": OutreachTask.Status.IN_PROGRESS,
    "completed": OutreachTask.Status.COMPLETED,
    "已完成": OutreachTask.Status.COMPLETED,
    "cancelled": OutreachTask.Status.CANCELLED,
    "canceled": OutreachTask.Status.CANCELLED,
    "已取消": OutreachTask.Status.CANCELLED,
}
_FEISHU_TASK_STATUS_ORDER = {
    OutreachTask.Status.PENDING: 0,
    OutreachTask.Status.IN_PROGRESS: 1,
    OutreachTask.Status.COMPLETED: 2,
    OutreachTask.Status.CANCELLED: 2,
}
_FEISHU_IMPORT_STATUS_ORDER = {
    SampleFulfillment.Status.PENDING: 0,
    SampleFulfillment.Status.PROCESSING: 0,
    SampleFulfillment.Status.SHIPPED: 1,
    SampleFulfillment.Status.DELIVERED: 1,
    SampleFulfillment.Status.OVERDUE: 1,
    SampleFulfillment.Status.PUBLISHED: 2,
}
_FEISHU_IMPORT_PRESERVED_STATUSES = frozenset(
    {
        SampleFulfillment.Status.COMPLETED,
        SampleFulfillment.Status.CANCELLED,
        SampleFulfillment.Status.LIVE_CREATOR,
        SampleFulfillment.Status.BLACKLISTED,
    }
)
FEISHU_FULL_IMPORT_PRESERVES_TERMINAL_SAMPLE_STATUS = True


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


def _import_manifest_digest(*, source, task_external_ids, sample_external_ids):
    """Return the durable digest for one complete source reconciliation set."""

    return _payload_hash(
        {
            "source": str(source or "").strip(),
            "task_external_ids": sorted(str(value).strip() for value in task_external_ids),
            "sample_external_ids": sorted(str(value).strip() for value in sample_external_ids),
        }
    )


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
    source=None,
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

    if (
        owner_id is not None
        and _pk(owner_id) != task.owner_id
        and source != FEISHU_FULL_SAMPLE_STATUS_SOURCE
    ):
        raise ValidationError(
            {"owner": "Sample owner must match the outreach task owner for this source."},
            code="conflict",
        )

    # The outreach task owner is the relationship owner.  The controlled
    # Feishu snapshot may carry a different same-tenant executor; every other
    # source keeps the historical owner-match rule above.
    owner = _locked_user(user, _pk(owner_id) if owner_id is not None else task.owner_id)

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


def _source_decimal(value, *, field):
    """Normalize a source cost without consulting the current SKU catalog."""

    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (ArithmeticError, ValueError) as exc:
        raise ValidationError({field: "Source cost must be a finite decimal."}) from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValidationError({field: "Source cost must be non-negative."})
    return parsed


def _source_datetime(value, *, field):
    """Normalize an explicit source date without falling back to ``now``."""

    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        # Feishu exports timestamps as epoch milliseconds.  Accept seconds as
        # well for adapters/tests that already normalized the source value.
        try:
            numeric = float(value)
        except (ArithmeticError, ValueError, OverflowError) as exc:
            raise ValidationError({field: "Source date is not a valid timestamp."}) from exc
        if not math.isfinite(numeric):
            raise ValidationError({field: "Source date is not a valid timestamp."})
        if abs(numeric) >= 100_000_000_000:
            numeric /= 1000
        try:
            parsed = datetime.fromtimestamp(numeric, tz=datetime_timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValidationError({field: "Source date is not a valid timestamp."}) from exc
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, time):
        # A time without a source date is not an auditable timestamp.  The task
        # adapter combines ``start_time``/``dispatch_clock`` only after it has
        # parsed the corresponding source date.
        raise ValidationError({field: "Source time requires an explicit source date."})
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        text = str(value).strip()
        parsed = parse_datetime(text)
        if parsed is None:
            parsed_date = parse_date(text)
            if parsed_date is not None:
                parsed = datetime.combine(parsed_date, time.min)
    if parsed is None:
        raise ValidationError({field: "Source date is not a valid timestamp."})
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _source_item_signature(fulfillment):
    """Return stable source-item facts for idempotence/audit comparisons."""

    fields = (
        "sku_id",
        "external_product_id",
        "site_code",
        "requested_sku",
        "product_name",
        "quantity",
        "unit_price",
        "unit_cost",
        "cost_amount",
        "currency",
        "price_match_status",
        "normalized_sku",
        "matched_sku_code",
        "matched_legacy_sku_code",
        "sales_amount",
        "cost_match_status",
        "cost_source",
        "price_source",
        "cost_snapshot_at",
        "price_snapshot_at",
        "match_notes",
    )
    return tuple(
        tuple(_canonical_scalar(getattr(item, field)) for field in fields)
        for item in SampleItem.objects.filter(
            tenant_id=fulfillment.tenant_id,
            fulfillment_id=fulfillment.pk,
        ).order_by("id")
    )


def _apply_source_chronology(
    *,
    user,
    fulfillment,
    desired_status,
    sample_sent_at,
    shipped_at,
):
    """Write source dates atomically, without using execution time as a fact."""

    source_sample_sent_at = _source_datetime(sample_sent_at, field="sample_sent_at")
    if source_sample_sent_at is None:
        raise ValidationError({"sample_sent_at": "Source sample date is required."})
    supplied_shipped_at = _source_datetime(shipped_at, field="shipped_at")
    advanced_statuses = {
        SampleFulfillment.Status.SHIPPED,
        SampleFulfillment.Status.PUBLISHED,
    }
    if desired_status in advanced_statuses:
        source_shipped_at = supplied_shipped_at or fulfillment.shipped_at
    elif (
        fulfillment.status in advanced_statuses
        or fulfillment.status
        in {
            SampleFulfillment.Status.DELIVERED,
            SampleFulfillment.Status.OVERDUE,
        }
        or fulfillment.status in _FEISHU_IMPORT_PRESERVED_STATUSES
    ):
        # A stale pending snapshot must not erase a chronology that has already
        # been recorded by a later workflow state.
        source_shipped_at = fulfillment.shipped_at
    else:
        source_shipped_at = None
    deadline_base = source_shipped_at or source_sample_sent_at
    source_deadline = deadline_base + timedelta(days=20)
    desired = {
        "sample_sent_at": source_sample_sent_at,
        "shipped_at": source_shipped_at,
        "video_deadline_at": source_deadline,
    }
    before = {
        field: getattr(fulfillment, field)
        for field in desired
    }
    changes = {
        field: value
        for field, value in desired.items()
        if before[field] != value
    }
    if changes:
        changes["updated_at"] = timezone.now()
        QuerySet.update(
            SampleFulfillment.objects.filter(
                pk=fulfillment.pk,
                tenant_id=user.tenant_id,
            ),
            **changes,
        )
        fulfillment.refresh_from_db()
    return before, {
        field: getattr(fulfillment, field)
        for field in desired
    }


def _replace_sample_items_from_source(*, user, fulfillment, item_payloads, currency="CNY"):
    """Persist source item facts exactly, without ProductSKU repricing.

    The controlled Feishu export is an historical snapshot.  Its costs are
    facts from the source system, not a request to price against today's
    ``ProductSKU.purchase_price``.  This path therefore allows a zero quantity
    placeholder, keeps missing and zero costs distinct, and only aggregates
    an explicit source ``cost_amount``.
    """

    if not isinstance(item_payloads, (list, tuple)):
        raise ValidationError({"items": "Source items must be a list."})

    # The source adapter has one fixed accounting currency and source owner.
    # Do not let a row payload (or a caller accidentally using the helper) turn
    # this into a current-catalog repricing path.
    if currency not in (None, "", "CNY"):
        raise ValidationError({"currency": "Source fulfillment costs must use CNY."})
    source_currency = "CNY"
    source_cost = FEISHU_FULL_SAMPLE_STATUS_SOURCE
    normalized_items = []
    for raw_payload in item_payloads:
        if not isinstance(raw_payload, Mapping):
            raise ValidationError({"items": "Each source item must be an object."})
        payload = _inherit_item_product(
            raw_payload,
            product_id=fulfillment.external_product_id,
            product_name=fulfillment.product_name_snapshot,
        )
        # A source ``sku`` is display input, not permission to bind a possibly
        # cross-tenant ProductSKU.  requested_sku remains the exact source
        # value while normalized_sku is only a search/display helper.
        requested_sku = payload.get("requested_sku")
        if requested_sku in (None, ""):
            requested_sku = payload.get("sku")
        requested_sku = str(requested_sku).strip() or None if requested_sku is not None else None
        unit_cost = _source_decimal(
            payload.get("unit_cost", payload.get("source_unit_cost")),
            field="unit_cost",
        )
        cost_amount = _source_decimal(
            payload.get("cost_amount", payload.get("source_cost_amount")),
            field="cost_amount",
        )
        quantity = payload.get("quantity", 0)
        if isinstance(quantity, bool):
            raise ValidationError({"items": "Source item quantity must be a non-negative integer."})
        try:
            quantity = int(quantity)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"items": "Source item quantity must be a non-negative integer."}) from exc
        if quantity < 0:
            raise ValidationError({"items": "Source item quantity must be non-negative."})

        site_code = str(payload.get("site_code") or "").strip()
        if not site_code:
            raise ValidationError({"items": "Each source item requires site_code."})
        product_id = str(payload.get("external_product_id") or "").strip()
        product_name = str(payload.get("product_name") or "").strip()
        item_data = {
            "sku_id": None,
            "external_product_id": product_id,
            "site_code": site_code,
            "requested_sku": requested_sku,
            "product_name": product_name,
            "quantity": quantity,
            "unit_price": None,
            "unit_cost": unit_cost,
            "cost_amount": cost_amount,
            "currency": source_currency,
            "price_match_status": "not_imported",
            "normalized_sku": _normalize_sku(requested_sku),
            "matched_sku_code": "",
            "matched_legacy_sku_code": "",
            "sales_amount": None,
            "cost_match_status": "source",
            "cost_source": source_cost,
            "price_source": "",
            "price_snapshot_at": None,
            "cost_snapshot_at": None,
            "match_notes": "",
        }
        normalized_items.append(item_data)

    # The source export can contain repeated SKU lines, while SampleItem has a
    # tenant/fulfillment/requested_sku uniqueness constraint.  Aggregate only
    # exact source facts: quantities and known costs are additive, while a
    # missing cost stays missing.  Empty requested_sku values remain separate
    # positional placeholders because SQL permits multiple NULLs.
    aggregated_items = []
    by_requested_sku = {}
    comparable_fields = (
        "external_product_id",
        "site_code",
        "requested_sku",
        "product_name",
        "unit_price",
        "unit_cost",
        "currency",
        "price_match_status",
        "normalized_sku",
        "matched_sku_code",
        "matched_legacy_sku_code",
        "sales_amount",
        "cost_match_status",
        "cost_source",
        "price_source",
        "price_snapshot_at",
        "cost_snapshot_at",
        "match_notes",
    )
    for item_data in normalized_items:
        requested_sku = item_data["requested_sku"]
        if requested_sku in (None, ""):
            aggregated_items.append(item_data)
            continue
        existing = by_requested_sku.get(requested_sku)
        if existing is None:
            existing = dict(item_data)
            by_requested_sku[requested_sku] = existing
            aggregated_items.append(existing)
            continue
        differences = [
            field
            for field in comparable_fields
            if _canonical_scalar(existing[field]) != _canonical_scalar(item_data[field])
        ]
        if differences:
            raise ValidationError(
                {"items": f"Duplicate source SKU {requested_sku!r} has conflicting facts: {differences}."},
                code="conflict",
            )
        existing["quantity"] += item_data["quantity"]
        if existing["cost_amount"] is None or item_data["cost_amount"] is None:
            existing["cost_amount"] = None
        else:
            existing["cost_amount"] += item_data["cost_amount"]

    source_items = list(
        SampleItem.objects.select_for_update()
        .filter(tenant_id=user.tenant_id, fulfillment_id=fulfillment.pk)
        .order_by("id")
    )
    # The previous controlled loader used ``legacy_shop_analytics_bd`` for
    # these same source-owned facts.  A business-number adoption may migrate
    # those rows in place; catalog/manual items remain outside this adapter.
    managed_cost_sources = {
        "",
        source_cost,
        "feishu_source",
        "legacy_shop_analytics_bd",
    }
    foreign_items = [
        item
        for item in source_items
        if (item.cost_source or "") not in managed_cost_sources
    ]
    if foreign_items:
        raise ValidationError(
            {
                "items": (
                    "Source import cannot overwrite sample items owned by another "
                    "cost source."
                )
            },
            code="conflict",
        )
    existing_by_sku = {}
    existing_null_items = []
    for item in source_items:
        key = item.requested_sku
        if key in (None, ""):
            existing_null_items.append(item)
            continue
        if key in existing_by_sku:
            # A pre-existing duplicate violates the current model contract;
            # never choose one row or physically delete the other during an
            # import.  The outer transaction remains rollback-safe.
            raise ValidationError(
                {"items": f"Existing source fulfillment contains duplicate SKU {key!r}."},
                code="conflict",
            )
        existing_by_sku[key] = item

    desired_keys = {
        item["requested_sku"]
        for item in aggregated_items
        if item["requested_sku"] not in (None, "")
    }
    stale_items = [
        item
        for item in source_items
        if (
            item.requested_sku not in (None, "")
            and item.requested_sku not in desired_keys
        )
    ]
    null_desired_count = sum(
        item["requested_sku"] in (None, "") for item in aggregated_items
    )
    if len(existing_null_items) > null_desired_count:
        stale_items.extend(existing_null_items[null_desired_count:])
    if stale_items:
        raise ValidationError(
            {
                "items": (
                    "Source update would remove existing sample items; "
                    "physical deletion is not allowed."
                )
            },
            code="conflict",
        )

    source_item_fields = (
        "external_product_id",
        "site_code",
        "requested_sku",
        "product_name",
        "quantity",
        "sku_id",
        "unit_price",
        "unit_cost",
        "cost_amount",
        "currency",
        "price_match_status",
        "normalized_sku",
        "matched_sku_code",
        "matched_legacy_sku_code",
        "sales_amount",
        "cost_match_status",
        "cost_source",
        "price_source",
        "price_snapshot_at",
        "cost_snapshot_at",
        "match_notes",
    )
    matched_null_index = 0
    for item_data in aggregated_items:
        requested_sku = item_data["requested_sku"]
        if requested_sku in (None, ""):
            existing = (
                existing_null_items[matched_null_index]
                if matched_null_index < len(existing_null_items)
                else None
            )
            matched_null_index += 1
        else:
            existing = existing_by_sku.get(requested_sku)
        if existing is None:
            _save(SampleItem(tenant=user.tenant, fulfillment=fulfillment, **item_data))
            continue
        changes = {
            field: item_data[field]
            for field in source_item_fields
            if getattr(existing, field) != item_data[field]
        }
        if changes:
            changes["updated_at"] = timezone.now()
            QuerySet.update(
                SampleItem.objects.filter(
                    pk=existing.pk,
                    tenant_id=user.tenant_id,
                    fulfillment_id=fulfillment.pk,
                ),
                **changes,
            )

    sku_quantity = sum(item["quantity"] for item in aggregated_items)
    cost_total = Decimal("0")
    has_cost_amount = False
    for item in aggregated_items:
        if item["cost_amount"] is not None:
            cost_total += item["cost_amount"]
            has_cost_amount = True

    desired_cost = cost_total if has_cost_amount else None
    desired_values = {
        "sku_quantity": sku_quantity,
        "calculated_cost": desired_cost,
        "sales_amount": None,
        "pricing_status": "pending",
        "priced_at": None,
    }
    current_values = {
        field: getattr(fulfillment, field)
        for field in desired_values
    }
    if current_values != desired_values:
        desired_values["updated_at"] = timezone.now()
        QuerySet.update(
            SampleFulfillment.objects.filter(pk=fulfillment.pk, tenant=user.tenant),
            **desired_values,
        )
    fulfillment.refresh_from_db()
    return fulfillment


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


def _recalculate_sample_costs(*, user, fulfillment, item_payloads):
    """Replace item purchase-cost facts and aggregate cost in one transaction."""
    item_payloads = _normalize_item_payloads(item_payloads)
    SampleItem.objects.filter(
        tenant=user.tenant,
        fulfillment=fulfillment,
    ).delete()

    sku_quantity = 0
    cost_total = Decimal("0")
    any_cost_matched = False
    snapshot_time = timezone.now()
    for raw_payload in item_payloads:
        payload = _inherit_item_product(
            raw_payload,
            product_id=fulfillment.external_product_id,
            product_name=fulfillment.product_name_snapshot,
        )
        # Computed fields must never be accepted from a client or reused verbatim.
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
        normalized_sku, cost_sku, cost_status = _purchase_cost_for_payload(user.tenant, payload)
        quantity = payload.get("quantity", 1)
        unit_cost = cost_sku.purchase_price if cost_sku else None
        cost_amount = unit_cost * quantity if unit_cost is not None else None
        item = SampleItem(
            tenant=user.tenant,
            fulfillment=fulfillment,
            unit_cost=unit_cost,
            normalized_sku=normalized_sku,
            matched_sku_code=cost_sku.sku_code if cost_sku else "",
            matched_legacy_sku_code=cost_sku.legacy_sku_code if cost_sku else "",
            cost_amount=cost_amount,
            cost_match_status=cost_status,
            cost_source="products_productsku" if cost_sku else "",
            cost_snapshot_at=snapshot_time if cost_sku else None,
            **payload,
        )
        _save(item)
        sku_quantity += quantity
        if cost_amount is not None:
            cost_total += cost_amount
            any_cost_matched = True

    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk, tenant=user.tenant),
        sku_quantity=sku_quantity,
        calculated_cost=cost_total if any_cost_matched else None,
        sales_amount=None,
        pricing_status="pending",
        priced_at=None,
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
    if any(
        field in data
        for field in ("source_owner_name_snapshot", "source_dispatcher_name_snapshot")
    ):
        raise ValidationError(
            {"source_personnel": "Source personnel snapshots are writable only by the Feishu import adapter."},
            code="forbidden",
        )
    # task_no is server-owned even for direct service callers that bypass the serializer.
    data.pop("task_no", None)
    owner_values = data.pop("owners", None)
    if owner_values is None:
        owner_values = [data.get("owner")] if data.get("owner") is not None else []
    owner_ids = list(dict.fromkeys(_pk(value) for value in owner_values))
    if not owner_ids:
        raise ValidationError({"owners": "At least one owner is required."})
    owner_map = {
        owner_id: _tenant_user(user, owner_id, for_update=False)
        for owner_id in sorted(owner_ids)
    }
    owners = [owner_map[owner_id] for owner_id in owner_ids]
    for candidate in owners:
        _assert_active_bd_owner(user, candidate)
    owner = owners[0]
    store = _tenant_store(user, _pk(data["store"]), for_update=False)
    if store.status != "active":
        raise ValidationError({"store": "Only active stores can be assigned to outreach tasks."})
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
        owner_map = {owner_id: _locked_user(user, owner_id) for owner_id in sorted(owner_ids)}
        owners = [owner_map[owner_id] for owner_id in owner_ids]
        owner = owners[0]
    else:
        store = _locked_store(user, store.pk)
        owner_map = {owner_id: _locked_user(user, owner_id) for owner_id in sorted(owner_ids)}
        owners = [owner_map[owner_id] for owner_id in owner_ids]
        owner = owners[0]
    if store.status != "active":
        raise ValidationError({"store": "Only active stores can be assigned to outreach tasks."})
    for candidate in owners:
        _assert_active_bd_owner(user, candidate)
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
    task.owners.set(owners)
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
    _lock_tenant(user)
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
    if any(
        field in data
        for field in ("source_owner_name_snapshot", "source_dispatcher_name_snapshot")
    ):
        raise ValidationError(
            {"source_personnel": "Source personnel snapshots are writable only by the Feishu import adapter."},
            code="forbidden",
        )
    if not data:
        raise ValidationError({"detail": "At least one editable task field is required."})

    owner_values = data.pop("owners", None)
    owners = None
    if owner_values is not None:
        owner_ids = list(dict.fromkeys(_pk(value) for value in owner_values))
        if not owner_ids:
            raise ValidationError({"owners": "At least one owner is required."})
        owner_map = {owner_id: _locked_user(user, owner_id) for owner_id in sorted(owner_ids)}
        owners = [owner_map[owner_id] for owner_id in owner_ids]
        for candidate in owners:
            _assert_active_bd_owner(user, candidate)
        data["owner"] = owners[0]

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
    if owners is not None:
        task.owners.set(owners)
    _audit(
        user,
        "outreach_update",
        "outreach_task",
        task,
        before=before,
        after=after,
    )
    if "target_count" in changes:
        task = recompute_outreach_task_completion(user=user, task=task)
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
def import_outreach_target_snapshot(
    *,
    user,
    tenant,
    source,
    task,
    influencer,
    source_task_external_id,
    source_sample_external_id,
    first_linked_at,
    actor=None,
    return_metadata=False,
):
    """Materialize one historical Feishu task/creator relation.

    Interactive writes must continue to reject target changes on terminal
    tasks.  The fixed full-export importer has a narrower need: an approved
    legacy task can already be terminal even though the source snapshot proves
    that its creator relation existed earlier.  This adapter keeps that
    exception source-scoped, tenant-locked, idempotent and audited without
    relaxing ``OutreachTarget.clean`` or the public services.
    """

    if source != FEISHU_FULL_SAMPLE_STATUS_SOURCE:
        raise ValidationError({"source": "Unsupported outreach target import source."})
    if user is None or getattr(user, "tenant_id", None) is None:
        raise ValidationError({"actor": "An explicit tenant import actor is required."})
    if actor is not None and _pk(actor) != user.pk:
        raise ValidationError({"actor": "Import actor does not match the authenticated user."})
    if tenant is None or _pk(tenant) != user.tenant_id:
        raise ValidationError({"tenant": "Import tenant does not match the actor tenant."})

    task_external_id = str(source_task_external_id or "").strip()
    sample_external_id = str(source_sample_external_id or "").strip()
    if not task_external_id or len(task_external_id) > 160:
        raise ValidationError({"source_task_external_id": "Source task id must be 1-160 characters."})
    if not sample_external_id or len(sample_external_id) > 160:
        raise ValidationError({"source_sample_external_id": "Source sample id must be 1-160 characters."})
    linked_at = _source_datetime(first_linked_at, field="first_linked_at")
    if linked_at is None:
        raise ValidationError({"first_linked_at": "Source link time is required."})

    _lock_tenant(user)
    locked_influencer = _tenant_influencer(user, _pk(influencer), for_update=False)
    locked_influencer = _assert_influencer_not_blacklisted(
        user=user,
        influencer=locked_influencer,
        message="Blacklisted influencers cannot be imported as outreach targets.",
        code="conflict",
    )
    locked_task = _locked_task(user, _pk(task))
    if locked_task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive imported targets."})
    allowed_task_sources = {source, "legacy_shop_analytics_bd"}
    if locked_task.source not in allowed_task_sources:
        raise ValidationError(
            {"source": "Outreach task is owned by another source."},
            code="conflict",
        )
    if locked_task.source == source:
        source_key_matches = str(locked_task.external_id or "").strip() == task_external_id
    else:
        source_key_matches = str(locked_task.task_no or "").strip() == task_external_id
    if not source_key_matches:
        raise ValidationError(
            {"source_task_external_id": "Source task id does not match the imported task."},
            code="conflict",
        )

    target = (
        OutreachTarget.objects.select_for_update()
        .filter(
            tenant=user.tenant,
            task=locked_task,
            influencer=locked_influencer,
        )
        .first()
    )
    created = target is None
    restored = False
    historical_terminal_exception = locked_task.status in TERMINAL_OUTREACH_TASK_STATUSES
    if target is None:
        target = OutreachTarget(
            tenant=user.tenant,
            task=locked_task,
            influencer=locked_influencer,
            first_linked_at=linked_at,
            notes=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        )
        if historical_terminal_exception:
            # ``bulk_create`` deliberately bypasses the model's interactive
            # terminal-task guard.  Every relation and source invariant above
            # has already been revalidated under the tenant/task locks.
            QuerySet.bulk_create(OutreachTarget.objects.all(), [target])
            target = OutreachTarget.objects.get(
                tenant=user.tenant,
                task=locked_task,
                influencer=locked_influencer,
            )
        else:
            _save(target)
    elif target.is_deleted:
        before_version = target.version
        updated = QuerySet.update(
            OutreachTarget.objects.filter(
                pk=target.pk,
                tenant=user.tenant,
                is_deleted=True,
                version=before_version,
            ),
            is_deleted=False,
            deleted_at=None,
            version=before_version + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise ValidationError(
                {"version": "Outreach target was changed by another request."},
                code="conflict",
            )
        target.refresh_from_db()
        restored = True

    if created or restored:
        _audit(
            user,
            "feishu_import_target_create" if created else "feishu_import_target_restore",
            "outreach_target",
            target,
            before={"is_deleted": True} if restored else {},
            after={
                "source": source,
                "source_task_external_id": task_external_id,
                "source_sample_external_id": sample_external_id,
                "task_id": locked_task.pk,
                "influencer_id": locked_influencer.pk,
                "first_linked_at": target.first_linked_at.isoformat(),
                "source_first_linked_at": linked_at.isoformat(),
                "is_deleted": False,
                "historical_terminal_exception": historical_terminal_exception,
            },
        )

    if return_metadata:
        return {
            "target": target,
            "created": created,
            "restored": restored,
            "changed": created or restored,
            "outcome": "created" if created else ("restored" if restored else "noop"),
        }
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
def restore_outreach_task(*, user, task, expected_version, recompute_related=True):
    _lock_tenant(user)
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
    if recompute_related:
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
    """Complete an active task once unique sampled creators reach the target."""
    _lock_tenant(user)
    task = _locked_task(user, _pk(task))
    if task.is_deleted or task.status not in {
        OutreachTask.Status.PENDING,
        OutreachTask.Status.IN_PROGRESS,
    }:
        return task
    sampled_identities = {
        influencer_identity_key(
            influencer_id=influencer_id,
            platform=platform,
            handle=handle,
        )
        for influencer_id, platform, handle in SampleFulfillment.objects.filter(
            tenant=user.tenant,
            outreach_task=task,
            is_deleted=False,
        ).values_list(
            "influencer_id",
            "influencer__platform",
            "influencer__handle",
        )
    }
    sampled_count = len(sampled_identities)
    if task.target_count <= 0 or sampled_count < task.target_count:
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
                "sampled_influencer_count": sampled_count,
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
        detail = {"influencer": message or "该达人已被加入黑名单，不能创建送样。"}
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
    _lock_tenant(user)
    if not request_key or len(request_key) > 128:
        raise ValidationError({"idempotency_key": "Idempotency-Key must be 1-128 characters."})
    data = dict(validated_data)
    if "source_owner_name_snapshot" in data:
        raise ValidationError(
            {"source_personnel": "Source personnel snapshots are writable only by the Feishu import adapter."},
            code="forbidden",
        )
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
    requested_link_type = str(data.get("link_type") or "").strip()
    if requested_link_type == "direct" and task is not None:
        raise ValidationError(
            {"link_type": "Direct samples must be standalone and cannot link to outreach tasks."},
            code="conflict",
        )
    if requested_link_type == "direct" and data.get("outreach_target") is not None:
        raise ValidationError(
            {"link_type": "Direct samples must be standalone and cannot link to outreach targets."},
            code="conflict",
        )
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
            source=data.get("source"),
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
        if not product_id and data.get("link_type") != "direct":
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
    for field_name in ("sku_quantity", "sales_amount", "calculated_cost", "pricing_status", "priced_at"):
        fulfillment_data.pop(field_name, None)
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

    fulfillment = _recalculate_sample_costs(
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
    if task is not None and fulfillment.source != FEISHU_FULL_SAMPLE_STATUS_SOURCE:
        recompute_outreach_task_completion(user=user, task=task)
    return fulfillment, True


def _import_payload_value(payload, *names):
    """Read a small, explicit context field from a source event payload."""
    if isinstance(payload, Mapping):
        for name in names:
            if name in payload:
                return payload[name]
        return None
    for name in names:
        value = getattr(payload, name, None)
        if value is not None:
            return value
    return None


def _import_source_status(value):
    raw = getattr(value, "value", value)
    key = str(raw or "").strip()
    status = FEISHU_FULL_SAMPLE_STATUS_MAP.get(key)
    if status is None:
        status = FEISHU_FULL_SAMPLE_STATUS_MAP.get(key.casefold())
    if status is None:
        raise ValidationError(
            {"status": "Source snapshot status must be pending, shipped, or published."}
        )
    return status


def _import_source_event_id(event, operation_log):
    """Return a stable source row identity; never derive one from the clock."""
    explicit_names = (
        "source_event_id",
        "snapshot_key",
        "source_row_key",
        "record_id",
        "event_id",
        "id",
        "idempotency_key",
    )
    for payload in (event, operation_log):
        value = _import_payload_value(payload, *explicit_names)
        if value not in (None, ""):
            return str(value).strip()

    # The source package uses an external sample id.  If a row/payload digest
    # is available, include it so a regenerated source id cannot accidentally
    # claim an unrelated payload while still replaying the same row.
    external_id = _import_payload_value(event, "external_id", "sample_external_id")
    digest = _import_payload_value(event, "payload_hash", "row_hash", "snapshot_hash")
    if external_id not in (None, ""):
        key = str(external_id).strip()
        if digest not in (None, ""):
            key = f"{key}:{str(digest).strip()}"
        return key
    if isinstance(event, str):
        return event.strip()
    return ""


def _import_source_observed_at(event):
    """Parse an optional source timestamp without fabricating one."""
    value = _import_payload_value(
        event,
        "source_observed_at",
        "observed_at",
        "source_updated_at",
    )
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        observed_at = value
    else:
        text = str(value).strip()
        observed_at = parse_datetime(text)
        if observed_at is None:
            parsed_date = parse_date(text)
            if parsed_date is not None:
                observed_at = datetime.combine(parsed_date, time.min)
        if observed_at is None:
            raise ValidationError({"event": "source_observed_at is not a valid timestamp."})
    if timezone.is_naive(observed_at):
        observed_at = timezone.make_aware(observed_at, timezone.get_current_timezone())
    return observed_at


def _import_status_target(current_status, requested_status):
    """Compute the status this compatibility path is allowed to persist."""
    if current_status == requested_status:
        return current_status
    current_rank = _FEISHU_IMPORT_STATUS_ORDER.get(current_status)
    requested_rank = _FEISHU_IMPORT_STATUS_ORDER[requested_status]
    if current_rank is not None and requested_rank > current_rank:
        return requested_status
    # A published snapshot must never be rewritten to an older source value.
    # The same monotonic rule protects shipped/delivered/overdue records from
    # a stale pending snapshot as well.
    if current_rank is not None and requested_rank <= current_rank:
        return current_status
    # A controlled historical snapshot may refresh source-owned facts on a
    # fulfillment that later reached a terminal or creator-managed state.
    # Preserve that newer state and record the stale observation; never
    # regress it to the source snapshot's pending/shipped/published value.
    if current_status in _FEISHU_IMPORT_PRESERVED_STATUSES:
        return current_status
    # Unknown states are outside this compatibility contract and must not be
    # guessed or silently changed.
    return None


def _import_operation_log_exists(*, tenant_id, fulfillment_id, source, source_event_id):
    from apps.audit.models import OperationLog

    logs = OperationLog.objects.filter(
        tenant_id=tenant_id,
        module="influencers",
        action="sample_status_import",
        object_type="sample_fulfillment",
        object_id=str(fulfillment_id),
    ).order_by("id")
    for log in logs:
        after_data = log.after_data if isinstance(log.after_data, Mapping) else {}
        if (
            after_data.get("source") == source
            and after_data.get("source_event_id") == source_event_id
        ):
            return log
    return None


def _import_task_status(value):
    """Normalize the small, explicit task status vocabulary used by Feishu."""

    raw = getattr(value, "value", value)
    key = str(raw or "").strip()
    status = FEISHU_FULL_TASK_STATUS_MAP.get(key)
    if status is None:
        status = FEISHU_FULL_TASK_STATUS_MAP.get(key.casefold())
    if status is None:
        raise ValidationError(
            {"status": "Source task status must be pending, in_progress, completed, or cancelled."}
        )
    return status


def _import_task_source_datetime(row, *, field, explicit=None, names=(), date_names=(), time_names=()):
    """Parse a task source timestamp, including Feishu date/time columns."""

    if explicit not in (None, ""):
        return _source_datetime(explicit, field=field)
    row = row if isinstance(row, Mapping) else {}
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return _source_datetime(value, field=field)

    source_date = next(
        (row.get(name) for name in date_names if row.get(name) not in (None, "")),
        None,
    )
    source_time = next(
        (row.get(name) for name in time_names if row.get(name) not in (None, "")),
        None,
    )
    if source_date in (None, ""):
        return None
    if source_time in (None, ""):
        return _source_datetime(source_date, field=field)

    parsed_date = _source_datetime(source_date, field=field)
    if isinstance(source_time, datetime):
        parsed_time = source_time.timetz().replace(tzinfo=None)
    elif isinstance(source_time, time):
        parsed_time = source_time
    else:
        time_text = str(source_time).strip()
        parsed_time = None
        for fmt in ("%H:%M:%S", "%H:%M", "%H%M%S", "%H%M"):
            try:
                parsed_time = datetime.strptime(time_text, fmt).time()
                break
            except ValueError:
                continue
        if parsed_time is None:
            # Some exports put a complete datetime in the time column.  Let
            # the common parser handle that before reporting a source error.
            parsed = parse_datetime(time_text)
            if parsed is None:
                raise ValidationError({field: "Source date/time is not a valid timestamp."})
            parsed_time = parsed.timetz().replace(tzinfo=None)
    combined = datetime.combine(parsed_date.date(), parsed_time)
    if timezone.is_naive(combined):
        combined = timezone.make_aware(combined, timezone.get_current_timezone())
    return combined


def _import_task_status_target(current_status, requested_status):
    """Keep source task snapshots monotonic and never rewrite a terminal state."""

    if current_status == requested_status:
        return current_status
    current_rank = _FEISHU_TASK_STATUS_ORDER.get(current_status)
    requested_rank = _FEISHU_TASK_STATUS_ORDER[requested_status]
    if current_status in TERMINAL_OUTREACH_TASK_STATUSES:
        return None
    if current_rank is None:
        return None
    if requested_rank < current_rank:
        # A stale source snapshot must not regress an already advanced task.
        return current_status
    if requested_rank == current_rank and requested_status != current_status:
        # completed and cancelled are both terminal but are not interchangeable.
        return None
    return requested_status


def _import_task_operation_log_exists(*, tenant_id, task_id, source, source_event_id):
    from apps.audit.models import OperationLog

    logs = OperationLog.objects.filter(
        tenant_id=tenant_id,
        module="influencers",
        action="feishu_import_task_status",
        object_type="outreach_task",
        object_id=str(task_id),
    ).order_by("id")
    for log in logs:
        after_data = log.after_data if isinstance(log.after_data, Mapping) else {}
        if (
            after_data.get("source") == source
            and after_data.get("source_event_id") == source_event_id
        ):
            return log
    return None


def _import_task_external_id(*payloads):
    names = (
        "external_id",
        "task_external_id",
        "source_task_id",
        "task_id",
        "source_row_key",
        "task_no",
        "id",
        # ``record_id`` is the Feishu table's internal record key in the
        # reviewed export, not the task business/external id. Keep it only as
        # a last-resort compatibility alias when no explicit task id exists.
        "record_id",
    )
    for payload in payloads:
        value = _import_payload_value(payload, *names)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _import_task_field(data, row, field, *aliases):
    """Prefer validated relation objects/fields over raw source aliases."""

    if field in data and data[field] not in (None, ""):
        return data[field]
    for alias in aliases:
        if row.get(alias) not in (None, ""):
            return row[alias]
    return None


def _personnel_raw_name(mapping, role):
    """Read a source name without normalising or truncating its evidence."""
    def raw(value, field):
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValidationError({field: "Source personnel names must be strings."})
        return value

    if not isinstance(mapping, Mapping):
        return None
    entry = mapping.get(role)
    if isinstance(entry, Mapping):
        for key in (
            "source_name",
            "raw_name",
            "original_name",
            "name",
            "source_name_snapshot",
            "snapshot",
        ):
            if key in entry:
                return raw(entry[key], f"source_{role}_name_snapshot")
    for key in (
        f"source_{role}_name_snapshot",
        f"source_{role}_name",
        f"{role}_source_name",
        f"{role}_name",
        f"{role}_raw_name",
    ):
        if key in mapping:
            return raw(mapping[key], f"source_{role}_name_snapshot")
    return None


def _personnel_entry(mapping, role):
    if not isinstance(mapping, Mapping):
        return {}
    entry = mapping.get(role)
    if isinstance(entry, Mapping):
        return entry
    return mapping


def _personnel_resolution(mapping, role):
    entry = _personnel_entry(mapping, role)
    if not isinstance(entry, Mapping):
        return None
    for key in ("resolution", "provenance", "mapping", "match_type", "reason_code"):
        value = entry.get(key)
        if value not in (None, ""):
            return str(value).strip()
    for key in (f"{role}_resolution", f"{role}_provenance", f"{role}_mapping"):
        value = mapping.get(key) if isinstance(mapping, Mapping) else None
        if value not in (None, ""):
            return str(value).strip()
    return None


def _personnel_actual_id(mapping, role):
    entry = _personnel_entry(mapping, role)
    if not isinstance(entry, Mapping):
        return None
    for key in (
        "resolved_user_id",
        "actual_user_id",
        "resolved_id",
        "user_id",
        "actual_id",
        "id",
    ):
        value = entry.get(key)
        if value not in (None, ""):
            return _pk(value)
    for key in (f"{role}_resolved_user_id", f"{role}_user_id", f"{role}_actual_id"):
        value = mapping.get(key) if isinstance(mapping, Mapping) else None
        if value not in (None, ""):
            return _pk(value)
    return None


def _personnel_reason(mapping, role, resolution):
    # Reasons are a stable audit vocabulary, not caller-controlled text.
    return {
        "exact_match": "source name matched one qualified tenant user",
        "unmatched_fallback": "source name had no qualified tenant match; policy fallback used",
        "blank_dispatcher_uses_owner": "source dispatcher was blank; resolved owner reused",
    }.get(resolution, "source personnel mapping")


def _normalise_personnel_mapping(
    mapping,
    *,
    owner_name=None,
    dispatcher_name=None,
    owner_resolution=None,
    dispatcher_resolution=None,
    personnel_policy=None,
    roles=("owner",),
):
    """Validate the explicit importer-to-service personnel contract.

    The importer supplies the resolved foreign keys in ``validated_data`` and
    this function only validates the provenance envelope and preserves the raw
    source names.  It intentionally never resolves or creates users.
    """
    supplied = any(
        value is not None
        for value in (
            mapping,
            owner_name,
            dispatcher_name,
            owner_resolution,
            dispatcher_resolution,
            personnel_policy,
        )
    )
    if not supplied:
        return None
    if mapping is not None and not isinstance(mapping, Mapping):
        raise ValidationError({"personnel_mapping": "Personnel mapping must be an object."})
    mapping = dict(mapping or {})
    policy = personnel_policy or mapping.get("personnel_policy") or mapping.get("policy")
    if policy != FEISHU_PERSONNEL_POLICY:
        raise ValidationError(
            {"personnel_policy": "Unsupported personnel mapping policy."},
            code="conflict",
        )

    # Explicit kwargs are authoritative and let the importer pass the raw
    # fields without putting control metadata into validated model data.
    if owner_name is not None:
        existing_name = _personnel_raw_name(mapping, "owner")
        if existing_name is not None and str(existing_name) != str(owner_name):
            raise ValidationError(
                {"source_owner_name_snapshot": "Conflicting personnel source names were supplied."},
                code="conflict",
            )
        mapping["source_owner_name_snapshot"] = owner_name
    if dispatcher_name is not None:
        existing_name = _personnel_raw_name(mapping, "dispatcher")
        if existing_name is not None and str(existing_name) != str(dispatcher_name):
            raise ValidationError(
                {"source_dispatcher_name_snapshot": "Conflicting personnel source names were supplied."},
                code="conflict",
            )
        mapping["source_dispatcher_name_snapshot"] = dispatcher_name
    if owner_resolution is not None:
        existing_resolution = _personnel_resolution(mapping, "owner")
        if existing_resolution is not None and str(existing_resolution) != str(owner_resolution):
            raise ValidationError({"owner_resolution": "Conflicting personnel resolutions were supplied."}, code="conflict")
        mapping["owner_resolution"] = owner_resolution
    if dispatcher_resolution is not None:
        existing_resolution = _personnel_resolution(mapping, "dispatcher")
        if existing_resolution is not None and str(existing_resolution) != str(dispatcher_resolution):
            raise ValidationError({"dispatcher_resolution": "Conflicting personnel resolutions were supplied."}, code="conflict")
        mapping["dispatcher_resolution"] = dispatcher_resolution

    result = {"policy": policy}
    for role in roles:
        name = _personnel_raw_name(mapping, role)
        resolution = _personnel_resolution(mapping, role)
        # A role is considered supplied only when either an explicit raw name
        # or resolution was supplied.  This permits task imports that carry
        # only owner provenance while retaining an existing dispatcher value.
        if name is None and resolution is None:
            continue
        if name is None:
            name = ""
        if len(name) > 255:
            raise ValidationError(
                {f"source_{role}_name_snapshot": "Source personnel name must be at most 255 characters."}
            )
        if resolution not in FEISHU_PERSONNEL_RESOLUTIONS:
            raise ValidationError(
                {f"{role}_resolution": "Unsupported personnel mapping resolution."},
                code="conflict",
            )
        reason = _personnel_reason(mapping, role, resolution)
        if len(reason) > 5000:
            raise ValidationError({f"{role}_resolution": "Personnel mapping reason is too long."})
        result[role] = {
            "name": name,
            "resolution": resolution,
            "reason": reason,
            "actual_id": _personnel_actual_id(mapping, role),
        }
    if not any(role in result for role in roles):
        raise ValidationError({"personnel_mapping": "At least one personnel mapping role is required."})
    return result


def _require_personnel_roles(personnel, roles):
    """Require the complete provenance envelope for a full source-row import."""
    if personnel is None:
        raise ValidationError(
            {"personnel_mapping": "Complete source-row imports require personnel provenance."},
            code="required",
        )
    missing = [role for role in roles if role not in personnel]
    if missing:
        raise ValidationError(
            {"personnel_mapping": f"Missing personnel provenance role(s): {', '.join(missing)}."},
            code="required",
        )


def _qualified_personnel_matches(user, source_name):
    """Return the current tenant's qualified users matching a source name."""
    source_name = str(source_name or "")
    if not source_name.strip():
        return get_user_model().objects.none()
    eligible = get_user_model().objects.filter(
        tenant_id=user.tenant_id,
        is_active=True,
        user_type=get_user_model().UserType.INTERNAL,
    ).filter(
        user_roles__tenant_id=user.tenant_id,
        user_roles__role__tenant_id=user.tenant_id,
        user_roles__role__code="bd",
        user_roles__role__status="active",
    ).distinct()
    normalized = unicodedata.normalize("NFKC", source_name).strip().casefold()
    ids = [
        candidate.pk
        for candidate in eligible.only("pk", "username", "full_name")
        if normalized in {
            unicodedata.normalize("NFKC", str(candidate.username or "")).strip().casefold(),
            unicodedata.normalize("NFKC", str(candidate.full_name or "")).strip().casefold(),
        }
    ]
    return get_user_model().objects.filter(pk__in=ids)


def _validate_personnel_role(*, user, role, entry, actual_user, owner_user=None, owner_entry=None):
    """Recheck mapping against locked actual accounts during apply."""
    if entry is None:
        return
    actual_id = _pk(actual_user)
    supplied_id = entry.get("actual_id")
    if supplied_id is not None and _pk(supplied_id) != actual_id:
        raise ValidationError(
            {f"{role}_resolution": "Resolved personnel id does not match the imported relation."},
            code="conflict",
        )
    resolution = entry["resolution"]
    name = entry["name"]
    candidates = _qualified_personnel_matches(user, name)
    if resolution == "exact_match":
        if candidates.count() != 1 or candidates.first().pk != actual_id:
            raise ValidationError(
                {f"{role}_resolution": "Exact personnel mapping is no longer unique or does not match."},
                code="conflict",
            )
    elif resolution == "unmatched_fallback":
        if candidates.exists():
            raise ValidationError(
                {f"{role}_resolution": "Fallback requires zero qualified source-name matches."},
                code="conflict",
            )
        fallback_candidates = get_user_model().objects.filter(
            tenant_id=user.tenant_id,
            is_active=True,
            user_type=get_user_model().UserType.INTERNAL,
            user_roles__tenant_id=user.tenant_id,
            user_roles__role__tenant_id=user.tenant_id,
            user_roles__role__code="bd",
            user_roles__role__status="active",
        ).distinct()
        # The policy names one exact service account.  Do not apply the
        # importer-side display-name normalization here: accepting full-width,
        # case-folded, or padded usernames would make a Unicode lookalike account
        # a different fallback principal than the reviewed ``liyejun`` account.
        fallback_users = [
            candidate
            for candidate in fallback_candidates
            if str(candidate.username or "") == FEISHU_PERSONNEL_FALLBACK_USERNAME
        ]
        if len(fallback_users) != 1 or fallback_users[0].pk != actual_id:
            raise ValidationError(
                {f"{role}_resolution": "The configured personnel fallback is not uniquely qualified."},
                code="conflict",
            )
    elif resolution == "blank_dispatcher_uses_owner":
        if role != "dispatcher" or unicodedata.normalize("NFKC", name).strip():
            raise ValidationError(
                {f"{role}_resolution": "Blank-dispatcher provenance requires an empty source dispatcher name."},
                code="conflict",
            )
        if owner_entry is None or owner_user is None or actual_id != _pk(owner_user):
            raise ValidationError(
                {f"{role}_resolution": "Blank-dispatcher provenance must reuse the resolved owner account."},
                code="conflict",
            )


def _personnel_audit_data(*, personnel, task=None, fulfillment=None):
    data = {"personnel_policy": personnel["policy"]}
    for role, entry in personnel.items():
        if role == "policy":
            continue
        data.update(
            {
                f"source_{role}_name_snapshot": entry["name"],
                f"{role}_resolution": entry["resolution"],
                f"{role}_reason": entry["reason"],
                f"actual_{role}_id": (
                    getattr(task, f"{role}_id", None)
                    if task is not None
                    else getattr(fulfillment, f"{role}_id", None)
                ),
            }
        )
    return data


@transaction.atomic
def import_outreach_task_snapshot(
    status=None,
    event=None,
    operation_log=None,
    *,
    user=None,
    tenant=None,
    task=None,
    source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    source_row=None,
    request_key=None,
    request_hash=None,
    validated_data=None,
    actor=None,
    dispatch_time=None,
    started_at=None,
    outreach_at=None,
    finalized_at=None,
    personnel_mapping=None,
    source_owner_name_snapshot=None,
    source_dispatcher_name_snapshot=None,
    owner_resolution=None,
    dispatcher_resolution=None,
    personnel_policy=None,
    return_metadata=False,
):
    """Upsert one Feishu task snapshot with audited, source-owned timestamps.

    This is the compatibility adapter for the reviewed full export.  It does
    not call ``transition_outreach_task``: that public workflow service uses
    execution time for state timestamps, while a source snapshot must preserve
    the source's explicit dispatch/start dates and leave unknown completion
    dates unknown.  The result is ``(task, created)`` like the sample snapshot
    adapter.
    """

    if source != FEISHU_FULL_SAMPLE_STATUS_SOURCE:
        raise ValidationError({"source": "Unsupported outreach task import source."})
    personnel = _normalise_personnel_mapping(
        personnel_mapping,
        owner_name=source_owner_name_snapshot,
        dispatcher_name=source_dispatcher_name_snapshot,
        owner_resolution=owner_resolution,
        dispatcher_resolution=dispatcher_resolution,
        personnel_policy=personnel_policy,
        roles=("owner", "dispatcher"),
    )
    _require_personnel_roles(personnel, ("owner", "dispatcher"))
    if user is None:
        user = actor
    if user is None:
        # Resolution from a payload is deliberately limited to a concrete user
        # primary key and tenant.  A source row cannot cause an actor guess.
        payload_user = _import_payload_value(event, "actor", "user") or _import_payload_value(
            operation_log, "actor", "user"
        )
        payload_tenant = _import_payload_value(event, "tenant", "tenant_id") or _import_payload_value(
            operation_log, "tenant", "tenant_id"
        )
        if payload_user is not None and payload_tenant is not None:
            user = get_user_model().objects.filter(
                pk=_pk(payload_user), tenant_id=_pk(payload_tenant)
            ).first()
    if user is None or getattr(user, "tenant_id", None) is None:
        raise ValidationError({"actor": "An explicit tenant import actor is required."})
    if actor is not None:
        if getattr(actor, "tenant_id", None) != user.tenant_id:
            raise ValidationError({"actor": "Import actor must belong to the actor tenant."})
        if actor.pk != user.pk:
            raise ValidationError({"actor": "The import actor and user must match."}, code="conflict")
    if tenant is None:
        tenant = getattr(user, "tenant", None)
    if tenant is None or getattr(tenant, "pk", None) != user.tenant_id:
        raise ValidationError({"tenant": "Import tenant does not match the actor tenant."})

    row = source_row if isinstance(source_row, Mapping) else {}
    if not row and isinstance(event, Mapping):
        row = event
    for payload in (row, event, operation_log):
        payload_source = _import_payload_value(payload, "source", "source_name")
        if payload_source not in (None, "", "飞书") and payload_source != source:
            raise ValidationError({"source": "Source task row does not match the import source."})
        payload_tenant = _import_payload_value(payload, "tenant", "tenant_id")
        if payload_tenant is not None and _pk(payload_tenant) != user.tenant_id:
            raise ValidationError({"tenant": "Source task tenant does not match the actor tenant."})

    if status in (None, ""):
        status = _import_payload_value(row, "source_status", "status")
    if status in (None, ""):
        status = _import_payload_value(event, "source_status", "status")
    if status in (None, ""):
        status = _import_payload_value(operation_log, "source_status", "status")
    requested_status = _import_task_status(status)
    for payload in (event, operation_log):
        payload_status = _import_payload_value(payload, "source_status", "status")
        if payload_status not in (None, "") and _import_task_status(payload_status) != requested_status:
            raise ValidationError(
                {"status": "Source task event status does not match the requested status."},
                code="conflict",
            )

    data = dict(validated_data or {})
    external_id = _import_task_external_id(task, row, event, operation_log, data)
    if not external_id:
        raise ValidationError({"source_row": "Source task id is required."})
    if len(external_id) > 160:
        raise ValidationError({"source_row": "Source task id must be at most 160 characters."})
    for payload in (row, event, operation_log):
        payload_id = _import_task_external_id(payload)
        if payload_id and payload_id != external_id:
            raise ValidationError(
                {"source_row": "Source task ids do not identify the same row."},
                code="conflict",
            )

    # Status snapshots are independently replayable: the same source task can
    # move from in_progress to completed without reusing the earlier event key.
    # The adapter owns this key, so callers need not pre-compose it (an
    # explicitly supplied legacy key is treated only as source context).
    source_event_id = f"{external_id}:{requested_status}"
    if len(source_event_id) > 160:
        raise ValidationError({"event": "Source event id must be at most 160 characters."})

    # ``task_no`` is a source business number and is intentionally not replaced
    # with the server's DRJL sequence.  Existing rows can be adopted from the
    # explicitly approved legacy source only when this source row matches.
    task_no_value = _import_task_field(data, row, "task_no", "task_no", "source_task_no", "number")
    task_no = str(task_no_value or external_id).strip()
    if not task_no or len(task_no) > 80:
        raise ValidationError({"task_no": "Import task number must be 1-80 characters."})

    # Parse source chronology before any write.  No fallback to ``timezone.now``
    # is allowed for dispatch/start/finalization fields.
    parsed_dispatch = _import_task_source_datetime(
        row,
        field="dispatch_time",
        explicit=dispatch_time,
        names=("dispatch_time", "dispatch_timestamp", "dispatch_at"),
        date_names=("dispatch_date",),
        time_names=("dispatch_clock",),
    )
    parsed_started = _import_task_source_datetime(
        row,
        field="started_at",
        explicit=started_at,
        names=("started_at", "start_timestamp", "start_datetime"),
        date_names=("start_date",),
        time_names=("start_time",),
    )
    parsed_outreach = _import_task_source_datetime(
        row,
        field="outreach_at",
        explicit=outreach_at,
        names=("outreach_at", "outreach_timestamp", "outreach_datetime"),
        date_names=("outreach_date",),
        time_names=("outreach_time",),
    )
    parsed_finalized = _import_task_source_datetime(
        row,
        field="finalized_at",
        explicit=finalized_at,
        names=("finalized_at", "completed_at", "completion_timestamp", "cancelled_at"),
        date_names=("finalized_date", "completion_date"),
        time_names=("finalized_time", "completion_time"),
    )
    if parsed_outreach is None and parsed_started is not None:
        # The source has one outreach start fact; mapping it to both model
        # fields preserves it without inventing a second timestamp.
        parsed_outreach = parsed_started

    _lock_tenant(user)
    allowed_sources = (source, "legacy_shop_analytics_bd")
    locked_task = None
    if task is not None:
        try:
            locked_task = OutreachTask.objects.select_for_update().get(
                pk=_pk(task), tenant_id=user.tenant_id
            )
        except OutreachTask.DoesNotExist as exc:
            raise ValidationError({"task": "Task does not exist in the actor tenant."}) from exc
        if locked_task.external_id not in (None, "", external_id) and locked_task.source in allowed_sources:
            raise ValidationError({"source_row": "Task external id does not match the source row."}, code="conflict")
        if locked_task.source not in allowed_sources:
            raise ValidationError({"source": "Task is owned by another source."}, code="conflict")
    else:
        external_candidates = list(
            OutreachTask.objects.select_for_update()
            .filter(
                tenant_id=user.tenant_id,
                source__in=allowed_sources,
                external_id=external_id,
            )
            .order_by("id")
        )
        if len(external_candidates) > 1:
            raise ValidationError(
                {"source": "Multiple current/legacy tasks share this source external id."},
                code="conflict",
            )
        locked_task = external_candidates[0] if external_candidates else None

        number_candidates = list(
            OutreachTask.objects.select_for_update()
            .filter(
                tenant_id=user.tenant_id,
                source__in=allowed_sources,
                task_no=task_no,
            )
            .order_by("id")
        )
        if len(number_candidates) > 1:
            raise ValidationError(
                {"task_no": "Multiple current/legacy tasks share this business number."},
                code="conflict",
            )
        by_number = number_candidates[0] if number_candidates else None
        if locked_task is not None and by_number is not None and by_number.pk != locked_task.pk:
            raise ValidationError(
                {"task_no": "Task number and source external id identify different tasks."},
                code="conflict",
            )
        if locked_task is None and by_number is not None:
            if (
                by_number.external_id not in (None, "", external_id)
                and by_number.source != "legacy_shop_analytics_bd"
            ):
                raise ValidationError(
                    {"task_no": "Existing source task number belongs to a different source external id."},
                    code="conflict",
                )
            locked_task = by_number
    foreign_task = OutreachTask.objects.filter(
        tenant_id=user.tenant_id,
    ).filter(Q(external_id=external_id) | Q(task_no=task_no)).exclude(
        source__in=allowed_sources
    ).first()
    if foreign_task is not None and (locked_task is None or foreign_task.pk != locked_task.pk):
        raise ValidationError({"source": "Task business key is owned by another source."}, code="conflict")
    if locked_task is None:
        number_collision = OutreachTask.objects.filter(
            tenant_id=user.tenant_id, task_no=task_no
        ).first()
        if number_collision is not None:
            if number_collision.source not in allowed_sources:
                raise ValidationError({"task_no": "Task number is owned by another source."}, code="conflict")
            locked_task = OutreachTask.objects.select_for_update().get(pk=number_collision.pk)

    created = locked_task is None

    def resolve_store(value, fallback=None):
        return _locked_store(user, _pk(value if value is not None else fallback))

    store_value = _import_task_field(data, row, "store", "store", "store_id", "shop")
    owner_value = _import_task_field(data, row, "owner", "owner", "owner_id")
    dispatcher_value = _import_task_field(data, row, "dispatcher", "dispatcher", "dispatcher_id")
    influencer_value = _import_task_field(data, row, "influencer", "influencer", "influencer_id")
    spu_value = _import_task_field(data, row, "spu", "spu", "spu_id")

    if locked_task is not None:
        if store_value is None:
            store_value = locked_task.store_id
        if owner_value is None:
            owner_value = locked_task.owner_id
        if dispatcher_value is None:
            dispatcher_value = locked_task.dispatcher_id
        if influencer_value is None:
            influencer_value = locked_task.influencer_id
        if spu_value is None:
            spu_value = locked_task.spu_id
    if store_value is None:
        raise ValidationError({"store": "Source task store is required."})
    if owner_value is None:
        raise ValidationError({"owner": "Source task owner is required."})
    if dispatcher_value is None:
        dispatcher_value = owner_value
    store = _locked_store(user, _pk(store_value))
    if store.status != "active":
        raise ValidationError({"store": "Only active stores can be assigned to imported tasks."})
    owner = _locked_user(user, _pk(owner_value), field="owner")
    dispatcher = _locked_user(user, _pk(dispatcher_value), field="dispatcher")
    _assert_active_bd_owner(user, owner)
    _assert_active_bd_owner(user, dispatcher)
    if personnel is not None:
        _validate_personnel_role(
            user=user,
            role="owner",
            entry=personnel.get("owner"),
            actual_user=owner,
        )
        _validate_personnel_role(
            user=user,
            role="dispatcher",
            entry=personnel.get("dispatcher"),
            actual_user=dispatcher,
            owner_user=owner,
            owner_entry=personnel.get("owner"),
        )
    influencer = (
        _tenant_influencer(user, _pk(influencer_value), for_update=False)
        if influencer_value is not None
        else None
    )
    spu = _locked_spu(user, _pk(spu_value)) if spu_value is not None else None

    task_name_value = _import_task_field(data, row, "task_name", "task_name", "name")
    product_id_value = _import_task_field(
        data, row, "external_product_id", "external_product_id", "product_id"
    )
    product_name_value = _import_task_field(
        data, row, "product_name_snapshot", "product_name_snapshot", "product_name", "product"
    )
    sku_prefix_value = _import_task_field(data, row, "sku_prefix", "sku_prefix")
    priority_value = _import_task_field(data, row, "priority", "priority")
    target_count_value = _import_task_field(data, row, "target_count", "target_count")
    notes_value = _import_task_field(data, row, "notes", "notes", "feedback", "note")

    def text_value(value, fallback=""):
        return str(value if value is not None else fallback).strip()

    if locked_task is not None:
        task_name = text_value(task_name_value, locked_task.task_name)
        product_id = text_value(product_id_value, locked_task.external_product_id)
        product_name = text_value(product_name_value, locked_task.product_name_snapshot)
        sku_prefix = text_value(sku_prefix_value, locked_task.sku_prefix)
        priority = text_value(priority_value, locked_task.priority) or "normal"
        target_count = locked_task.target_count if target_count_value in (None, "") else target_count_value
        notes = text_value(notes_value, locked_task.notes)
    else:
        task_name = text_value(task_name_value)
        product_id = text_value(product_id_value)
        product_name = text_value(product_name_value, task_name)
        sku_prefix = text_value(sku_prefix_value)
        priority = text_value(priority_value) or "normal"
        target_count = 0 if target_count_value in (None, "") else target_count_value
        notes = text_value(notes_value)
    try:
        target_count = int(target_count)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"target_count": "Source target_count must be a non-negative integer."}) from exc
    if target_count < 0:
        raise ValidationError({"target_count": "Source target_count must be non-negative."})

    if parsed_dispatch is None and locked_task is None:
        raise ValidationError({"dispatch_time": "Source dispatch time is required for a new task."})
    if parsed_dispatch is None and locked_task is not None:
        parsed_dispatch = locked_task.dispatch_time

    source_values = {
        "task_no": task_no,
        "task_name": task_name,
        "store": store,
        "owner": owner,
        "dispatcher": dispatcher,
        "influencer": influencer,
        "spu": spu,
        "external_product_id": product_id,
        "product_name_snapshot": product_name,
        "sku_prefix": sku_prefix,
        "priority": priority,
        "target_count": target_count,
        "source": source,
        "external_id": external_id,
        "notes": notes,
        "dispatch_time": parsed_dispatch,
    }
    if personnel is not None:
        source_values.update(
            {
                "source_owner_name_snapshot": personnel.get("owner", {}).get("name", ""),
                "source_dispatcher_name_snapshot": personnel.get("dispatcher", {}).get("name", ""),
            }
        )
    restored = False
    if created:
        locked_task = OutreachTask(
            tenant=user.tenant,
            status=OutreachTask.Status.PENDING,
            version=1,
            started_at=None,
            outreach_at=None,
            finalized_at=None,
            is_deleted=False,
            deleted_at=None,
            **source_values,
        )
        _save(locked_task)
        create_audit = {
            "source": source,
            "external_id": external_id,
            "task_no": task_no,
            "status": locked_task.status,
            "dispatch_time": str(locked_task.dispatch_time),
        }
        if personnel is not None:
            create_audit.update(_personnel_audit_data(personnel=personnel, task=locked_task))
        _audit(
            user,
            "feishu_import_task_create",
            "outreach_task",
            locked_task,
            after=create_audit,
        )
    else:
        if locked_task.is_deleted:
            locked_task = restore_outreach_task(
                user=user,
                task=locked_task,
                expected_version=locked_task.version,
                recompute_related=False,
            )
            restored = True
        before_facts = {
            field: getattr(locked_task, field)
            for field in (
                "task_no",
                "task_name",
                "store_id",
                "owner_id",
                "dispatcher_id",
                "influencer_id",
                "spu_id",
                "external_product_id",
                "product_name_snapshot",
                "sku_prefix",
                "priority",
                "target_count",
                "source",
                "external_id",
                "notes",
                "dispatch_time",
                "started_at",
                "outreach_at",
                "finalized_at",
                "source_owner_name_snapshot",
                "source_dispatcher_name_snapshot",
            )
        }
        desired_facts = {
            "task_no": task_no,
            "task_name": task_name,
            "store_id": store.pk,
            "owner_id": owner.pk,
            "dispatcher_id": dispatcher.pk,
            "influencer_id": influencer.pk if influencer is not None else None,
            "spu_id": spu.pk if spu is not None else None,
            "external_product_id": product_id,
            "product_name_snapshot": product_name,
            "sku_prefix": sku_prefix,
            "priority": priority,
            "target_count": target_count,
            "source": source,
            "external_id": external_id,
            "notes": notes,
            "dispatch_time": parsed_dispatch,
        }
        if personnel is not None:
            desired_facts.update(
                {
                    "source_owner_name_snapshot": personnel.get("owner", {}).get(
                        "name", locked_task.source_owner_name_snapshot
                    ),
                    "source_dispatcher_name_snapshot": personnel.get("dispatcher", {}).get(
                        "name", locked_task.source_dispatcher_name_snapshot
                    ),
                }
            )
        fact_changes = {
            field: value
            for field, value in desired_facts.items()
            if before_facts[field] != value
        }
    if created:
        fact_changes = {}
        before_facts = {
            "status": locked_task.status,
            "version": locked_task.version,
            "dispatch_time": locked_task.dispatch_time,
            "started_at": locked_task.started_at,
            "outreach_at": locked_task.outreach_at,
            "finalized_at": locked_task.finalized_at,
        }

    before_status = locked_task.status
    before_version = locked_task.version
    target_status = _import_task_status_target(before_status, requested_status)
    if target_status is None:
        raise ValidationError(
            {"status": "Source task status conflicts with an existing terminal or unknown state."},
            code="conflict",
        )

    # Explicit source state dates are facts. Unknown finalized_at remains the
    # existing value (null for a newly imported task), never ``timezone.now``.
    state_changes = {}
    if target_status != before_status:
        state_changes["status"] = target_status
    if parsed_started is not None and locked_task.started_at != parsed_started:
        state_changes["started_at"] = parsed_started
    if parsed_outreach is not None and locked_task.outreach_at != parsed_outreach:
        state_changes["outreach_at"] = parsed_outreach
    if parsed_finalized is not None and locked_task.finalized_at != parsed_finalized:
        state_changes["finalized_at"] = parsed_finalized

    chronology_fields = ("dispatch_time", "started_at", "outreach_at", "finalized_at")
    chronology_changes = {
        field: state_changes[field]
        for field in chronology_fields
        if field in state_changes
    }

    all_changes = {**fact_changes, **state_changes}
    if all_changes:
        all_changes.update(version=before_version + 1, updated_at=timezone.now())
        updated = QuerySet.update(
            OutreachTask.objects.filter(
                pk=locked_task.pk,
                tenant=user.tenant,
                version=before_version,
                status=before_status,
            ),
            **all_changes,
        )
        if updated != 1:
            raise ValidationError({"version": "Task was changed by another request."}, code="conflict")
        locked_task.refresh_from_db()
    if (fact_changes or chronology_changes) and not created:
        update_after = {
            **{
                key: str(getattr(locked_task, key))
                for key in before_facts
                if key in fact_changes or key in chronology_changes or key in {"source", "external_id"}
            },
            "source": source,
            "source_event_id": source_event_id,
            "version": locked_task.version,
        }
        if personnel is not None:
            update_after.update(_personnel_audit_data(personnel=personnel, task=locked_task))
        _audit(
            user,
            "feishu_import_task_update",
            "outreach_task",
            locked_task,
            before={
                key: str(value)
                for key, value in before_facts.items()
                if key in fact_changes or key in chronology_changes or key in {"source", "external_id"}
            },
            after=update_after,
        )

    status_log = _import_task_operation_log_exists(
        tenant_id=user.tenant_id,
        task_id=locked_task.pk,
        source=source,
        source_event_id=source_event_id,
    )
    if status_log is None:
        task_status_after = {
            "source": source,
            "source_event_id": source_event_id,
            "source_status": requested_status,
            "status": locked_task.status,
            "version": locked_task.version,
            "preserved": target_status != requested_status,
            "finalized_at": str(locked_task.finalized_at) if locked_task.finalized_at else None,
        }
        if personnel is not None:
            task_status_after.update(_personnel_audit_data(personnel=personnel, task=locked_task))
        write_operation_log(
            tenant=user.tenant,
            user=user,
            module="influencers",
            action="feishu_import_task_status",
            object_type="outreach_task",
            object_id=locked_task.pk,
            before_data={
                "status": before_status,
                "version": before_version,
            },
            after_data=task_status_after,
        )
    if return_metadata:
        changed_fields = []
        if created:
            changed_fields.append("created")
        if restored:
            changed_fields.append("restore")
        if fact_changes:
            changed_fields.append("fields")
        if target_status != before_status:
            changed_fields.append("status")
        if parsed_started is not None and parsed_started != before_facts.get("started_at"):
            changed_fields.append("started_at")
        if parsed_outreach is not None and parsed_outreach != before_facts.get("outreach_at"):
            changed_fields.append("outreach_at")
        if parsed_finalized is not None and parsed_finalized != before_facts.get("finalized_at"):
            changed_fields.append("finalized_at")
        if not created and parsed_dispatch is not None and parsed_dispatch != before_facts.get("dispatch_time"):
            changed_fields.append("dispatch_time")
        outcome = "created" if created else ("updated" if changed_fields else "noop")
        return {
            "task": locked_task,
            "created": created,
            "changed": bool(changed_fields),
            "changed_fields": changed_fields,
            "outcome": outcome,
        }
    return locked_task, created


def _import_sample_row_snapshot(
    *,
    user,
    tenant,
    source,
    source_row,
    request_key,
    request_hash,
    validated_data,
    item_payloads,
    status,
    sample_sent_at,
    shipped_at,
    actor,
    source_cost_currency="CNY",
    preserve_source_cost=False,
    ignore_current_sku_price=False,
    personnel_mapping=None,
    source_owner_name_snapshot=None,
    owner_resolution=None,
    personnel_policy=None,
    return_metadata=False,
):
    """Create/update one source-owned fulfillment before applying its status.

    This adapter is deliberately private to the fixed Feishu status importer.
    It exists so the deployment bundle can preserve source fulfillment numbers
    and dates while the public UI continues to use ``create_sample_fulfillment``
    and ``transition_sample_fulfillment``.
    """
    # These keyword arguments are retained only for the reviewed deployment
    # bundle's call shape.  The source-row adapter always owns source facts and
    # never delegates costing to the live ProductSKU catalog.
    if source != FEISHU_FULL_SAMPLE_STATUS_SOURCE:
        raise ValidationError({"source": "Unsupported fulfillment import source."})
    personnel = _normalise_personnel_mapping(
        personnel_mapping,
        owner_name=source_owner_name_snapshot,
        owner_resolution=owner_resolution,
        personnel_policy=personnel_policy,
        roles=("owner",),
    )
    _require_personnel_roles(personnel, ("owner",))
    if tenant is None:
        tenant = getattr(user, "tenant", None)
    if tenant is None or getattr(tenant, "pk", None) != user.tenant_id:
        raise ValidationError({"tenant": "Import tenant does not match the actor tenant."})
    if actor is not None:
        if getattr(actor, "tenant_id", None) != user.tenant_id:
            raise ValidationError({"actor": "Import actor must belong to the actor tenant."})
        if actor.pk != user.pk:
            raise ValidationError({"actor": "The import actor and user must match."}, code="conflict")
    else:
        actor = user

    desired_status = _import_source_status(status)
    source_sample_sent_at = _source_datetime(sample_sent_at, field="sample_sent_at")
    source_shipped_at = _source_datetime(shipped_at, field="shipped_at")
    if source_sample_sent_at is None:
        raise ValidationError({"sample_sent_at": "Source sample date is required."})
    source_row = source_row if isinstance(source_row, Mapping) else {}
    row_source = source_row.get("source")
    if row_source not in (None, "", "飞书") and row_source != source:
        raise ValidationError({"source": "Source row source does not match the import source."})
    source_external_id = _import_payload_value(
        source_row,
        "external_id",
        "sample_external_id",
        "id",
        "record_id",
        "source_row_key",
    )
    if source_external_id in (None, ""):
        source_external_id = _import_payload_value(
            validated_data,
            "external_id",
            "fulfillment_no",
        )
    source_external_id = str(source_external_id or "").strip()
    if not source_external_id:
        raise ValidationError({"source_row": "Source fulfillment id is required."})
    if len(source_external_id) > 160:
        raise ValidationError({"source_row": "Source fulfillment id must be at most 160 characters."})

    if source_row.get("status") not in (None, ""):
        source_row_status = _import_source_status(source_row.get("status"))
        if source_row_status != desired_status:
            raise ValidationError(
                {"status": "Source row status does not match the requested status."},
                code="conflict",
            )
    if request_key in (None, ""):
        request_key = f"{source}:sample:{source_external_id}"
    request_key = str(request_key).strip()
    if not request_key or len(request_key) > 128:
        raise ValidationError({"request_key": "Import request key must be 1-128 characters."})
    request_hash = str(request_hash or "").strip() or _payload_hash(
        {"source": source, "source_row": source_row}
    )
    if len(request_hash) > 64:
        raise ValidationError({"request_hash": "Import request hash must be at most 64 characters."})

    data = dict(validated_data or {})
    fulfillment_no = str(data.get("fulfillment_no") or source_external_id).strip()
    if not fulfillment_no or len(fulfillment_no) > 80:
        raise ValidationError({"fulfillment_no": "Import fulfillment number must be 1-80 characters."})
    data.update(
        {
            "fulfillment_no": fulfillment_no,
            "request_key": request_key,
            "request_hash": request_hash,
            "source": source,
            "external_id": source_external_id,
        }
    )
    if personnel is not None and "owner" in personnel:
        data["source_owner_name_snapshot"] = personnel["owner"]["name"]
    item_payloads = list(item_payloads or [])

    _lock_tenant(user)
    allowed_existing_sources = (source, "legacy_shop_analytics_bd")
    external_candidates = list(
        SampleFulfillment.objects.select_for_update()
        .filter(
            tenant_id=user.tenant_id,
            source__in=allowed_existing_sources,
            external_id=source_external_id,
        )
        .order_by("id")
    )
    if len(external_candidates) > 1:
        raise ValidationError(
            {"source": "Multiple current/legacy fulfillments share this source external id."},
            code="conflict",
        )
    fulfillment = external_candidates[0] if external_candidates else None
    if fulfillment is not None and fulfillment.fulfillment_no != fulfillment_no:
        raise ValidationError(
            {"fulfillment_no": "Existing source fulfillment number does not match its external id."},
            code="conflict",
        )
    if fulfillment is None:
        number_candidates = list(
            SampleFulfillment.objects.select_for_update()
            .filter(
                tenant_id=user.tenant_id,
                source__in=allowed_existing_sources,
                fulfillment_no=fulfillment_no,
            )
            .order_by("id")
        )
        if len(number_candidates) > 1:
            raise ValidationError(
                {"fulfillment_no": "Multiple current/legacy fulfillments share this business number."},
                code="conflict",
            )
        fulfillment = number_candidates[0] if number_candidates else None
        if (
            fulfillment is not None
            and fulfillment.external_id != source_external_id
            and fulfillment.source != "legacy_shop_analytics_bd"
        ):
            raise ValidationError(
                {"fulfillment_no": "Existing fulfillment number belongs to a different source external id."},
                code="conflict",
            )
    foreign_source = SampleFulfillment.objects.filter(
        tenant_id=user.tenant_id,
        external_id=source_external_id,
    ).exclude(source__in=allowed_existing_sources).first()
    if foreign_source is not None:
        raise ValidationError(
            {"source": "Source fulfillment id is owned by another source."},
            code="conflict",
        )

    created = False
    restored = False
    before_status = None
    before_version = None
    before_source_fields = {}
    source_fields_changed = False
    if fulfillment is None:
        # The regular creation service supplies all relationship and item
        # validation, but leaves the workflow in its required initial pending
        # state. The source status is applied immediately below through this
        # adapter's audited path.
        # Do not let the generic create service infer a shipment timestamp or
        # emit its order-number transition with ``timezone.now()``.  The source
        # chronology and audited source transition are applied below.
        create_data = dict(data)
        create_data["sample_order_no"] = ""
        # Specialized source personnel fields are applied by this adapter
        # after the ordinary creation service has validated relationships.
        create_data.pop("source_owner_name_snapshot", None)
        fulfillment, created = create_sample_fulfillment(
            user=user,
            request_key=request_key,
            validated_data=create_data,
            # The generic create path prices against the live catalog.  Source
            # rows are historical facts, so create with no items and replace
            # them through the source-only adapter immediately afterward.
            item_payloads=[],
        )
        # ``create_sample_fulfillment`` computes its own request hash and the
        # source order number was intentionally blanked to avoid an inferred
        # shipment transition.  Restore those source facts with a validated
        # tenant-scoped update before the source-only replacements.
        source_create_changes = {
            "request_key": request_key,
            "request_hash": request_hash,
            "sample_order_no": str(data.get("sample_order_no") or "").strip(),
            # The generic linked-sample service prefers the task's product
            # name snapshot.  This source adapter instead owns the explicit
            # sample-row snapshot and must not discard it when the task export
            # has only a product id.
            "product_name_snapshot": str(
                data.get("product_name_snapshot") or ""
            ).strip(),
        }
        QuerySet.update(
            SampleFulfillment.objects.filter(pk=fulfillment.pk, tenant_id=user.tenant_id),
            **source_create_changes,
        )
        fulfillment.refresh_from_db()
        if personnel is not None and "owner" in personnel:
            _validate_personnel_role(
                user=user,
                role="owner",
                entry=personnel["owner"],
                actual_user=fulfillment.owner,
            )
            QuerySet.update(
                SampleFulfillment.objects.filter(
                    pk=fulfillment.pk,
                    tenant_id=user.tenant_id,
                ),
                source_owner_name_snapshot=personnel["owner"]["name"],
            )
            fulfillment.refresh_from_db()
    else:
        before_status = fulfillment.status
        before_version = fulfillment.version
        before_source_fields = {
            field: getattr(fulfillment, field)
            for field in (
                "fulfillment_no",
                "request_key",
                "request_hash",
                "source",
                "external_id",
                "sample_order_no",
                "link_type",
                "notes",
                "owner_id",
                "influencer_id",
                "store_id",
                "external_product_id",
                "product_name_snapshot",
                "source_owner_name_snapshot",
            )
        }
        if fulfillment.is_deleted:
            # A full-source reconciliation may legitimately see a row again
            # after the previous batch soft-deleted it.  Restore only rows
            # already proven to belong to this controlled source (or the
            # explicitly approved legacy source); foreign-source rows were
            # rejected above and can never be revived by this adapter.
            fulfillment = restore_sample_fulfillment(
                user=user,
                fulfillment=fulfillment,
                expected_version=fulfillment.version,
                recompute_related=False,
            )
            restored = True
        if (
            fulfillment.request_key != request_key
            and SampleFulfillment.objects.filter(
                tenant_id=user.tenant_id,
                request_key=request_key,
            ).exclude(pk=fulfillment.pk).exists()
        ):
            raise ValidationError({"request_key": "Import request key is already used by another fulfillment."}, code="conflict")

        # Validate the complete incoming relationship set with the persisted
        # workflow state held constant, then save only source-owned facts.
        before = {
            field: getattr(fulfillment, field)
            for field in (
                "fulfillment_no",
                "request_key",
                "request_hash",
                "outreach_task",
                "outreach_target",
                "influencer",
                "store",
                "product_name_snapshot",
                "source_owner_name_snapshot",
                "external_product_id",
                "sample_order_no",
                "link_type",
                "quick_tags",
                "owner",
                "notes",
                "source",
                "external_id",
                "sample_sent_at",
            )
        }
        for field in (
            "fulfillment_no",
            "request_key",
            "request_hash",
            "outreach_task",
            "outreach_target",
            "influencer",
            "store",
            "product_name_snapshot",
            "source_owner_name_snapshot",
            "external_product_id",
            "sample_order_no",
            "link_type",
            "quick_tags",
            "owner",
            "notes",
            "source",
            "external_id",
        ):
            if field in data:
                setattr(fulfillment, field, data[field])
        # Validate the resolved owner from the incoming source row, not the
        # persisted owner.  A legitimate Feishu fallback can intentionally
        # migrate an older same-source row to the configured ``liyejun`` user.
        if personnel is not None and "owner" in personnel:
            _validate_personnel_role(
                user=user,
                role="owner",
                entry=personnel["owner"],
                actual_user=fulfillment.owner,
            )
        fulfillment.full_clean()
        after = {
            field: getattr(fulfillment, field)
            for field in before
        }
        source_fields_changed = before != after
        if source_fields_changed:
            # State-machine ``save`` protects source snapshots (and other
            # workflow fields) from ordinary ORM writes.  This adapter is the
            # narrow, audited exception: after ``full_clean`` above, persist
            # only the source-owned allow-list under a tenant/version/state CAS.
            source_update = {}
            source_fk_fields = {
                "outreach_task",
                "outreach_target",
                "influencer",
                "store",
                "owner",
            }
            for field in (
                "fulfillment_no",
                "request_key",
                "request_hash",
                "outreach_task",
                "outreach_target",
                "influencer",
                "store",
                "product_name_snapshot",
                "external_product_id",
                "sample_order_no",
                "link_type",
                "quick_tags",
                "owner",
                "source_owner_name_snapshot",
                "notes",
                "source",
                "external_id",
            ):
                if field in source_fk_fields:
                    source_update[f"{field}_id"] = getattr(fulfillment, f"{field}_id")
                else:
                    source_update[field] = getattr(fulfillment, field)
            source_update["updated_at"] = timezone.now()
            updated = QuerySet.update(
                SampleFulfillment.objects.filter(
                    pk=fulfillment.pk,
                    tenant_id=user.tenant_id,
                    version=fulfillment.version,
                    status=fulfillment.status,
                    is_deleted=False,
                ),
                **source_update,
            )
            if updated != 1:
                raise ValidationError(
                    {"version": "Fulfillment was changed by another request."},
                    code="conflict",
                )
            fulfillment.refresh_from_db()
            sample_update_after = {key: str(value) for key, value in after.items()}
            if personnel is not None:
                sample_update_after.update(
                    _personnel_audit_data(personnel=personnel, fulfillment=fulfillment)
                )
            _audit(
                user,
                "feishu_import_sample_update",
                "sample_fulfillment",
                fulfillment,
                before={key: str(value) for key, value in before.items()},
                after=sample_update_after,
            )

    before_dates, _ = _apply_source_chronology(
        user=user,
        fulfillment=fulfillment,
        desired_status=desired_status,
        sample_sent_at=source_sample_sent_at,
        shipped_at=source_shipped_at,
    )
    before_items = _source_item_signature(fulfillment)
    _replace_sample_items_from_source(
        user=user,
        fulfillment=fulfillment,
        item_payloads=item_payloads,
        # The fixed importer contract is CNY/source-owned regardless of row
        # payload hints.  The helper enforces both values again.
        currency=source_cost_currency,
    )
    after_dates = {
        field: getattr(fulfillment, field)
        for field in ("sample_sent_at", "shipped_at", "video_deadline_at")
    }
    after_items = _source_item_signature(fulfillment)
    source_facts_changed = (
        source_fields_changed
        or before_dates != after_dates
        or before_items != after_items
    )
    if before_dates != after_dates or before_items != after_items:
        _audit(
            user,
            "feishu_import_sample_facts",
            "sample_fulfillment",
            fulfillment,
            before={
                "dates": {key: str(value) for key, value in before_dates.items()},
                "item_count": len(before_items),
            },
            after={
                "dates": {key: str(value) for key, value in after_dates.items()},
                "item_count": len(after_items),
                "calculated_cost": str(fulfillment.calculated_cost)
                if fulfillment.calculated_cost is not None
                else None,
            },
        )

    # Match the public update service's optimistic-concurrency contract: a
    # source fact or item change advances the fulfillment version exactly once
    # before the independently audited status snapshot runs. A byte-for-byte
    # replay performs no write and leaves the version untouched.
    if not created and source_facts_changed:
        expected_version = fulfillment.version
        updated = QuerySet.update(
            SampleFulfillment.objects.filter(
                pk=fulfillment.pk,
                tenant_id=user.tenant_id,
                version=expected_version,
                status=fulfillment.status,
                is_deleted=False,
            ),
            version=expected_version + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise ValidationError(
                {"version": "Fulfillment was changed by another request."},
                code="conflict",
            )
        fulfillment.refresh_from_db()

    # A source row can legitimately be observed in more than one status over
    # time.  Keep the event identity stable per row *and status* so a later
    # shipped -> published snapshot emits one new event instead of colliding
    # with the earlier status event.  The adapter owns this key; callers do not
    # need to pre-compose it.
    source_status_event_id = f"{source_external_id}:{desired_status}"
    if len(source_status_event_id) > 160:
        raise ValidationError({"event": "Source status event id must be at most 160 characters."})
    event_payload = dict(source_row)
    event_payload.update(
        {
            "source": source,
            "source_event_id": source_status_event_id,
            "source_status": desired_status,
            "tenant": tenant,
            "fulfillment": fulfillment,
            "source_observed_at": source_shipped_at,
        }
    )
    personnel_audit = (
        _personnel_audit_data(personnel=personnel, fulfillment=fulfillment)
        if personnel is not None
        else {}
    )
    event_payload.update(personnel_audit)
    status_operation_payload = {
        "source": source,
        "source_event_id": source_status_event_id,
        "source_status": desired_status,
        "tenant": tenant,
        "fulfillment": fulfillment,
        "actor": actor,
    }
    status_operation_payload.update(personnel_audit)
    import_sample_fulfillment_snapshot(
        desired_status,
        event_payload,
        status_operation_payload,
        user=user,
        fulfillment=fulfillment,
        source=source,
        source_owner_name_snapshot=(
            personnel["owner"]["name"] if personnel is not None and "owner" in personnel else None
        ),
        owner_resolution=(
            personnel["owner"]["resolution"] if personnel is not None and "owner" in personnel else None
        ),
        personnel_policy=personnel["policy"] if personnel is not None else None,
    )
    fulfillment.refresh_from_db()
    after_status = fulfillment.status
    changed_fields = []
    if created:
        changed_fields.append("created")
    if restored:
        changed_fields.append("restore")
    if before_status is not None and before_status != after_status:
        changed_fields.append("status")
    if before_dates != after_dates:
        changed_fields.append("dates")
    if before_items != after_items:
        changed_fields.append("items")
    if before_source_fields and any(
        before_source_fields[field] != getattr(fulfillment, field)
        for field in before_source_fields
    ):
        changed_fields.append("fields")
    if created:
        # ``create_sample_fulfillment`` must create its attribution row before
        # the source-only item/status adapter runs, but that generic service
        # necessarily sees its initial ``now``/pending/empty-item facts.  The
        # source import owns this newly-created snapshot and repairs it before
        # the outer transaction can commit.  Existing attribution snapshots
        # are immutable historical facts and are deliberately never changed.
        snapshot = (
            BdSampleAttributionSnapshot.objects.select_for_update()
            .filter(tenant_id=user.tenant_id, fulfillment_id=fulfillment.pk)
            .first()
        )
        if snapshot is None:
            raise ValidationError(
                {"attribution": "New source fulfillment is missing its attribution snapshot."},
                code="conflict",
            )
        first_item = (
            SampleItem.objects.filter(
                tenant_id=user.tenant_id,
                fulfillment_id=fulfillment.pk,
            )
            .order_by("id")
            .first()
        )
        site = str(
            (first_item.site_code if first_item is not None else "")
            or getattr(fulfillment.store, "country_code", "")
            or ""
        ).strip()
        snapshot_before = {
            "sampled_at": snapshot.sampled_at,
            "shipped_at": snapshot.shipped_at,
            "sample_status": snapshot.sample_status,
            "cost_amount": snapshot.cost_amount,
            "currency": snapshot.currency,
            "site": snapshot.site,
            "sku_id": snapshot.sku_id,
            "source": snapshot.source,
        }
        snapshot_changes = {
            "owner_id": fulfillment.owner_id,
            "influencer_id": fulfillment.influencer_id,
            "store_id": fulfillment.store_id,
            "creator_username": getattr(fulfillment.influencer, "handle", "") or "",
            "shop_abbr": getattr(fulfillment.store, "code", "") or "",
            "site": site,
            "product_id": fulfillment.external_product_id or "",
            "product_name": fulfillment.product_name_snapshot or "",
            "sku_id": (first_item.requested_sku if first_item is not None else "") or "",
            "sampled_at": fulfillment.sample_sent_at,
            "shipped_at": fulfillment.shipped_at,
            "sample_status": fulfillment.status,
            "cost_amount": fulfillment.calculated_cost,
            "currency": "CNY",
            "pricing_status": "pending",
            "source": source,
            "legacy_inferred": False,
            "updated_at": timezone.now(),
        }
        QuerySet.update(
            BdSampleAttributionSnapshot.objects.filter(
                pk=snapshot.pk,
                tenant_id=user.tenant_id,
                fulfillment_id=fulfillment.pk,
            ),
            **snapshot_changes,
        )
        snapshot.refresh_from_db()
        _audit(
            user,
            "feishu_import_attribution_snapshot",
            "bd_sample_attribution_snapshot",
            snapshot,
            before={key: str(value) for key, value in snapshot_before.items()},
            after={
                "sampled_at": str(snapshot.sampled_at),
                "shipped_at": str(snapshot.shipped_at) if snapshot.shipped_at else None,
                "sample_status": snapshot.sample_status,
                "cost_amount": str(snapshot.cost_amount) if snapshot.cost_amount is not None else None,
                "currency": snapshot.currency,
                "site": snapshot.site,
                "sku_id": snapshot.sku_id,
                "source": snapshot.source,
            },
        )
    if return_metadata:
        outcome = "created" if created else ("updated" if changed_fields else "noop")
        return {
            "fulfillment": fulfillment,
            "created": created,
            "changed": bool(changed_fields),
            "changed_fields": changed_fields,
            "outcome": outcome,
        }
    return fulfillment, created


@transaction.atomic
def import_sample_fulfillment_snapshot(
    status=None,
    event=None,
    operation_log=None,
    *,
    user=None,
    tenant=None,
    fulfillment=None,
    source=FEISHU_FULL_SAMPLE_STATUS_SOURCE,
    source_row=None,
    request_key=None,
    request_hash=None,
    validated_data=None,
    item_payloads=None,
    sample_sent_at=None,
    shipped_at=None,
    actor=None,
    source_cost_currency="CNY",
    preserve_source_cost=False,
    ignore_current_sku_price=False,
    personnel_mapping=None,
    source_owner_name_snapshot=None,
    owner_resolution=None,
    personnel_policy=None,
    return_metadata=False,
):
    """Apply one Feishu sample-status snapshot through an audited import path.

    The first three positional arguments intentionally match the deployment
    gate's compatibility contract: ``status, event, operation_log``.  The
    normal caller should also pass the explicit tenant actor and fulfillment:

    ``import_sample_fulfillment_snapshot(status, event, operation_log,
    user=actor, fulfillment=sample)``.

    Only the fixed ``feishu_full_20260908`` source and three source statuses
    are accepted.  The source event key is persisted on
    ``FulfillmentStatusEvent`` and is unique per tenant/source, so a replay is
    a no-op.  Existing published/terminal or otherwise more advanced workflow
    states are never downgraded or overwritten.
    """
    if validated_data is not None or source_row is not None:
        if user is None:
            user = actor
        if user is None:
            raise ValidationError({"actor": "An explicit tenant import actor is required."})
        return _import_sample_row_snapshot(
            user=user,
            tenant=tenant,
            source=source,
            source_row=source_row,
            request_key=request_key,
            request_hash=request_hash,
            validated_data=validated_data,
            item_payloads=item_payloads,
            status=status,
            sample_sent_at=sample_sent_at,
            shipped_at=shipped_at,
            actor=actor,
            source_cost_currency=source_cost_currency,
            preserve_source_cost=preserve_source_cost,
            ignore_current_sku_price=ignore_current_sku_price,
            personnel_mapping=personnel_mapping,
            source_owner_name_snapshot=source_owner_name_snapshot,
            owner_resolution=owner_resolution,
            personnel_policy=personnel_policy,
            return_metadata=return_metadata,
        )
    if source != FEISHU_FULL_SAMPLE_STATUS_SOURCE:
        raise ValidationError({"source": "Unsupported fulfillment status import source."})
    personnel = _normalise_personnel_mapping(
        personnel_mapping,
        owner_name=source_owner_name_snapshot,
        owner_resolution=owner_resolution,
        personnel_policy=personnel_policy,
        roles=("owner",),
    )
    requested_status = _import_source_status(status)

    event_source = _import_payload_value(event, "source")
    log_source = _import_payload_value(operation_log, "source")
    for payload_source in (event_source, log_source):
        if payload_source not in (None, "") and payload_source != source:
            raise ValidationError({"source": "Source snapshot source does not match the import source."})

    event_status = _import_payload_value(event, "source_status", "status")
    if event_status not in (None, "") and _import_source_status(event_status) != requested_status:
        raise ValidationError(
            {"status": "Source event status does not match the requested status."},
            code="conflict",
        )
    log_status = _import_payload_value(operation_log, "source_status", "status")
    if log_status not in (None, "") and _import_source_status(log_status) != requested_status:
        raise ValidationError(
            {"status": "Operation log status does not match the requested status."},
            code="conflict",
        )

    event_tenant = _import_payload_value(event, "tenant", "tenant_id")
    log_tenant = _import_payload_value(operation_log, "tenant", "tenant_id")
    event_fulfillment = _import_payload_value(event, "fulfillment", "fulfillment_id")
    log_fulfillment = _import_payload_value(operation_log, "fulfillment", "fulfillment_id")
    if fulfillment is None:
        fulfillment = event_fulfillment or log_fulfillment
    event_user = _import_payload_value(event, "actor", "user")
    log_user = _import_payload_value(operation_log, "actor", "user")
    if user is None:
        user = event_user or log_user

    # A source import must be attributed to an actual tenant user.  We permit
    # the context payload to carry a user primary key only when the fulfillment
    # or tenant context lets us resolve that key without guessing.
    tenant_hint = event_tenant or log_tenant
    fulfillment_hint_tenant = getattr(fulfillment, "tenant_id", None)
    tenant_id = _pk(tenant_hint) if tenant_hint is not None else fulfillment_hint_tenant
    if user is None and tenant_id is not None:
        user_id = _pk(event_user or log_user)
        if user_id is not None:
            user = get_user_model().objects.filter(pk=user_id, tenant_id=tenant_id).first()
    if user is None or getattr(user, "tenant_id", None) is None:
        raise ValidationError({"actor": "An explicit tenant import actor is required."})
    tenant_id = user.tenant_id
    for payload_tenant in (event_tenant, log_tenant):
        if payload_tenant is not None and _pk(payload_tenant) != tenant_id:
            raise ValidationError({"tenant": "Source snapshot tenant does not match the actor tenant."})

    if fulfillment is None:
        raise ValidationError({"fulfillment": "A fulfillment is required for source status import."})
    fulfillment_id = _pk(fulfillment)
    if getattr(fulfillment, "tenant_id", tenant_id) not in (None, tenant_id):
        raise ValidationError({"fulfillment": "Fulfillment must belong to the actor tenant."})
    for payload_fulfillment in (event_fulfillment, log_fulfillment):
        if payload_fulfillment is not None and _pk(payload_fulfillment) != fulfillment_id:
            raise ValidationError(
                {"fulfillment": "Source event fulfillment does not match the requested fulfillment."},
                code="conflict",
            )

    source_event_id = _import_source_event_id(event, operation_log)
    if not source_event_id:
        raise ValidationError({"event": "A stable source event id is required."})
    if len(source_event_id) > 160:
        raise ValidationError({"event": "Source event id must be at most 160 characters."})

    _lock_tenant(user)
    try:
        locked_fulfillment = SampleFulfillment.objects.select_for_update().get(
            pk=fulfillment_id,
            tenant_id=tenant_id,
        )
    except SampleFulfillment.DoesNotExist as exc:
        raise ValidationError(
            {"fulfillment": "Fulfillment does not exist in the actor tenant."}
        ) from exc
    before_shipped_at = locked_fulfillment.shipped_at
    if locked_fulfillment.source != source:
        raise ValidationError(
            {"source": "Fulfillment source does not match the source snapshot."},
            code="conflict",
        )
    if locked_fulfillment.is_deleted:
        raise ValidationError({"fulfillment": "Deleted fulfillments cannot receive source snapshots."})

    personnel_changed = False
    if personnel is not None and "owner" in personnel:
        _validate_personnel_role(
            user=user,
            role="owner",
            entry=personnel["owner"],
            actual_user=locked_fulfillment.owner,
        )
        desired_owner_name = personnel["owner"]["name"]
        if locked_fulfillment.source_owner_name_snapshot != desired_owner_name:
            before_personnel_name = locked_fulfillment.source_owner_name_snapshot
            expected_personnel_version = locked_fulfillment.version
            updated = QuerySet.update(
                SampleFulfillment.objects.filter(
                    pk=locked_fulfillment.pk,
                    tenant_id=tenant_id,
                    version=expected_personnel_version,
                    is_deleted=False,
                ),
                source_owner_name_snapshot=desired_owner_name,
                version=expected_personnel_version + 1,
                updated_at=timezone.now(),
            )
            if updated != 1:
                raise ValidationError({"version": "Fulfillment was changed by another request."}, code="conflict")
            locked_fulfillment.refresh_from_db()
            personnel_changed = True
            _audit(
                user,
                "feishu_import_sample_personnel",
                "sample_fulfillment",
                locked_fulfillment,
                before={"source_owner_name_snapshot": before_personnel_name},
                after=_personnel_audit_data(personnel=personnel, fulfillment=locked_fulfillment),
            )

    personnel_audit = (
        _personnel_audit_data(personnel=personnel, fulfillment=locked_fulfillment)
        if personnel is not None
        else {}
    )

    # The tenant lock serializes imports while this source-key lookup also
    # catches accidental reuse of a source row for another fulfillment.
    existing_event = FulfillmentStatusEvent.objects.select_for_update().filter(
        tenant_id=tenant_id,
        source=source,
        source_event_id=source_event_id,
    ).first()
    if existing_event is not None:
        current_rank = _FEISHU_IMPORT_STATUS_ORDER.get(locked_fulfillment.status)
        historical_rank = _FEISHU_IMPORT_STATUS_ORDER.get(existing_event.to_status)
        historical_target = _import_status_target(existing_event.from_status, requested_status)
        if locked_fulfillment.status in _FEISHU_IMPORT_PRESERVED_STATUSES:
            current_not_behind_event = True
        elif existing_event.to_status in _FEISHU_IMPORT_PRESERVED_STATUSES:
            current_not_behind_event = locked_fulfillment.status == existing_event.to_status
        else:
            current_not_behind_event = (
                current_rank is not None
                and historical_rank is not None
                and current_rank >= historical_rank
            )
        # The event row is immutable evidence of the state observed when this
        # source snapshot first arrived.  A later snapshot may have advanced
        # the fulfillment, so recomputing the current transition must not turn
        # a replay of the older event into a conflict (for example shipped ->
        # published, then replay shipped).  It is still a conflict when the
        # event points at another fulfillment/status or when replay would
        # require regressing the current state.
        if (
            existing_event.fulfillment_id != locked_fulfillment.pk
            or existing_event.source_status != requested_status
            or not current_not_behind_event
            or historical_target is None
            or existing_event.to_status != historical_target
        ):
            raise ValidationError(
                {"event": "Source event id was already imported with a different fulfillment or status."},
                code="conflict",
            )
        # A manually repaired audit log should not cause the replay to emit a
        # second log; create the missing one only if the event transaction was
        # previously committed without its audit row.
        if _import_operation_log_exists(
            tenant_id=tenant_id,
            fulfillment_id=locked_fulfillment.pk,
            source=source,
            source_event_id=source_event_id,
        ) is None:
            write_operation_log(
                tenant=user.tenant,
                user=user,
                module="influencers",
                action="sample_status_import",
                object_type="sample_fulfillment",
                object_id=locked_fulfillment.pk,
                before_data={
                    "status": existing_event.from_status,
                    "version": max(locked_fulfillment.version - 1, 1),
                },
                after_data={
                    "source": source,
                    "source_event_id": source_event_id,
                    "source_status": requested_status,
                    "status": existing_event.to_status,
                    "version": locked_fulfillment.version,
                    "event_id": existing_event.pk,
                    "preserved": existing_event.to_status != requested_status,
                    **personnel_audit,
                },
            )
        if return_metadata:
            return {
                "fulfillment": locked_fulfillment,
                "created": False,
                "changed": personnel_changed,
                "changed_fields": ["source_owner_name_snapshot"] if personnel_changed else [],
                "outcome": "updated" if personnel_changed else "noop",
            }
        return locked_fulfillment

    before_status = locked_fulfillment.status
    before_version = locked_fulfillment.version
    target_status = _import_status_target(before_status, requested_status)
    if target_status is None:
        raise ValidationError(
            {"status": "Terminal or creator-managed fulfillment states cannot be changed by this import."},
            code="conflict",
        )
    should_update = target_status != before_status
    if should_update:
        changes = {
            "status": target_status,
            "version": before_version + 1,
            "updated_at": timezone.now(),
        }
        # A source-observed timestamp is accepted only when explicitly supplied
        # by the source row.  Never invent a shipment time from import time.
        observed_at = _import_source_observed_at(event)
        if (
            target_status in {
                SampleFulfillment.Status.SHIPPED,
                SampleFulfillment.Status.PUBLISHED,
            }
            and locked_fulfillment.shipped_at is None
            and observed_at is not None
        ):
            changes["shipped_at"] = observed_at
        _cas_state_update(
            locked_fulfillment,
            tenant=user.tenant,
            expected_status=before_status,
            expected_version=before_version,
            **changes,
        )

    status_event = FulfillmentStatusEvent.objects.create(
        tenant=user.tenant,
        fulfillment=locked_fulfillment,
        from_status=before_status,
        to_status=target_status,
        actor=user,
        reason=f"source_snapshot_import:{source_event_id}"[:240],
        source=source,
        source_event_id=source_event_id,
        source_status=requested_status,
    )
    after_status = locked_fulfillment.status
    write_operation_log(
        tenant=user.tenant,
        user=user,
        module="influencers",
        action="sample_status_import",
        object_type="sample_fulfillment",
        object_id=locked_fulfillment.pk,
        before_data={"status": before_status, "version": before_version},
        after_data={
            "source": source,
            "source_event_id": source_event_id,
            "source_status": requested_status,
            "status": after_status,
            "version": locked_fulfillment.version,
            "event_id": status_event.pk,
            "preserved": not should_update,
            **personnel_audit,
        },
    )
    if return_metadata:
        changed_fields = ["status"] if should_update else []
        if personnel_changed:
            changed_fields.append("source_owner_name_snapshot")
        if before_shipped_at != locked_fulfillment.shipped_at:
            changed_fields.append("shipped_at")
        return {
            "fulfillment": locked_fulfillment,
            "created": False,
            "changed": bool(changed_fields),
            "changed_fields": changed_fields,
            "outcome": "updated" if changed_fields else "noop",
        }
    return locked_fulfillment


@transaction.atomic
def transition_sample_fulfillment(
    *, user, fulfillment, status, expected_version, reason="", confirm_terminal=False
):
    _lock_tenant(user)
    fulfillment = _locked_sample_fulfillment(user=user, fulfillment=fulfillment)
    if fulfillment.is_deleted:
        raise ValidationError({"fulfillment": "Deleted sample fulfillments cannot transition."})
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
            SampleFulfillment.Status.COMPLETED,
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
    """Edit sample facts and atomically rebuild any requested SKU costs."""
    _lock_tenant(user)
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
    if "source_owner_name_snapshot" in data:
        raise ValidationError(
            {"source_personnel": "Source personnel snapshots are writable only by the Feishu import adapter."},
            code="forbidden",
        )
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
        fulfillment = _recalculate_sample_costs(
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
def soft_delete_sample_fulfillment(
    *, user, fulfillment, expected_version, recompute_related=True
):
    _lock_tenant(user)
    fulfillment = _locked_sample_fulfillment(user=user, fulfillment=fulfillment)
    if fulfillment.is_deleted:
        raise ValidationError({"fulfillment": "Deleted sample fulfillments cannot be deleted again."})
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
    if recompute_related:
        _recompute_related_task(user=user, fulfillment=fulfillment)
    return fulfillment


@transaction.atomic
def restore_sample_fulfillment(
    *, user, fulfillment, expected_version, recompute_related=True
):
    _lock_tenant(user)
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
    if task is not None and recompute_related:
        recompute_outreach_task_completion(user=user, task=task)
    return fulfillment


@transaction.atomic
def soft_delete_import_source(
    *,
    user,
    tenant,
    source,
    batch,
    task_external_ids,
    sample_external_ids,
    reason="",
    manifest_digest=None,
):
    """Soft-delete missing rows owned by the controlled full-import source.

    This is intentionally source-scoped and batch-scoped. It never executes
    a broad delete and never removes targets, video results, attribution rows,
    status events, or source records. The existing audited soft-delete
    services perform one state/version write per active row; the aggregate log
    below makes an empty replay auditable without emitting duplicate work.
    """
    if source != FEISHU_FULL_SAMPLE_STATUS_SOURCE:
        raise ValidationError({"source": "Unsupported import cleanup source."})
    if tenant is None or getattr(tenant, "pk", None) != getattr(user, "tenant_id", None):
        raise ValidationError({"tenant": "Import cleanup tenant does not match the actor tenant."})
    if getattr(user, "tenant_id", None) is None:
        raise ValidationError({"actor": "An explicit tenant cleanup actor is required."})
    # A destructive reconciliation must never trust an in-memory status or
    # source value.  Require a real persisted model instance, then lock and
    # re-read the batch using the actor tenant/source and completed status.
    # This also rejects SimpleNamespace/unsaved objects and empty ids before a
    # source-wide query can run.
    if not isinstance(batch, ImportBatch) or batch.pk in (None, ""):
        raise ValidationError({"batch": "A persisted completed import batch is required for cleanup."})
    batch_id = _pk(batch)

    def normalize_ids(values, field):
        if values is None or isinstance(values, (str, bytes, Mapping)):
            raise ValidationError({field: "Cleanup source ids must be a collection."})
        normalized = set()
        try:
            iterator = iter(values)
        except TypeError as exc:
            raise ValidationError({field: "Cleanup source ids must be a collection."}) from exc
        for value in iterator:
            text = str(value or "").strip()
            if text:
                normalized.add(text)
        return normalized

    task_external_ids = normalize_ids(task_external_ids, "task_external_ids")
    sample_external_ids = normalize_ids(sample_external_ids, "sample_external_ids")
    if not task_external_ids and not sample_external_ids:
        raise ValidationError({"manifest": "A complete non-empty import manifest is required for cleanup."})

    computed_manifest_digest = _import_manifest_digest(
        source=source,
        task_external_ids=task_external_ids,
        sample_external_ids=sample_external_ids,
    )

    _lock_tenant(user)
    try:
        locked_batch = ImportBatch.objects.select_for_update().get(
            pk=batch_id,
            tenant_id=user.tenant_id,
            source=source,
            status=ImportBatch.Status.COMPLETED,
        )
    except ImportBatch.DoesNotExist as exc:
        raise ValidationError(
            {"batch": "Cleanup requires a persisted completed import batch for this tenant and source."}
        ) from exc

    batch_key = str(locked_batch.batch_key or "").strip()
    if not batch_key:
        raise ValidationError({"batch": "Import batch key is required for idempotent cleanup."})
    persisted_manifest_digest = str(locked_batch.manifest_digest or "").strip().lower()
    if persisted_manifest_digest != computed_manifest_digest:
        raise ValidationError(
            {"manifest": "Cleanup manifest does not match the persisted completed import batch."},
            code="conflict",
        )
    if manifest_digest not in (None, ""):
        supplied_manifest_digest = str(manifest_digest).strip().lower()
        if supplied_manifest_digest != computed_manifest_digest:
            raise ValidationError(
                {"manifest": "Supplied cleanup manifest digest does not match the input ids."},
                code="conflict",
            )

    from apps.audit.models import OperationLog

    aggregate_key = f"{source}:{locked_batch.pk}:soft-delete"
    previous_log = OperationLog.objects.filter(
        tenant_id=user.tenant_id,
        module="influencers",
        action="feishu_import_source_soft_delete",
        object_type="import_batch",
        object_id=aggregate_key,
    ).first()
    if previous_log is not None:
        after_data = previous_log.after_data if isinstance(previous_log.after_data, Mapping) else {}
        return {
            "source": source,
            "batch_key": batch_key,
            "manifest_digest": persisted_manifest_digest,
            "task_deleted": int(after_data.get("task_deleted", 0) or 0),
            "sample_deleted": int(after_data.get("sample_deleted", 0) or 0),
            "replayed": True,
        }

    # Cleanup is a snapshot reconciliation for this exact source.  Legacy
    # records are eligible for adoption only when an incoming row hits the same
    # business key; an unmatched legacy record may belong to another historical
    # export and must remain untouched.
    allowed_sources = (source,)
    missing_samples = list(
        SampleFulfillment.objects.select_for_update()
        .filter(
            tenant_id=user.tenant_id,
            source__in=allowed_sources,
            is_deleted=False,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id="")
        .exclude(external_id__in=sample_external_ids)
        .order_by("id")
    )
    missing_tasks = list(
        OutreachTask.objects.select_for_update()
        .filter(
            tenant_id=user.tenant_id,
            source__in=allowed_sources,
            is_deleted=False,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id="")
        .exclude(external_id__in=task_external_ids)
        .order_by("id")
    )

    deleted_samples = 0
    for fulfillment in missing_samples:
        soft_delete_sample_fulfillment(
            user=user,
            fulfillment=fulfillment,
            expected_version=fulfillment.version,
            recompute_related=False,
        )
        deleted_samples += 1
    deleted_tasks = 0
    for task in missing_tasks:
        soft_delete_outreach_task(
            user=user,
            task=task,
            expected_version=task.version,
        )
        deleted_tasks += 1

    write_operation_log(
        tenant=tenant,
        user=user,
        module="influencers",
        action="feishu_import_source_soft_delete",
        object_type="import_batch",
        object_id=aggregate_key,
        before_data={
            "source": source,
            "batch_key": batch_key,
            "batch_id": locked_batch.pk,
            "manifest_digest": persisted_manifest_digest,
            "task_external_count": len(task_external_ids),
            "sample_external_count": len(sample_external_ids),
            "reason": reason,
        },
        after_data={
            "source": source,
            "batch_key": batch_key,
            "batch_id": locked_batch.pk,
            "manifest_digest": persisted_manifest_digest,
            "task_external_count": len(task_external_ids),
            "sample_external_count": len(sample_external_ids),
            "task_deleted": deleted_tasks,
            "sample_deleted": deleted_samples,
            "preserves_related_data": True,
        },
    )
    return {
        "source": source,
        "batch_key": batch_key,
        "manifest_digest": persisted_manifest_digest,
        "task_deleted": deleted_tasks,
        "sample_deleted": deleted_samples,
        "replayed": False,
    }


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
    _lock_tenant(user)
    fulfillment = _locked_sample_fulfillment(user=user, fulfillment=fulfillment)
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
                _lock_tenant(actor)
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
