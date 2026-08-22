"""Shared, fail-closed API helpers for the supply-flow wave.

The domain services remain the only write boundary.  This module only performs
channel/permission/scope checks and builds small DTO envelopes; it deliberately
does not expose model ``save`` or queryset mutation helpers.
"""

from __future__ import annotations

from functools import wraps
from operator import and_
from typing import Iterable

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Prefetch
from rest_framework.decorators import permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.accounts.models import CustomUser
from apps.accounts.miniapp_auth import MINIAPP_TOKEN_CHANNEL
from apps.accounts.miniapp_permissions import IsMiniAppToken
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied, ScopedResourceNotFound
from apps.common.responses import success_response
from apps.masterdata.models import StatusChoices, SupplierMaster
from apps.packing.permissions import IsNonMiniAppChannel, supplier_id_for_user
from apps.packing.models import PackingBatchOrder, PackingBox
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes


SUPPLIER_WEB = "supplier_web"
MINIAPP = "miniapp"
INTERNAL = "internal"

# The API contract intentionally forbids partial/union scopes.  Every custom
# scope must describe all dimensions that can be present in a historical
# consolidation/shipment snapshot.
CUSTOM_SCOPE_KEYS = frozenset({
    "supplier_ids",
    "supply_purchase_order_ids",
    "packing_batch_ids",
    "consolidation_site_ids",
    "consolidation_ids",
})
SHIPMENT_SCOPE_KEYS = frozenset({*CUSTOM_SCOPE_KEYS, "shipment_ids"})


class IsSupplyChainInternal(BasePermission):
    """Marker permission; individual views call ``require_internal``."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.user_type == CustomUser.UserType.INTERNAL
        )


class IsSupplyChainSupplier(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.user_type == CustomUser.UserType.EXTERNAL
        )


def require_json(request):
    if request.content_type != "application/json":
        raise ValidationError({"content_type": "Content-Type application/json is required."})


def require_key(request) -> str:
    value = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
    if not value or len(value) > 128 or any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in value):
        raise ValidationError({"idempotency_key": "A printable Idempotency-Key (1-128 chars) is required."})
    return value


def _positive_ids(value, key):
    if not isinstance(value, (list, tuple)) or not value or len(value) > 5000:
        raise DataScopeDenied(f"CUSTOM scope {key} must contain one to 5000 IDs.", error_code=ErrorCode.DATA_SCOPE_INVALID)
    parsed = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise DataScopeDenied(f"CUSTOM scope {key} contains an invalid ID.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        parsed.append(int(item))
    if len(set(parsed)) != len(parsed):
        raise DataScopeDenied(f"CUSTOM scope {key} contains duplicate IDs.", error_code=ErrorCode.DATA_SCOPE_INVALID)
    return frozenset(parsed)


def validate_supply_scopes(scopes, *, include_shipment=False):
    if not scopes:
        raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
    validated = []
    for scope in scopes:
        scope_type = scope.get("scope_type")
        config = scope.get("config")
        if not isinstance(config, dict):
            raise DataScopeDenied("Data-scope config must be a JSON object.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        if scope_type == DataScope.ScopeType.ALL:
            validated.append({"scope_type": scope_type, "config": {}})
            continue
        if scope_type in {DataScope.ScopeType.OWN, DataScope.ScopeType.DEPARTMENT}:
            raise DataScopeDenied("OWN and DEPARTMENT scopes are not supported for supply-flow APIs.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        if scope_type != DataScope.ScopeType.CUSTOM:
            raise DataScopeDenied("A complete CUSTOM scope is required.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        expected_keys = SHIPMENT_SCOPE_KEYS if include_shipment else CUSTOM_SCOPE_KEYS
        if set(config) != set(expected_keys):
            raise DataScopeDenied("CUSTOM scope must include all supply-flow dimensions.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        validated.append({"scope_type": scope_type, "config": {key: _positive_ids(config[key], key) for key in expected_keys}})
    return validated


def require_internal(user, permission_code):
    if not (
        user and user.is_authenticated and user.is_active
        and user.user_type == CustomUser.UserType.INTERNAL
        and check_user_permission(user, permission_code)
    ):
        raise PermissionDenied("The requested supply-chain permission is not available.")
    return validate_supply_scopes(
        get_permission_data_scopes(user, permission_code),
        include_shipment=permission_code.startswith("supply.shipment."),
    )


def require_supplier(user):
    """Resolve a tenant-bound active external supplier profile."""
    supplier_id = supplier_id_for_user(user)
    if not SupplierMaster.objects.filter(tenant=user.tenant, pk=supplier_id, status=StatusChoices.ACTIVE).exists():
        raise PermissionDenied("The supplier account is not active.")
    return int(supplier_id)


def assert_channel(request, channel):
    token = request.auth
    token_channel = token.get("channel") if token else None
    if channel == MINIAPP:
        if token_channel != MINIAPP_TOKEN_CHANNEL:
            raise PermissionDenied("A Mini Program token is required for this channel.")
    elif token_channel == MINIAPP_TOKEN_CHANNEL:
        raise PermissionDenied("A Mini Program token cannot access this API channel.")


def _scope_matches_dims(scope, dims: dict[str, Iterable[int | None]]):
    if scope["scope_type"] == DataScope.ScopeType.ALL:
        return True
    cfg = scope["config"]
    keys = SHIPMENT_SCOPE_KEYS if "shipment_ids" in cfg else CUSTOM_SCOPE_KEYS
    for key in keys:
        values = {int(value) for value in (dims.get(key) or ()) if value is not None}
        if not values <= cfg[key]:
            return False
    return True


def _allocation_dims(allocation):
    return {
        "supplier_ids": [allocation.supplier_id_snapshot],
        "supply_purchase_order_ids": list(allocation.order_ids_snapshot or ([allocation.order_id_snapshot] if allocation.order_id_snapshot else [])),
        "packing_batch_ids": [allocation.batch_id_snapshot],
        "consolidation_site_ids": [getattr(allocation.consolidation, "site_id", None)],
        "consolidation_ids": [allocation.consolidation_id],
    }


def consolidation_dimensions(item):
    dims = {
        "supplier_ids": [], "supply_purchase_order_ids": [], "packing_batch_ids": [],
        "consolidation_site_ids": [item.site_id], "consolidation_ids": [item.id],
    }
    for allocation in item.allocations.all():
        child = _allocation_dims(allocation)
        for key in dims:
            dims[key].extend(child[key])
    return dims


def shipment_dimensions(item):
    dims = {
        "supplier_ids": [], "supply_purchase_order_ids": [], "packing_batch_ids": [],
        "consolidation_site_ids": [], "consolidation_ids": [],
        "shipment_ids": [item.id],
    }
    for allocation in item.box_allocations.all():
        dims["supplier_ids"].append(allocation.supplier_id_snapshot)
        dims["supply_purchase_order_ids"].extend(allocation.order_ids_snapshot or [])
        dims["packing_batch_ids"].append(allocation.batch_id_snapshot)
        dims["consolidation_site_ids"].append(allocation.consolidation.site_id)
        dims["consolidation_ids"].append(allocation.consolidation_id)
    # A draft shipment without an origin cannot be safely scoped by the
    # five-dimensional CUSTOM contract; use a negative sentinel so it is
    # denied instead of treating every empty dimension as a match.
    dims["consolidation_site_ids"].append(item.origin_site_id_snapshot or -1)
    return dims


def authorize_consolidation_allocations_for_scope(user, scopes, *, allocation_ids, shipment_id=None):
    from apps.consolidation.models import ConsolidationBoxAllocation
    ids = sorted({int(value) for value in allocation_ids})
    allocations = list(ConsolidationBoxAllocation.objects.filter(
        tenant=user.tenant, pk__in=ids,
    ).select_related("consolidation"))
    if len(allocations) != len(ids):
        raise ScopedResourceNotFound("One or more consolidation allocations are not in the authorized scope.")
    for allocation in allocations:
        dims = _allocation_dims(allocation)
        if shipment_id is not None:
            dims["shipment_ids"] = [shipment_id]
        if not scope_allows(scopes, dims):
            raise DataScopeDenied("One or more source allocations are outside the shipment data scope.", error_code=ErrorCode.DATA_SCOPE_FORBIDDEN)
    return allocations


def scope_allows(scopes, dims):
    return any(_scope_matches_dims(scope, dims) for scope in scopes)


def authorized_consolidation(queryset, user, permission_code, pk=None):
    scopes = require_internal(user, permission_code)
    queryset = queryset.filter(tenant=user.tenant).prefetch_related("allocations")
    if pk is not None:
        item = queryset.filter(pk=pk).first()
        if item is None or not scope_allows(scopes, consolidation_dimensions(item)):
            raise ScopedResourceNotFound("Consolidation is not available in the authorized scope.")
        return item, scopes
    return [item for item in queryset if scope_allows(scopes, consolidation_dimensions(item))], scopes


def authorized_site(queryset, user, permission_code, pk=None):
    scopes = require_internal(user, permission_code)
    queryset = queryset.filter(tenant=user.tenant)
    if pk is not None:
        item = queryset.filter(pk=pk).first()
        if item is None or not any(
            scope["scope_type"] == DataScope.ScopeType.ALL
            or item.id in scope["config"]["consolidation_site_ids"]
            for scope in scopes
        ):
            raise ScopedResourceNotFound("Consolidation site is not available in the authorized scope.")
        return item, scopes
    return [item for item in queryset if any(
        scope["scope_type"] == DataScope.ScopeType.ALL
        or item.id in scope["config"]["consolidation_site_ids"]
        for scope in scopes
    )], scopes


def authorized_shipment(queryset, user, permission_code, pk=None):
    scopes = require_internal(user, permission_code)
    queryset = queryset.filter(tenant=user.tenant).prefetch_related("box_allocations__consolidation")
    if pk is not None:
        item = queryset.filter(pk=pk).first()
        if item is None or not scope_allows(scopes, shipment_dimensions(item)):
            raise ScopedResourceNotFound("Shipment is not available in the authorized scope.")
        return item, scopes
    return [item for item in queryset if scope_allows(scopes, shipment_dimensions(item))], scopes


def authorize_box_ids_for_scope(user, scopes, *, box_ids, site_id, consolidation_id):
    """Require every newly allocated box to fit one complete CUSTOM scope."""
    ids = sorted({int(value) for value in box_ids})
    boxes = list(PackingBox.objects.filter(tenant=user.tenant, pk__in=ids).select_related("batch"))
    if len(boxes) != len(ids):
        raise ScopedResourceNotFound("One or more packing boxes are not available in the authorized scope.")
    order_map = {}
    for row in PackingBatchOrder.objects.filter(tenant=user.tenant, batch_id__in=[box.batch_id for box in boxes]):
        order_map.setdefault(row.batch_id, set()).add(int(row.order_id))
    for box in boxes:
        dims = {
            "supplier_ids": [box.batch.supplier_id],
            "supply_purchase_order_ids": sorted(order_map.get(box.batch_id, set())),
            "packing_batch_ids": [box.batch_id],
            "consolidation_site_ids": [site_id],
            "consolidation_ids": [consolidation_id],
        }
        if not scope_allows(scopes, dims):
            raise DataScopeDenied("One or more boxes are outside the allocation data scope.", error_code=ErrorCode.DATA_SCOPE_FORBIDDEN)
    return boxes


def supplier_allocation(queryset, user, allocation_id):
    supplier_id = require_supplier(user)
    item = queryset.filter(tenant=user.tenant, pk=allocation_id, supplier_id_snapshot=supplier_id).first()
    if item is None:
        raise ScopedResourceNotFound("The assignment is not available for this supplier.")
    return item, supplier_id


def page_payload(request, items, transform):
    try:
        page = int(request.query_params.get("page", 1))
        size = int(request.query_params.get("page_size", 20))
    except (TypeError, ValueError):
        raise ValidationError({"page": "page and page_size must be positive integers."})
    if page < 1 or size < 1 or size > 100:
        raise ValidationError({"page": "page must be positive and page_size must be 1-100."})
    paginator = Paginator(list(items), size)
    if page > max(1, paginator.num_pages):
        raise ScopedResourceNotFound("Requested page does not exist.")
    page_obj = paginator.page(page)
    return {
        "count": paginator.count,
        "next": None,
        "previous": None,
        "results": [transform(item) for item in page_obj.object_list],
    }


def event_result(obj, event, replayed, transform):
    response = success_response(transform(obj))
    response["Idempotency-Replayed"] = "true" if replayed else "false"
    return response


def internal_permissions(*permission_codes):
    """Decorative DRF permission classes; actual code is checked per method."""
    return permission_classes([IsAuthenticated, IsSupplyChainInternal, IsNonMiniAppChannel])


def supplier_permissions(*, miniapp=False):
    return permission_classes([IsAuthenticated, IsSupplyChainSupplier, IsMiniAppToken] if miniapp else [IsAuthenticated, IsSupplyChainSupplier, IsNonMiniAppChannel])


def local_upload_enabled():
    return bool(getattr(settings, "SUPPLY_FLOW_LOCAL_UPLOAD_ENABLED", False))
